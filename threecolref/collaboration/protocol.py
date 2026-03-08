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

"""Socket.IO event names and message helpers for real-time collaboration."""


# --- Event names ---
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



def make_item_added_msg(user_id, item_id, item_type, data):
    """Build an ITEM_ADDED payload.

    *data* should contain all fields needed to reconstruct the item on the
    remote side (position, scale, rotation, flip, image bytes, etc.).
    """
    return {
        'user_id': user_id,
        'item_id': item_id,
        'item_type': item_type,
        'data': data,
    }


def make_item_moved_msg(user_id, item_ids, dx, dy):
    return {
        'user_id': user_id,
        'item_ids': item_ids,
        'dx': dx,
        'dy': dy,
    }


def make_item_transformed_msg(user_id, item_ids, transform_type, **kwargs):
    """*transform_type*: 'scale', 'rotate', 'flip', 'crop', 'opacity',
    'grayscale', 'reset_scale', 'reset_rotation', 'reset_flip',
    'reset_crop', 'reset_transforms'.
    """
    return {
        'user_id': user_id,
        'item_ids': item_ids,
        'transform_type': transform_type,
        **kwargs,
    }


def make_item_removed_msg(user_id, item_ids):
    return {
        'user_id': user_id,
        'item_ids': item_ids,
    }


def make_cursor_moved_msg(user_id, x, y, username=None):
    return {
        'user_id': user_id,
        'x': x,
        'y': y,
        'username': username,
    }


def make_full_sync_request_msg(user_id):
    return {'user_id': user_id}


def make_full_sync_response_msg(user_id, items):
    """*items* is a list of dicts — same structure as ITEM_ADDED payloads."""
    return {
        'user_id': user_id,
        'items': items,
    }


def make_doodle_start_msg(user_id, item_id, item_type, color_hex, width, x, y, parent_id=None):
    return {
        'user_id': user_id,
        'item_id': item_id,
        'item_type': item_type,
        'color': color_hex,
        'width': width,
        'x': x,
        'y': y,
        'parent_id': parent_id,
    }


def make_doodle_point_msg(user_id, item_id, x, y):
    return {
        'user_id': user_id,
        'item_id': item_id,
        'x': x,
        'y': y,
    }


def make_doodle_end_msg(user_id, item_id):
    return {
        'user_id': user_id,
        'item_id': item_id,
    }


def make_sync_start_msg(user_id):
    return {'user_id': user_id}


def make_sync_end_msg(user_id):
    return {'user_id': user_id}

