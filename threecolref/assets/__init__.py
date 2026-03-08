#!/usr/bin/env python3

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

from importlib.resources import files as rsc_files
import logging

from PyQt6 import QtGui, QtWidgets
from PyQt6.QtSvg import QSvgRenderer


logger = logging.getLogger(__name__)


class BeeAssets:
    _instance = None
    PATH = rsc_files('threecolref.assets')

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
            cls._instance.on_new()
        return cls._instance

    def on_new(self):
        logger.debug(f'Assets path: {self.PATH}')

        import os, sys
        # Use ICO on Windows for crispest window icon, fallback to PNG
        ico_path = str(self.PATH.joinpath('logo.ico'))
        png_path = str(self.PATH.joinpath('logo.png'))
        if os.path.exists(ico_path) and sys.platform.startswith('win'):
            self.logo = QtGui.QIcon(ico_path)
        else:
            self.logo = QtGui.QIcon(png_path)
        assert self.logo.isNull() is False
        # High-res pixmap for UI elements (loaded from the original PNG at native size)
        self.logo_pixmap = QtGui.QPixmap(png_path)
        
        # Load the modern rotation handle icon
        self.icon_rotate_svg = QSvgRenderer(str(self.PATH.joinpath('icon_rotate.svg')))
        
        # Settings icons
        self.icon_perf = str(self.PATH.joinpath('icon_perf.svg'))
        self.icon_appearance = str(self.PATH.joinpath('icon_appearance.svg'))
        self.icon_save = str(self.PATH.joinpath('icon_save.svg'))
        self.icon_window = str(self.PATH.joinpath('icon_window.svg'))
        self.icon_image = str(self.PATH.joinpath('icon_image.svg'))
        self.icon_keyboard = str(self.PATH.joinpath('icon_keyboard.svg'))
        self.icon_restore = str(self.PATH.joinpath('icon_restore.svg'))
        self.icon_gear = str(self.PATH.joinpath('icon_gear.svg'))

        # Doodle Toolbar icons (iOS/Lucide style)
        self.icon_pencil = str(self.PATH.joinpath('icon_pencil.svg'))
        self.icon_eraser = str(self.PATH.joinpath('icon_eraser.svg'))
        self.icon_undo = str(self.PATH.joinpath('icon_undo.svg'))
        self.icon_redo = str(self.PATH.joinpath('icon_redo.svg'))
        self.icon_trash = str(self.PATH.joinpath('icon_trash.svg'))
        self.icon_close = str(self.PATH.joinpath('icon_close.svg'))
        self.icon_grip = str(self.PATH.joinpath('icon_grip.svg'))
        self.icon_rect = str(self.PATH.joinpath('icon_rect.svg'))
        self.icon_circle = str(self.PATH.joinpath('icon_circle.svg'))
        self.icon_line = str(self.PATH.joinpath('icon_line.svg'))
        self.icon_arrow = str(self.PATH.joinpath('icon_arrow.svg'))
        self.icon_select = str(self.PATH.joinpath('icon_select.svg'))

    def cursor_from_image(self, filename, hotspot):
        app = QtWidgets.QApplication.instance()
        scaling = app.primaryScreen().devicePixelRatio()
        img = QtGui.QImage(str(self.PATH.joinpath(filename)))
        assert img.isNull() is False
        pixmap = QtGui.QPixmap.fromImage(img)
        pixmap.setDevicePixelRatio(scaling)
        return QtGui.QCursor(
            pixmap, int(hotspot[0]/scaling), int(hotspot[1]/scaling))
