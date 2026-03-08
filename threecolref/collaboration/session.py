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

"""Session code generation.

A session code is a short, human-friendly string that encodes an
``ip:port`` pair so that a remote user can join.

Encoding scheme
---------------
1. Pack the IPv4 address (4 bytes) + port (2 bytes) = 6 bytes.
2. Encode with base32 (uppercase, no padding) → 10 chars.
3. Insert a dash every 5 chars for readability → e.g. ``ABCDE-FGHIJ``.
"""

import base64
import logging
import socket
import struct

logger = logging.getLogger(__name__)

_DASH_INTERVAL = 5


def get_local_ip():
    """Return the best-guess LAN IP address for this machine."""
    try:
        # Connect to an external address (doesn't actually send data)
        # to let the OS pick the right interface.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def generate_code(host: str, port: int) -> str:
    """Encode *host*:*port* into a short alphanumeric session code."""
    parts = [int(p) for p in host.split('.')]
    raw = struct.pack('!4BH', *parts, port)          # 6 bytes
    b32 = base64.b32encode(raw).decode('ascii').rstrip('=')  # 10 chars
    # Insert dashes for readability
    chunks = [b32[i:i + _DASH_INTERVAL]
              for i in range(0, len(b32), _DASH_INTERVAL)]
    code = '-'.join(chunks)
    logger.debug(f'Generated session code {code} for {host}:{port}')
    return code


def decode_code(code: str):
    """Decode a session code back to ``(host, port)``."""
    b32 = code.replace('-', '').replace(' ', '').upper()
    # Re-add base32 padding
    padding = (8 - len(b32) % 8) % 8
    b32 += '=' * padding
    raw = base64.b32decode(b32)
    parts = struct.unpack('!4BH', raw)
    host = '.'.join(str(p) for p in parts[:4])
    port = parts[4]
    logger.debug(f'Decoded session code to {host}:{port}')
    return host, port


def generate_cloud_code() -> str:
    """Generate a random 6-character code for cloud sessions."""
    import random
    import string
    # Avoid ambiguous characters
    chars = string.ascii_uppercase + string.digits
    chars = chars.replace('0', '').replace('O', '').replace('1', '').replace('I', '')
    room_id = ''.join(random.choices(chars, k=6))
    return f"C-{room_id}"


def is_cloud_code(code: str) -> bool:
    """Return True if the code is a cloud session code."""
    return code.startswith("C-")
