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

import os

# --- .env LOADER ---
# This allows us to hide sensitive URLs from the public GitHub repo
_env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(_env_path):
    with open(_env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

APPNAME = '3ColRef'
APPNAME_FULL = f'{APPNAME} Reference Image Viewer'
VERSION = '1.0.0'
WEBSITE = 'https://3colref.vercel.app'
COPYRIGHT = 'Copyright © 2024-2026 Luohino'

EXTENSION = '.3col'
FILE_TYPE_NAME = f'{APPNAME} Scene'

CHANGELOG_URL = f'{WEBSITE}/changelog'

# Security: COLLAB_SERVER_URL is loaded from .env if it exists.
# For local convenience, the default is set to your Render URL.
# WARNING: DO NOT COMMIT THIS FILE IF THE URL BELOW IS PRIVATE!
COLLAB_SERVER_URL = os.environ.get('COLLAB_SERVER_URL', 'https://.com')

CHANGED_SYMBOL = '•'

COLORS = {
    # Qt:
    'Active:Base': (60, 60, 60),
    'Active:AlternateBase': (70, 70, 70),
    'Active:Window': (40, 40, 40),
    'Active:Button': (40, 40, 40),
    'Active:Text': (200, 200, 200),
    'Active:HighlightedText': (255, 255, 255),
    'Active:WindowText': (200, 200, 200),
    'Active:ButtonText': (200, 200, 200),
    'Active:Highlight': (83, 167, 165),
    'Active:Link': (90, 181, 179),

    'Disabled:Base': (40, 40, 40),
    'Disabled:Window': (40, 40, 40, 50),
    'Disabled:WindowText': (120, 120, 120),
    'Disabled:Light': (0, 0, 0, 0),
    'Disabled:Text': (140, 140, 140),

    # threecolref specific:
    'Scene:Selection': (66, 116, 159),  # Muted Slate Blue (PureRef-style)
    'Scene:Canvas': (60, 60, 60),
    'Scene:Text': (200, 200, 200),
}
