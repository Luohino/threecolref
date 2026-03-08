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

"""High-level collaboration manager used by the UI layer.

This is the *single entry point* the rest of the application uses to
start/stop collaboration and to broadcast local scene changes.
"""

import base64
import logging
import time

from PyQt6 import QtCore, QtGui, QtWidgets

from threecolref.collaboration import protocol
from threecolref.collaboration.client import CollaborationClient
from threecolref.collaboration.server import CollaborationServer
from threecolref.collaboration.session import (
    decode_code, generate_code, get_local_ip,
    generate_cloud_code, is_cloud_code
)
from threecolref import constants

logger = logging.getLogger(__name__)

# Throttle cursor broadcasts to ~10 fps for high-capacity sessions
_CURSOR_INTERVAL_MS = 100


class CollaborationManager(QtCore.QObject):
    """Orchestrates server, client, and scene integration."""

    # Signals for the UI
    status_changed = QtCore.pyqtSignal(str)    # 'connected' | 'disconnected' | 'hosting'
    user_count_changed = QtCore.pyqtSignal(int)
    error_occurred = QtCore.pyqtSignal(str)

    # Signals the view connects to for applying remote changes
    remote_item_added = QtCore.pyqtSignal(dict)
    remote_item_moved = QtCore.pyqtSignal(dict)
    remote_item_transformed = QtCore.pyqtSignal(dict)
    remote_item_removed = QtCore.pyqtSignal(dict)
    remote_cursor_moved = QtCore.pyqtSignal(dict)
    remote_session_join = QtCore.pyqtSignal(dict)
    remote_session_leave = QtCore.pyqtSignal(dict)
    remote_user_left = QtCore.pyqtSignal(str)
    remote_full_sync_request = QtCore.pyqtSignal(dict)   # host should respond
    remote_full_sync_response = QtCore.pyqtSignal(dict)  # joiner applies
    remote_doodle_start = QtCore.pyqtSignal(dict)
    remote_doodle_point = QtCore.pyqtSignal(dict)
    remote_doodle_end = QtCore.pyqtSignal(dict)
    remote_sync_start = QtCore.pyqtSignal(dict)
    remote_sync_end = QtCore.pyqtSignal(dict)


    def __init__(self, parent=None):
        super().__init__(parent)
        self._server: CollaborationServer | None = None
        self._client: CollaborationClient | None = None
        self._is_hosting = False
        self._session_code: str | None = None
        self._connected_users: dict[str, dict] = {}
        self._last_cursor_broadcast = 0.0

        # Counter to suppress re-broadcasting during remote event application
        self._remote_apply_depth = 0
        
        # O(1) Lookup Cache: mapping collab_id -> QGraphicsItem
        self._collab_items: dict[str, QtWidgets.QGraphicsItem] = {}

        # Render Keep-Alive: Ping server every 10 mins to avoid free-tier spin-down
        # Heartbeat is ONLY active during a collaboration session.
        self._heartbeat_timer = QtCore.QTimer(self)
        self._heartbeat_timer.timeout.connect(self._send_heartbeat)
        
        # Initial "warm up" ping on app launch
        self.ensure_server_awake()


    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def is_hosting(self) -> bool:
        return self._is_hosting

    @property
    def session_code(self) -> str | None:
        return self._session_code

    @property
    def username(self) -> str:
        return self._client.username if self._client else 'Unknown'

    @property
    def user_id(self) -> str | None:
        return self._client.user_id if self._client else None

    @property
    def applying_remote(self) -> bool:
        """True while a remote event is being applied to the local scene.
        Commands / scene hooks check this to avoid re-broadcasting."""
        return self._remote_apply_depth > 0

    def begin_remote_apply(self):
        """Call before applying any remote scene change to suppress re-broadcast."""
        self._remote_apply_depth += 1

    def end_remote_apply(self):
        """Call after applying remote scene change(s) to re-enable broadcasting."""
        self._remote_apply_depth = max(0, self._remote_apply_depth - 1)

    def register_item(self, item_id: str, item: QtWidgets.QGraphicsItem):
        """Register an item in the collaboration cache."""
        self._collab_items[item_id] = item

    def unregister_item(self, item_id: str):
        """Remove an item from the collaboration cache."""
        self._collab_items.pop(item_id, None)

    def get_item(self, item_id: str) -> QtWidgets.QGraphicsItem | None:
        """Find a cached item by its collab_id, with safety checks."""
        item = self._collab_items.get(item_id)
        if item is None:
            return None
        
        # STABILITY: Check if the underlying C++ object was deleted.
        # This prevents RuntimeError: wrapped C/C++ object has been deleted.
        try:
            # Accessing any property will trigger RuntimeError if C++ object is gone
            _ = item.scene() 
        except (RuntimeError, AttributeError):
            logger.debug(f"[collab] Auto-unregistering deleted item {item_id}")
            self.unregister_item(item_id)
            return None
            
        return item


    # ------------------------------------------------------------------
    # Keep-Alive Heartbeat
    # ------------------------------------------------------------------

    def _send_heartbeat(self):
        """Asynchronously ping the Render server's /ping endpoint."""
        url = f"{constants.COLLAB_SERVER_URL}/ping"
        logger.debug(f"[collab] Sending keep-alive heartbeat to {url}")
        
        # Use a secondary thread to avoid blocking GUI on network timeout
        import urllib.request
        from threading import Thread
        
        def _ping():
            try:
                # This keeps the Render server 'warm' if it's the target URL
                with urllib.request.urlopen(url, timeout=5) as response:
                    if response.status == 200:
                        logger.debug("[collab] Heartbeat SUCCESS")
            except Exception as e:
                # Expected if offline or if COLLAB_SERVER_URL is local/invalid
                logger.debug(f"[collab] Heartbeat skipped/failed: {e}")

        Thread(target=_ping, daemon=True).start()

    def ensure_server_awake(self):
        """Manually trigger a ping to wake up the server (e.g. when opening menus)."""
        self._send_heartbeat()


    # ------------------------------------------------------------------
    # Start / Join / Stop
    # ------------------------------------------------------------------

    def start_sharing(self) -> str:
        """Start a local server and connect to it.  Returns the session
        code that other users can use to join.
        """
        self.stop()  # clean up any previous session

        self._server = CollaborationServer()
        self._server.start(port=0)

        if self._server.port is None:
            raise RuntimeError('Server failed to start')

        host = get_local_ip()
        self._session_code = generate_code(host, self._server.port)
        self._is_hosting = True

        # Connect our own client to the local server
        self._setup_client()
        self._client.connect_to(f'http://127.0.0.1:{self._server.port}')

        self.status_changed.emit('hosting')
        logger.info(f'Sharing started – code: {self._session_code}')
        return self._session_code

    def start_cloud_sharing(self) -> str:
        """Start a session on the global Render backend."""
        self.stop()
        
        # We don't start a local server, we just connect to the global one
        self._session_code = generate_cloud_code()
        self._is_hosting = True
        
        self._setup_client()
        # Room ID is the part after "C-"
        room_id = self._session_code[2:]
        self._client.connect_to(constants.COLLAB_SERVER_URL, room_id=room_id)
        
        self.status_changed.emit('hosting')
        logger.info(f'Cloud sharing started – code: {self._session_code}')
        return self._session_code

    def join_session(self, code: str):
        """Join a session using a code (could be Local or Cloud)."""
        self.stop()
        self._session_code = code
        self._is_hosting = False
        self._heartbeat_timer.start(600000) # Keep server alive during session
        
        self._setup_client()

        if is_cloud_code(code):
            room_id = code[2:]
            logger.info(f'Joining Cloud session: {room_id}')
            self._client.connect_to(constants.COLLAB_SERVER_URL, room_id=room_id)
        else:
            host, port = decode_code(code)
            logger.info(f'Joining Local session at {host}:{port}')
            self._client.connect_to(f'http://{host}:{port}')



    def stop(self):
        """Tear down client and server (if hosting)."""
        if self._client:
            self._client.stop()
            self._client.deleteLater()
            self._client = None
        if self._server:
            self._server.stop()
            self._server = None
        self._is_hosting = False
        self._session_code = None
        self._connected_users.clear()
        self._collab_items.clear()
        self._heartbeat_timer.stop() # Allow server to sleep after session ends
        self.status_changed.emit('disconnected')
        self.user_count_changed.emit(0)

    def kick_user(self, user_id: str):
        """Kick a user by their user_id (host only)."""
        if not self._is_hosting:
            return
            
        # Proactively remove from our local list for immediate visual feedback
        self._on_remote_leave({'user_id': user_id})

        if self._server:
            # Local hosting: directly tell the server to kick the sid
            self._server.kick_user_by_id(user_id)
            logger.info(f'Host (local) kicked user {user_id}')
        else:
            # Cloud hosting: emit a request to the Render backend to kick the sid
            if self._client and self._client.is_connected:
                self._client.emit(protocol.HOST_KICK, {'target_user_id': user_id})
                logger.info(f'Host (cloud) requested kick of user {user_id}')

    def get_connected_users(self) -> list[dict]:
        """Return a list of metadata for all connected peers."""
        return list(self._connected_users.values())

    # ------------------------------------------------------------------
    # Client setup & signal wiring
    # ------------------------------------------------------------------

    def _setup_client(self):
        self._client = CollaborationClient(parent=self)
        c = self._client

        # Connection lifecycle
        c.connected.connect(self._on_connected)
        c.disconnected.connect(self._on_disconnected)
        c.kicked.connect(self.stop)
        c.error.connect(self._on_error)

        # Remote scene events → re-emit so the view can handle them
        c.remote_item_added.connect(self.remote_item_added)
        c.remote_item_moved.connect(self.remote_item_moved)
        c.remote_item_transformed.connect(self.remote_item_transformed)
        c.remote_item_removed.connect(self.remote_item_removed)
        c.remote_cursor_moved.connect(self.remote_cursor_moved)
        c.remote_full_sync_request.connect(self.remote_full_sync_request)
        c.remote_full_sync_response.connect(self.remote_full_sync_response)
        c.remote_doodle_start.connect(self.remote_doodle_start)
        c.remote_doodle_point.connect(self.remote_doodle_point)
        c.remote_doodle_end.connect(self.remote_doodle_end)
        c.remote_sync_start.connect(self.remote_sync_start)
        c.remote_sync_end.connect(self.remote_sync_end)
        c.remote_session_join.connect(self.remote_session_join)
        c.remote_session_leave.connect(self.remote_session_leave)


        # Presence
        c.remote_session_join.connect(self._on_remote_join)
        c.remote_session_leave.connect(self._on_remote_leave)

    def _on_connected(self):
        logger.info('Collaboration client connected')
        # Fix: Don't overwrite 'hosting' status with 'connected'
        if self._is_hosting:
            self.status_changed.emit('hosting')
        else:
            self.status_changed.emit('connected')
            
        # Initialize user count (1 for self)
        self.user_count_changed.emit(1)
        
        # If we are joining, request the full scene immediately
        if not self._is_hosting:
            self.request_full_sync()

    def _on_disconnected(self):
        logger.info('Collaboration client disconnected')
        self.status_changed.emit('disconnected')

    def _on_error(self, msg):
        logger.error(f'Collaboration error: {msg}')
        self.error_occurred.emit(msg)

    def _on_remote_join(self, data):
        uid = data.get('user_id', '')
        self._connected_users[uid] = data
        self.user_count_changed.emit(len(self._connected_users) + 1)  # +1 for self
        self.remote_session_join.emit(data)

    def _on_remote_leave(self, data):
        uid = data.get('user_id') or data.get('sid', '')
        if uid in self._connected_users:
            self._connected_users.pop(uid, None)
            self.user_count_changed.emit(len(self._connected_users) + 1)
            self.remote_user_left.emit(uid)

    # ------------------------------------------------------------------
    # Broadcasting helpers (called from scene hooks)
    # ------------------------------------------------------------------

    def broadcast_item_added(self, item_id, item_type, data):
        if self.applying_remote or not self.is_active:
            return
        msg = protocol.make_item_added_msg(
            self._client.user_id, item_id, item_type, data)
        self._client.emit(protocol.ITEM_ADDED, msg)

    def broadcast_full_sync_response(self, items: list):
        """Send full scene state to requesting peers (host only)."""
        if not self.is_active:
            return
        msg = protocol.make_full_sync_response_msg(self._client.user_id, items)
        self._client.emit(protocol.FULL_SYNC_RESPONSE, msg)

    def broadcast_sync_start(self):
        if not self.is_active:
            return
        msg = protocol.make_sync_start_msg(self._client.user_id)
        self._client.emit(protocol.SYNC_START, msg)

    def broadcast_sync_end(self):
        if not self.is_active:
            return
        msg = protocol.make_sync_end_msg(self._client.user_id)
        self._client.emit(protocol.SYNC_END, msg)


    def request_full_sync(self):
        """Called by a joiner right after connecting — asks host for scene."""
        if not self.is_active:
            return
        msg = protocol.make_full_sync_request_msg(self._client.user_id)
        self._client.emit(protocol.FULL_SYNC_REQUEST, msg)

    def broadcast_item_moved(self, item_ids, dx, dy):
        if self.applying_remote or not self.is_active:
            return
        msg = protocol.make_item_moved_msg(
            self._client.user_id, item_ids, dx, dy)
        self._client.emit(protocol.ITEM_MOVED, msg)

    def broadcast_item_transformed(self, item_ids, transform_type, **kwargs):
        if self.applying_remote or not self.is_active:
            return
        msg = protocol.make_item_transformed_msg(
            self._client.user_id, item_ids, transform_type, **kwargs)
        self._client.emit(protocol.ITEM_TRANSFORMED, msg)

    def broadcast_item_removed(self, item_ids):
        if self.applying_remote or not self.is_active or not item_ids:
            return
        msg = protocol.make_item_removed_msg(self._client.user_id, item_ids)
        self._client.emit(protocol.ITEM_REMOVED, msg)
        
        # BUGFIX: Also unregister from local cache immediately so we don't
        # hold onto deleted C++ objects.
        for iid in item_ids:
            self.unregister_item(iid)

    def broadcast_cursor(self, x, y):
        if not self.is_active:
            return
        now = time.monotonic() * 1000
        if now - self._last_cursor_broadcast < _CURSOR_INTERVAL_MS:
            return
        self._last_cursor_broadcast = now
        msg = protocol.make_cursor_moved_msg(
            self._client.user_id, x, y, self._client.username)
        self._client.emit(protocol.CURSOR_MOVED, msg)

    def broadcast_doodle_start(self, item_id, item_type, color, width, x, y, parent_id=None):
        if self.applying_remote or not self.is_active:
            return
        msg = protocol.make_doodle_start_msg(
            self._client.user_id, item_id, item_type, color, width, x, y, parent_id)
        self._client.emit(protocol.DOODLE_START, msg)

    def broadcast_doodle_point(self, item_id, x, y):
        if self.applying_remote or not self.is_active:
            return

        # Throttle doodle points to ~60 fps
        now = time.monotonic() * 1000
        if not hasattr(self, '_last_doodle_broadcasts'):
            self._last_doodle_broadcasts = {}

        last = self._last_doodle_broadcasts.get(item_id, 0)
        if now - last < 33:  # Throttled to 30 FPS for extreme performance
            return

        self._last_doodle_broadcasts[item_id] = now
        msg = protocol.make_doodle_point_msg(
            self._client.user_id, item_id, x, y)
        self._client.emit(protocol.DOODLE_POINT, msg)

    def broadcast_doodle_end(self, item_id):
        if self.applying_remote or not self.is_active:
            return
        msg = protocol.make_doodle_end_msg(self._client.user_id, item_id)
        self._client.emit(protocol.DOODLE_END, msg)

