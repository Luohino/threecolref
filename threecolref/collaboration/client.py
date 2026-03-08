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

"""Socket.IO async client that runs in its own thread.

Incoming events are forwarded to the Qt main thread via
:class:`PyQt6.QtCore.pyqtSignal` so scene modifications are always
performed on the GUI thread.
"""

import asyncio
import logging
import threading
import uuid

import socketio

from PyQt6 import QtCore

from threecolref.collaboration import protocol

logger = logging.getLogger(__name__)


class CollaborationClient(QtCore.QObject):
    """Wraps a ``socketio.AsyncClient`` and bridges events to Qt signals."""

    # --- Qt signals (emitted on the main thread) ---
    connected = QtCore.pyqtSignal()
    disconnected = QtCore.pyqtSignal()
    kicked = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)

    remote_item_added = QtCore.pyqtSignal(dict)
    remote_item_moved = QtCore.pyqtSignal(dict)
    remote_item_transformed = QtCore.pyqtSignal(dict)
    remote_item_removed = QtCore.pyqtSignal(dict)
    remote_cursor_moved = QtCore.pyqtSignal(dict)
    remote_full_sync_request = QtCore.pyqtSignal(dict)
    remote_full_sync_response = QtCore.pyqtSignal(dict)
    remote_session_join = QtCore.pyqtSignal(dict)
    remote_session_leave = QtCore.pyqtSignal(dict)
    remote_doodle_start = QtCore.pyqtSignal(dict)
    remote_doodle_point = QtCore.pyqtSignal(dict)
    remote_doodle_end = QtCore.pyqtSignal(dict)
    remote_sync_start = QtCore.pyqtSignal(dict)
    remote_sync_end = QtCore.pyqtSignal(dict)


    def __init__(self, parent=None):
        super().__init__(parent)
        from threecolref.config import BeeSettings
        settings = BeeSettings()
        
        self.user_id: str = uuid.uuid4().hex[:8]
        custom_name = settings.valueOrDefault('Collaboration/username')
        self.username: str = custom_name if custom_name else f'User-{self.user_id[:4]}'
        self.room_id: str = 'default'

        self.sio = socketio.AsyncClient(reconnection=True,
                                        reconnection_attempts=10,
                                        reconnection_delay=1)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._connected = False

        self._register_handlers()

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Socket.IO event handlers → Qt signals
    # ------------------------------------------------------------------

    def _register_handlers(self):
        @self.sio.event
        async def connect():
            logger.info('[client] Connected to server')
            self._connected = True
            # Re-announce ourselves if we were already in a session
            await self.sio.emit(protocol.SESSION_JOIN, {
                'user_id': self.user_id,
                'username': self.username,
                'room_id': self.room_id,
            })
            self.connected.emit()


        @self.sio.event
        async def disconnect():
            logger.info('[client] Disconnected from server')
            self._connected = False
            self.disconnected.emit()

        @self.sio.event
        async def connect_error(data):
            logger.error(f'[client] Connection error: {data}')
            self.error.emit(str(data))

        @self.sio.on(protocol.SESSION_KICKED)
        async def on_kicked(data):
            logger.info('[client] Kicked by host')
            self._connected = False
            # Prevent socketio from trying to reconnect
            try:
                await self.sio.disconnect()
            except Exception:
                pass
            self.kicked.emit()

        # Map server events → Qt signals
        _mapping = {
            protocol.ITEM_ADDED: self.remote_item_added,
            protocol.ITEM_MOVED: self.remote_item_moved,
            protocol.ITEM_TRANSFORMED: self.remote_item_transformed,
            protocol.ITEM_REMOVED: self.remote_item_removed,
            protocol.CURSOR_MOVED: self.remote_cursor_moved,
            protocol.FULL_SYNC_REQUEST: self.remote_full_sync_request,
            protocol.FULL_SYNC_RESPONSE: self.remote_full_sync_response,
            protocol.SESSION_JOIN: self.remote_session_join,
            protocol.SESSION_LEAVE: self.remote_session_leave,
            protocol.DOODLE_START: self.remote_doodle_start,
            protocol.DOODLE_POINT: self.remote_doodle_point,
            protocol.DOODLE_END: self.remote_doodle_end,
            protocol.SYNC_START: self.remote_sync_start,
            protocol.SYNC_END: self.remote_sync_end,
        }

        for event_name, signal in _mapping.items():
            self._bind(event_name, signal)

    def _bind(self, event_name, signal):
        @self.sio.on(event_name)
        async def _handler(data):
            # Skip messages that originated from us
            if isinstance(data, dict) and data.get('user_id') == self.user_id:
                return
            logger.debug(f'[client] received {event_name}')
            signal.emit(data)

    # ------------------------------------------------------------------
    # Public helpers – schedule coroutines on the background loop
    # ------------------------------------------------------------------

    def connect_to(self, url: str, room_id: str = 'default'):
        """Connect to the server at *url* and join *room_id*."""
        self.room_id = room_id
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, args=(url,), daemon=True, name='collab-client')
        self._thread.start()

    def _run(self, url):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_wait(url))
        except (RuntimeError, asyncio.CancelledError):
            # Happens when the loop is stopped/closed during run_until_complete
            logger.debug('[client] Loop stopped during run')
        finally:
            try:
                self._loop.close()
            except:
                pass
            logger.info('[client] Stopped')

    async def _connect_and_wait(self, url):
        try:
            await self.sio.connect(url, transports=['websocket'])
            # Announce ourselves
            await self.sio.emit(protocol.SESSION_JOIN, {
                'user_id': self.user_id,
                'username': self.username,
                'room_id': self.room_id,
            })
            await self.sio.wait()
        except Exception as exc:
            logger.error(f'[client] Fatal: {exc}', exc_info=True)
            self.error.emit(str(exc))

    def emit(self, event: str, data: dict):
        """Thread-safe emit: schedule on the client's event loop."""
        if self._loop and self._connected:
            asyncio.run_coroutine_threadsafe(
                self.sio.emit(event, data), self._loop)

    def stop(self):
        """Disconnect and tear down the background thread."""
        self._connected = False
        if self._loop and self._loop.is_running():
            # Schedule a graceful disconnect, then stop the loop
            async def _shutdown():
                try:
                    if self.sio.connected:
                        await self.sio.disconnect()
                except Exception:
                    pass
                self._loop.stop()

            asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
        if self._thread:
            self._thread.join(timeout=5)
        logger.info('[client] Stopped')
