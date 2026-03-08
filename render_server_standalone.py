import os
import asyncio
import logging
import sys
import socketio
from aiohttp import web

# --- COLLABORATION PROTOCOL CONSTANTS (Inlined) ---
ITEM_ADDED = 'item_added'
ITEM_MOVED = 'item_moved'
ITEM_TRANSFORMED = 'item_transformed'
ITEM_REMOVED = 'item_removed'
CURSOR_MOVED = 'cursor_moved'
SESSION_JOIN = 'session_join'
SESSION_LEAVE = 'session_leave'
SESSION_KICKED = 'session_kicked'
HOST_KICK = 'host_kick'
FULL_SYNC_REQUEST = 'full_sync_request'
FULL_SYNC_RESPONSE = 'full_sync_response'
DOODLE_START = 'doodle_start'
DOODLE_POINT = 'doodle_point'
DOODLE_END = 'doodle_end'
SYNC_START = 'sync_start'
SYNC_END = 'sync_end'

# --- LOGGING CONFIG ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("beeref-backend")

_ROOM = 'collab'

class CollaborationServer:
    """Relay server that broadcasts events between clients."""
    
    _RELAY_EVENTS = (
        ITEM_ADDED, ITEM_MOVED, ITEM_TRANSFORMED, ITEM_REMOVED,
        CURSOR_MOVED, FULL_SYNC_REQUEST, FULL_SYNC_RESPONSE,
        DOODLE_START, DOODLE_POINT, DOODLE_END, SYNC_START, SYNC_END,
    )

    def __init__(self):
        self.sio = socketio.AsyncServer(
            async_mode='aiohttp',
            cors_allowed_origins='*',
            max_http_buffer_size=1024 * 1024 * 1024
        )
        self.app = web.Application()
        self.app.router.add_get('/ping', self._handle_ping)
        self.sio.attach(self.app)
        self.connected_users = {} # sid -> user_data
        self.sid_to_room = {}     # sid -> room_id
        self._register_handlers()

    async def _handle_ping(self, request):
        return web.Response(text="pong")

    def _register_handlers(self):
        @self.sio.event
        async def connect(sid, environ):
            logger.info(f'[server] Client connected: {sid}')
            self.connected_users[sid] = {'sid': sid}

        @self.sio.event
        async def disconnect(sid):
            logger.info(f'[server] Client disconnected: {sid}')
            user_data = self.connected_users.pop(sid, {})
            room_id = self.sid_to_room.pop(sid, None)
            
            if room_id:
                await self.sio.leave_room(sid, room_id)
                await self.sio.emit(SESSION_LEAVE, {**user_data, 'sid': sid}, room=room_id)

        @self.sio.event
        async def session_join(sid, data):
            uid = data.get('user_id', '')
            room_id = data.get('room_id', 'default')
            
            logger.info(f'[server] {sid} joining room: {room_id} (uid: {uid})')
            
            # Leave old room if any
            old_room = self.sid_to_room.get(sid)
            if old_room:
                await self.sio.leave_room(sid, old_room)
            
            self.connected_users[sid] = data
            self.sid_to_room[sid] = room_id
            await self.sio.enter_room(sid, room_id)
            
            # 1. Tell others in the room about the newcomer
            await self.sio.emit(SESSION_JOIN, data, room=room_id, skip_sid=sid)
            
            # 2. Tell the newcomer about everyone already in the room
            for other_sid, other_data in self.connected_users.items():
                if other_sid != sid and self.sid_to_room.get(other_sid) == room_id:
                    await self.sio.emit(SESSION_JOIN, other_data, to=sid)

        @self.sio.on(HOST_KICK)
        async def on_host_kick(sid, data):
            # For simplicity in this relay, we trust the kicker is the host.
            # In a production app, you'd check if 'sid' is the room owner.
            target_user_id = data.get('target_user_id')
            room_id = self.sid_to_room.get(sid)
            if not target_user_id or not room_id:
                return

            logger.info(f'[server] Host {sid} requested kick of user {target_user_id}')
            
            # Find the sid for this user_id in the same room
            target_sid = None
            for s, d in self.connected_users.items():
                if d.get('user_id') == target_user_id and self.sid_to_room.get(s) == room_id:
                    target_sid = s
                    break
            
            if target_sid:
                await self.sio.emit(SESSION_KICKED, {}, to=target_sid)
                await self.sio.disconnect(target_sid)
                logger.info(f'[server] Forcibly disconnected {target_sid}')

        for event_name in self._RELAY_EVENTS:
            self._register_relay(event_name)

    def _register_relay(self, event_name):
        @self.sio.on(event_name)
        async def _relay(sid, data):
            room_id = self.sid_to_room.get(sid)
            if room_id:
                await self.sio.emit(event_name, data, room=room_id, skip_sid=sid)

    async def _serve(self, port):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        logger.info(f'[server] Listening on 0.0.0.0:{port}')
        while True:
            await asyncio.sleep(3600)

async def main():
    port = int(os.environ.get("PORT", "8080"))
    server = CollaborationServer()
    try:
        await server._serve(port)
    except Exception as e:
        logger.fatal(f"Server crashed: {e}", exc_info=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
