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

import logging

from PyQt6 import QtWidgets

from threecolref.config import KeyboardSettings
from threecolref.widgets.controls.keyboard import KeyboardShortcutsView
from threecolref.widgets.controls.mouse import MouseView
from threecolref.widgets.controls.mousewheel import MouseWheelView
from threecolref.widgets import ios_dialogs

logger = logging.getLogger(__name__)


class ControlsDialog(ios_dialogs._IosDialogBase):
    def __init__(self, parent):
        super().__init__(parent, 'Keyboard & Mouse Controls')
        self.setMinimumSize(700, 500)
        tabs = QtWidgets.QTabWidget(self.container)
        tabs.setStyleSheet("color: white; background-color: transparent;")

        # Keyboard shortcuts
        keyboard = QtWidgets.QWidget(self.container)
        kb_layout = QtWidgets.QVBoxLayout()
        keyboard.setLayout(kb_layout)
        table = KeyboardShortcutsView(keyboard)
        search_input = QtWidgets.QLineEdit(self.container)
        search_input.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); color: white; border-radius: 4px; padding: 4px;")
        search_input.setPlaceholderText('Search...')
        search_input.textChanged.connect(table.model().setFilterFixedString)
        kb_layout.addWidget(search_input)
        kb_layout.addWidget(table)
        tabs.addTab(keyboard, '&Keyboard Shortcuts')

        # Mouse controls
        mouse = QtWidgets.QWidget(self.container)
        mouse_layout = QtWidgets.QVBoxLayout()
        mouse.setLayout(mouse_layout)
        table = MouseView(mouse)
        search_input = QtWidgets.QLineEdit(self.container)
        search_input.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); color: white; border-radius: 4px; padding: 4px;")
        search_input.setPlaceholderText('Search...')
        search_input.textChanged.connect(table.model().setFilterFixedString)
        mouse_layout.addWidget(search_input)
        mouse_layout.addWidget(table)
        tabs.addTab(mouse, '&Mouse')

        # Mouse wheel controls
        mousewheel = QtWidgets.QWidget(self.container)
        wheel_layout = QtWidgets.QVBoxLayout()
        mousewheel.setLayout(wheel_layout)
        table = MouseWheelView(mousewheel)
        search_input = QtWidgets.QLineEdit(self.container)
        search_input.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); color: white; border-radius: 4px; padding: 4px;")
        search_input.setPlaceholderText('Search...')
        search_input.textChanged.connect(table.model().setFilterFixedString)
        wheel_layout.addWidget(search_input)
        wheel_layout.addWidget(table)
        tabs.addTab(mousewheel, 'Mouse &Wheel')

        self.content_layout.addWidget(tabs)
        self.content_layout.addSpacing(10)

        # Bottom row of buttons
        self.close_btn = self._create_button("Close")
        self.close_btn.clicked.connect(self.reject)
        
        sep = QtWidgets.QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); border: none;")
        
        self.restore_btn = self._create_button("Restore Defaults", is_destructive=True)
        self.restore_btn.clicked.connect(self.on_restore_defaults)

        self.button_layout.addWidget(self.close_btn)
        self.button_layout.addWidget(sep)
        self.button_layout.addWidget(self.restore_btn)

        self.show()

    def on_restore_defaults(self, *args, **kwargs):
        from threecolref.widgets.ios_dialogs import BeeIosMessageDialog
        reply = BeeIosMessageDialog.show_message(
            self,
            'Restore defaults?',
            'Do you want to restore all keyboard and mouse settings '
            'to their default values?')

        if reply == "OK":
            KeyboardSettings().restore_defaults()
