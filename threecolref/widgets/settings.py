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

from functools import partial
import logging

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import Qt

from threecolref import constants
from threecolref.config import BeeSettings, settings_events
from threecolref.assets import BeeAssets


logger = logging.getLogger(__name__)


class GroupBase(QtWidgets.QGroupBox):
    TITLE = None
    HELPTEXT = None
    KEY = None

    def __init__(self):
        super().__init__()
        self.settings = BeeSettings()
        self.update_title()
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        settings_events.restore_defaults.connect(self.on_restore_defaults)

        if self.HELPTEXT:
            helptxt = QtWidgets.QLabel(self.HELPTEXT)
            helptxt.setWordWrap(True)
            helptxt.setStyleSheet("color: rgba(255, 255, 255, 120); font-size: 11px; margin-bottom: 8px;")
            self.layout.addWidget(helptxt)

        self.setStyleSheet("""
            QGroupBox {
                border: none;
                margin-top: 32px;
                background: transparent;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 0 12px 0;
                font-size: 15px;
                font-weight: 700;
                color: #ffffff;
            }
            QLabel {
                background: transparent;
                border: none;
                color: rgba(255, 255, 255, 180);
                font-size: 11px;
            }
        """)

    def update_title(self):
        title = [self.TITLE]
        if self.settings.value_changed(self.KEY):
            title.append(constants.CHANGED_SYMBOL)
        self.setTitle(' '.join(title))

    def on_value_changed(self, value):
        if self.ignore_value_changed:
            return

        value = self.convert_value_from_qt(value)
        if value != self.settings.valueOrDefault(self.KEY):
            logger.debug(f'Setting {self.KEY} changed to: {value}')
            self.settings.setValue(self.KEY, value)
            self.update_title()

    def convert_value_from_qt(self, value):
        return value

    def on_restore_defaults(self):
        new_value = self.settings.valueOrDefault(self.KEY)
        self.ignore_value_changed = True
        self.set_value(new_value)
        self.ignore_value_changed = False
        self.update_title()


class RadioGroup(GroupBase):
    OPTIONS = None

    def __init__(self):
        super().__init__()

        self.ignore_value_changed = True
        self.buttons = {}
        for (value, label, helptext) in self.OPTIONS:
            btn = QtWidgets.QRadioButton(label)
            self.buttons[value] = btn
            btn.setToolTip(helptext)
            btn.toggled.connect(partial(self.on_value_changed, value=value))
            if value == self.settings.valueOrDefault(self.KEY):
                btn.setChecked(True)
            self.layout.addWidget(btn)

        self.ignore_value_changed = False
        self.layout.addStretch(100)

    def set_value(self, value):
        for old_value, btn in self.buttons.items():
            btn.setChecked(old_value == value)


class IntegerGroup(GroupBase):
    MIN = None
    MAX = None

    def __init__(self):
        super().__init__()
        self.input = QtWidgets.QSpinBox()
        self.input.setRange(self.MIN, self.MAX)
        self.set_value(self.settings.valueOrDefault(self.KEY))
        self.input.valueChanged.connect(self.on_value_changed)
        self.layout.addWidget(self.input)
        self.layout.addStretch(100)
        self.ignore_value_changed = False

    def set_value(self, value):
        self.input.setValue(value)


class SingleCheckboxGroup(GroupBase):
    LABEL = None

    def __init__(self):
        super().__init__()
        self.input = QtWidgets.QCheckBox(self.LABEL)
        self.set_value(self.settings.valueOrDefault(self.KEY))
        self.input.checkStateChanged.connect(self.on_value_changed)
        self.layout.addWidget(self.input)
        self.layout.addStretch(100)
        self.ignore_value_changed = False

    def set_value(self, value):
        self.input.setChecked(value)

    def convert_value_from_qt(self, value):
        return value == Qt.CheckState.Checked


class ArrangeDefaultWidget(RadioGroup):
    TITLE = 'Default Arrange Method:'
    HELPTEXT = ('How images are arranged when inserted in batch')
    KEY = 'Items/arrange_default'
    OPTIONS = (
        ('optimal', 'Optimal', 'Arrange Optimal'),
        ('horizontal', 'Horizontal (by filename)',
         'Arrange Horizontal (by filename)'),
        ('vertical', 'Vertical (by filename)',
         'Arrange Vertical (by filename)'),
        ('square', 'Square (by filename)', 'Arrannge Square (by filename)'))


class ImageStorageFormatWidget(RadioGroup):
    TITLE = 'Image Storage Format:'
    HELPTEXT = ('How images are stored inside bee files.'
                ' Changes will only take effect on newly saved images.')
    KEY = 'Items/image_storage_format'
    OPTIONS = (
        ('best', 'Best Guess',
         ('Small images and images with alpha channel are stored as png,'
          ' everything else as jpg')),
        ('png', 'Always PNG', 'Lossless, but large bee file'),
        ('jpg', 'Always JPG',
         'Small bee file, but lossy and no transparency support'))


class ArrangeGapWidget(IntegerGroup):
    TITLE = 'Arrange Gap:'
    HELPTEXT = ('The gap between images when using arrange actions.')
    KEY = 'Items/arrange_gap'
    MIN = 0
    MAX = 200


class AllocationLimitWidget(IntegerGroup):
    TITLE = 'Maximum Image Size:'
    HELPTEXT = ('The maximum image size that can be loaded (in megabytes). '
                'Set to 0 for no limitation.')
    KEY = 'Items/image_allocation_limit'
    MIN = 0
    MAX = 10000


class ConfirmCloseUnsavedWidget(SingleCheckboxGroup):
    TITLE = 'Confirm when closing an unsaved file:'
    HELPTEXT = (
        'When about to close an unsaved file, should threecolref ask for '
        'confirmation?')
    LABEL = 'Confirm when closing'
    KEY = 'Save/confirm_close_unsaved'


class SettingsCategory:
    """Represents a settings category with icon and widgets."""
    def __init__(self, name, icon_path, widgets):
        self.name = name
        self.icon_path = icon_path
        self.widgets = widgets


class SettingsListButton(QtWidgets.QPushButton):
    """Custom button for settings category in sidebar."""
    def __init__(self, category):
        super().__init__()
        self.category = category
        self.setCheckable(True)
        self.setFlat(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        
        # Create layout for icon and text
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        
        # Icon label with SVG
        icon_label = QtWidgets.QLabel()
        icon_pix = QtGui.QIcon(category.icon_path).pixmap(18, 18)
        icon_label.setPixmap(icon_pix)
        icon_label.setStyleSheet('background: transparent; min-width: 24px;')
        layout.addWidget(icon_label)
        
        # Text label
        text_label = QtWidgets.QLabel(category.name)
        text_label.setStyleSheet('background: transparent; border: none; font-size: 11px; font-weight: 500;')
        layout.addWidget(text_label)
        layout.addStretch()
        
        self.setLayout(layout)
        self.setMinimumHeight(44)
        
        # Apply styling
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 8px;
                padding: 0px;
                margin: 0px 8px;
                color: rgba(255, 255, 255, 120);
                text-align: left;
                outline: none;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 15);
                color: rgba(255, 255, 255, 220);
            }
            QPushButton:checked {
                background-color: rgba(255, 255, 255, 25);
                color: #ffffff;
            }
            QPushButton:focus {
                outline: none;
                border: none;
            }
        """)


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.setMinimumSize(800, 600)
        self.selected_category = None
        self.category_buttons = {}
        
        # Main layout: horizontal split
        main_layout = QtWidgets.QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.setLayout(main_layout)
        
        # --- LEFT SIDEBAR ---
        sidebar = QtWidgets.QWidget()
        sidebar.setStyleSheet('background-color: #222; border: none;')
        sidebar.setMinimumWidth(260)
        sidebar.setMaximumWidth(260)
        sidebar_layout = QtWidgets.QVBoxLayout()
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(4)
        sidebar.setLayout(sidebar_layout)
        
        # Search box
        search_box = QtWidgets.QLineEdit()
        search_box.setPlaceholderText('Search...')
        search_box.setStyleSheet("""
            QLineEdit {
                background-color: #333;
                border: 1px solid #444;
                border-radius: 18px;
                padding: 0px 16px;
                color: #ffffff;
                font-size: 13px;
                margin: 16px 16px 12px 16px;
                selection-background-color: #444;
            }
            QLineEdit:focus {
                border: 1px solid #666;
                background-color: #3a3a3a;
            }
        """)
        search_box.setFixedHeight(36)
        sidebar_layout.addWidget(search_box)
        
        # Define categories
        assets = BeeAssets()
        categories = [
            SettingsCategory('Performance', assets.icon_perf, []),
            SettingsCategory('Appearance', assets.icon_appearance, []),
            SettingsCategory('Saving and loading', assets.icon_save, []),
            SettingsCategory('Window', assets.icon_window, []),
            SettingsCategory('Images', assets.icon_image, []),
            SettingsCategory('Keyboard shortcuts', assets.icon_keyboard, []),
        ]
        
        # Create category buttons
        for i, category in enumerate(categories):
            btn = SettingsListButton(category)
            btn.clicked.connect(lambda checked, cat=category, idx=i: 
                               self.on_category_selected(cat, idx))
            self.category_buttons[i] = btn
            sidebar_layout.addWidget(btn)
        
        sidebar_layout.addStretch()
        
        # Bottom buttons in sidebar
        bottom_buttons = QtWidgets.QWidget()
        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.setContentsMargins(8, 8, 8, 8)
        bottom_layout.setSpacing(8)
        
        # Restore defaults button
        restore_btn = QtWidgets.QPushButton()
        restore_btn.setIcon(QtGui.QIcon(assets.icon_restore))
        restore_btn.setIconSize(QtCore.QSize(18, 18))
        restore_btn.setToolTip('Restore defaults')
        restore_btn.setFlat(True)
        restore_btn.setFixedSize(32, 32)
        restore_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        restore_btn.setStyleSheet("""
            QPushButton { 
                background: transparent; 
                border: none; 
                border-radius: 6px;
                outline: none;
            }
            QPushButton:hover { background: rgba(255, 255, 255, 20); }
        """)
        restore_btn.clicked.connect(self.on_restore_defaults)
        bottom_layout.addWidget(restore_btn)
        
        # Settings icon
        settings_icon = QtWidgets.QPushButton()
        settings_icon.setIcon(QtGui.QIcon(assets.icon_gear))
        settings_icon.setIconSize(QtCore.QSize(18, 18))
        settings_icon.setFlat(True)
        settings_icon.setFixedSize(32, 32)
        settings_icon.setEnabled(False)
        settings_icon.setStyleSheet("""
            QPushButton { 
                background: transparent; 
                border: none; 
                outline: none;
            }
        """)
        bottom_layout.addWidget(settings_icon)
        
        bottom_layout.addStretch()
        bottom_buttons.setLayout(bottom_layout)
        sidebar_layout.addWidget(bottom_buttons)
        
        main_layout.addWidget(sidebar)
        
        # --- RIGHT CONTENT AREA ---
        content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout()
        content_layout.setContentsMargins(24, 24, 24, 24)
        content_layout.setSpacing(16)
        content_widget.setLayout(content_layout)
        
        # Stacked widget for different category views
        self.stacked_widget = QtWidgets.QStackedWidget()
        
        # Performance page
        perf_page = QtWidgets.QWidget()
        perf_layout = QtWidgets.QVBoxLayout(perf_page)
        perf_layout.addWidget(QtWidgets.QLabel('Performance settings would go here'))
        perf_layout.addStretch()
        self.stacked_widget.addWidget(perf_page)
        
        # Appearance page
        app_page = QtWidgets.QWidget()
        app_layout = QtWidgets.QVBoxLayout(app_page)
        app_layout.addWidget(QtWidgets.QLabel('Appearance settings would go here'))
        app_layout.addStretch()
        self.stacked_widget.addWidget(app_page)
        
        # Saving and loading page
        save_page = QtWidgets.QWidget()
        save_layout = QtWidgets.QVBoxLayout(save_page)
        save_layout.addWidget(ConfirmCloseUnsavedWidget())
        save_layout.addStretch()
        self.stacked_widget.addWidget(save_page)
        
        # Window page
        win_page = QtWidgets.QWidget()
        win_layout = QtWidgets.QVBoxLayout(win_page)
        win_layout.addWidget(QtWidgets.QLabel('Window settings would go here'))
        win_layout.addStretch()
        self.stacked_widget.addWidget(win_page)
        
        # Images page
        img_page = QtWidgets.QWidget()
        img_layout = QtWidgets.QVBoxLayout(img_page)
        img_layout.addWidget(ImageStorageFormatWidget())
        img_layout.addWidget(AllocationLimitWidget())
        img_layout.addWidget(ArrangeGapWidget())
        img_layout.addWidget(ArrangeDefaultWidget())
        img_layout.addStretch()
        self.stacked_widget.addWidget(img_page)
        
        # Keyboard shortcuts page
        kbd_page = QtWidgets.QWidget()
        kbd_layout = QtWidgets.QVBoxLayout(kbd_page)
        kbd_layout.addWidget(QtWidgets.QLabel('Keyboard shortcuts would go here'))
        kbd_layout.addStretch()
        self.stacked_widget.addWidget(kbd_page)
        
        content_layout.addWidget(self.stacked_widget)
        main_layout.addWidget(content_widget, 1)
        
        # Select first category by default
        self.category_buttons[0].click()
        self.show()
    
    def create_icon(self, char, size):
        """Create a simple icon from a character."""
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setFont(QtGui.QFont('Arial', size - 4))
        painter.setPen(QtGui.QColor('#999'))
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, char)
        painter.end()
        return QtGui.QIcon(pixmap)
    
    def on_category_selected(self, category, index):
        """Handle category selection."""
        # Update button states
        for btn in self.category_buttons.values():
            btn.setChecked(False)
        self.category_buttons[index].setChecked(True)
        
        # Show corresponding page
        self.stacked_widget.setCurrentIndex(index)
        self.selected_category = category

    def on_restore_defaults(self, *args, **kwargs):
        reply = QtWidgets.QMessageBox.question(
            self,
            'Restore defaults?',
            'Do you want to restore all settings to their default values?')

        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            BeeSettings().restore_defaults()
