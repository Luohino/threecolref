# This file is part of threecolref.
#
# threecolref is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# threecolref is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with threecolref.  If not, see <https://www.gnu.org/licenses/>.

"""Socket.IO server that relays collaboration events between clients.

The server runs inside a daemon :class:`threading.Thread` with its own
*asyncio* event loop so it never blocks the Qt main thread.
"""

import asyncio
import logging
import threading

import socketio
from aiohttp import web

from threecolref.collaboration import protocol

logger = logging.getLogger(__name__)

# The single room name used for a session (one room per server instance).
_ROOM = 'collab'


class CollaborationServer:
    """Thin relay server.  All events received from one client are
    broadcast to every *other* client in the room.
    """

    # Events the server simply relays without inspecting.
    _RELAY_EVENTS = (
        protocol.ITEM_ADDED,
        protocol.ITEM_MOVED,
        protocol.ITEM_TRANSFORMED,
        protocol.ITEM_REMOVED,
        protocol.CURSOR_MOVED,
        protocol.FULL_SYNC_REQUEST,
        protocol.FULL_SYNC_RESPONSE,
        protocol.DOODLE_START,
        protocol.DOODLE_POINT,
        protocol.DOODLE_END,
        protocol.SYNC_START,
        protocol.SYNC_END,
    )

    def __init__(self):
        self.sio = socketio.AsyncServer(
            async_mode='aiohttp',
            cors_allowed_origins='*',
            max_http_buffer_size=1024 * 1024 * 1024  # 1GB
        )

        self.app = web.Application()
        self.sio.attach(self.app)

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self.port: int | None = None
        self.connected_users: dict[str, dict] = {}  # sid -> info

        self._register_handlers()

    # ------------------------------------------------------------------
    # Socket.IO handlers
    # ------------------------------------------------------------------

    def _register_handlers(self):
        @self.sio.event
        async def connect(sid, environ):
            logger.info(f'[server] Client connected: {sid}')
            await self.sio.enter_room(sid, _ROOM)
            self.connected_users[sid] = {'sid': sid}

        @self.sio.event
        async def disconnect(sid):
            logger.info(f'[server] Client disconnected: {sid}')
            user_data = self.connected_users.pop(sid, {})
            await self.sio.leave_room(sid, _ROOM)
            # Notify remaining clients with full user data (so they can map sid to uid)
            await self.sio.emit(
                protocol.SESSION_LEAVE,
                {**user_data, 'sid': sid},
                room=_ROOM,
            )

        @self.sio.event
        async def session_join(sid, data):
            # 1. Update our record of this user
            uid = data.get('user_id', '')
            logger.info(f'[server] session_join from {sid} (uid: {uid})')
            self.connected_users[sid] = data
            
            # 2. Tell everyone else about the newcomer
            await self.sio.emit(
                protocol.SESSION_JOIN,
                data,
                room=_ROOM,
                skip_sid=sid,
            )
            
            # 3. Tell the NEWCOMER about everyone already here
            # (Important for joiner to see host and other peers)
            for other_sid, other_data in self.connected_users.items():
                if other_sid != sid:
                    await self.sio.emit(protocol.SESSION_JOIN, other_data, to=sid)

        @self.sio.on(protocol.HOST_KICK)
        async def on_host_kick(sid, data):
            target_user_id = data.get('target_user_id')
            if not target_user_id:
                return
                
            logger.info(f'[server] Host {sid} requested kick of user {target_user_id}')
            self.kick_user_by_id(target_user_id)


        # Register generic relay for every event type
        for event_name in self._RELAY_EVENTS:
            self._register_relay(event_name)

    def _register_relay(self, event_name):
        @self.sio.on(event_name)
        async def _relay(sid, data):
            logger.debug(f'[server] relay {event_name} from {sid}')
            await self.sio.emit(event_name, data, room=_ROOM, skip_sid=sid)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, port: int = 0):
        """Start the server on *port* (0 = auto-pick) in a background thread."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, args=(port,), daemon=True, name='collab-server')
        self._thread.start()

        # Wait until the server has picked a port
        for _ in range(50):  # up to 5 s
            if self.port is not None:
                break
            import time
            time.sleep(0.1)

    def _run(self, port):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve(port))

    async def _serve(self, port):
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, '0.0.0.0', port)
        await site.start()

        # Resolve actual port
        sockets = site._server.sockets  # type: ignore[union-attr]
        if sockets:
            self.port = sockets[0].getsockname()[1]
        logger.info(f'[server] Listening on 0.0.0.0:{self.port}')

        # Keep running until the loop is stopped
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass

    def kick_user(self, sid: str):
        """Forcibly disconnect a user by their session ID (sid)."""
        if self._loop and self._loop.is_running():
            async def _kick():
                await self.sio.emit(protocol.SESSION_KICKED, {}, to=sid)
                await self.sio.disconnect(sid)
            asyncio.run_coroutine_threadsafe(_kick(), self._loop)
            logger.info(f'[server] Kicked user: {sid}')

    def kick_user_by_id(self, user_id: str):
        """Find a user by their user_id and kick them."""
        target_sid = None
        for sid, data in self.connected_users.items():
            if data.get('user_id') == user_id:
                target_sid = sid
                break
        if target_sid:
            self.kick_user(target_sid)

    def stop(self):
        """Shut down the server and its thread."""
        if self._loop and self._loop.is_running():
            # Cancel all tasks
            for task in asyncio.all_tasks(self._loop):
                self._loop.call_soon_threadsafe(task.cancel)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=3)
        self.port = None
        self.connected_users.clear()
        logger.info('[server] Stopped')
