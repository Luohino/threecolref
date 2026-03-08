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

from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtCore import Qt

from threecolref import constants, commands
from threecolref.actions.actions import bee_actions
from threecolref.config import logfile_name
from . import controls, settings, welcome_overlay, color_gamut, ios_dialogs
from .hierarchy import HierarchyOverlay


logger = logging.getLogger(__name__)


class BeeProgressDialog(ios_dialogs.BeeIosProgressDialog):
    """Refactored to use iOS-style dialog base."""
    def __init__(self, label, worker, maximum=0, parent=None, title="Progress"):
        super().__init__(label, parent=parent, title=title)
        logger.debug('Initialised progress bar (iOS style)')
        self.setMaximum(maximum)
        
        worker.begin_processing.connect(self.on_begin_processing)
        worker.progress.connect(self.on_progress)
        worker.finished.connect(self.on_finished)
        worker.user_input_required.connect(self.on_finished)
        self.canceled.connect(worker.on_canceled)

    def on_progress(self, value):
        logger.debug(f'Progress dialog: {value}')
        self.setValue(value)

    def on_begin_processing(self, value):
        logger.debug(f'Begin progress dialog: {value}')
        self.setMaximum(value)

    def on_finished(self, *args, **kwargs):
        logger.debug('Finished progress dialog')
        self.setValue(self.maximum())
        self.reset()
        QtCore.QTimer.singleShot(100, self.deleteLater)


class HelpDialog(ios_dialogs._IosDialogBase):
    def __init__(self, parent):
        super().__init__(parent, f'{constants.APPNAME} Help')
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)

        tabs = QtWidgets.QTabWidget(self.container)
        tabs.setStyleSheet("color: white; background-color: transparent;")

        # Controls
        controls_txt = rsc_files(
            'threecolref.documentation').joinpath('controls.html').read_text()
        controls_label = QtWidgets.QLabel(controls_txt)
        controls_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        scroll = QtWidgets.QScrollArea(self.container)
        scroll.setWidgetResizable(True)
        scroll.setWidget(controls_label)
        tabs.addTab(scroll, '&Controls')

        self.content_layout.addWidget(tabs)
        self.content_layout.addSpacing(10)

        # Bottom row of buttons
        self.close_btn = self._create_button("Close", is_primary=True)
        self.close_btn.clicked.connect(self.reject)
        self.button_layout.addWidget(self.close_btn)

        self.show()


class DebugLogDialog(ios_dialogs._IosDialogBase):
    def __init__(self, parent):
        super().__init__(parent, f'{constants.APPNAME} Debug Log')
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)
        
        with open(logfile_name()) as f:
            self.log_txt = f.read()

        name_widget = QtWidgets.QLabel(logfile_name(), self.container)
        name_widget.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        name_widget.setStyleSheet("color: rgba(255,255,255,0.7); font-size: 12px;")
        self.content_layout.addWidget(name_widget)

        self.log = QtWidgets.QPlainTextEdit(self.log_txt, self.container)
        self.log.setReadOnly(True)
        self.log.setStyleSheet("background-color: rgba(0,0,0,0.3); color: white; border-radius: 6px; padding: 5px;")
        self.content_layout.addWidget(self.log)
        self.content_layout.addSpacing(10)

        self.close_btn = self._create_button("Close")
        self.close_btn.clicked.connect(self.reject)
        
        sep = QtWidgets.QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); border: none;")
        
        self.copy_btn = self._create_button("Copy To Clipboard", is_primary=True)
        self.copy_btn.clicked.connect(self.copy_to_clipboard)

        self.button_layout.addWidget(self.close_btn)
        self.button_layout.addWidget(sep)
        self.button_layout.addWidget(self.copy_btn)

        self.show()

    def copy_to_clipboard(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.log_txt)


class AboutDialog(ios_dialogs._IosDialogBase):
    def __init__(self, parent):
        super().__init__(parent, f'About {constants.APPNAME}')
        self.setMinimumWidth(380)

        main_layout = QtWidgets.QHBoxLayout()
        main_layout.setSpacing(20)
        self.content_layout.addLayout(main_layout)

        # Left Column: Logo
        from threecolref.assets import BeeAssets
        logo_label = QtWidgets.QLabel(self.container)
        logo_label.setPixmap(BeeAssets().logo.pixmap(90, 90))
        logo_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        logo_layout = QtWidgets.QVBoxLayout()
        logo_layout.addWidget(logo_label)
        logo_layout.addStretch()
        main_layout.addLayout(logo_layout)

        # Right Column: Details
        details_layout = QtWidgets.QVBoxLayout()
        details_layout.setSpacing(15)

        title = QtWidgets.QLabel(f"{constants.APPNAME} {constants.VERSION}", self.container)
        title.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        details_layout.addWidget(title)

        fullname = QtWidgets.QLabel(constants.APPNAME_FULL, self.container)
        fullname.setStyleSheet("color: rgba(255, 255, 255, 0.85); font-size: 13px;")
        details_layout.addWidget(fullname)

        copyright = QtWidgets.QLabel(constants.COPYRIGHT, self.container)
        copyright.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 12px;")
        details_layout.addWidget(copyright)

        link_label = QtWidgets.QLabel(
            f'<a href="{constants.WEBSITE}" style="color: #0A84FF; text-decoration: none;">Visit the {constants.APPNAME} website</a>',
            self.container)
        link_label.setOpenExternalLinks(True)
        link_label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        details_layout.addWidget(link_label)
        details_layout.addStretch()
        
        main_layout.addLayout(details_layout)
        self.content_layout.addSpacing(20)

        # Buttons
        self.ok_btn = self._create_button("OK", is_primary=True)
        self.ok_btn.clicked.connect(self.accept)
        self.button_layout.addWidget(self.ok_btn)

        self.show()


class SceneToPixmapExporterDialog(ios_dialogs._IosDialogBase):
    MIN_SIZE = 10
    MAX_SIZE = 100000

    def __init__(self, parent, default_size):
        super().__init__(parent, 'Export Scene to Image')
        self.default_size = default_size
        if (self.default_size.width() > self.MAX_SIZE
                or self.default_size.width() >= self.MAX_SIZE):
            self.default_size.scale(
                self.MAX_SIZE, self.MAX_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio)

        self.ignore_change = False
        
        layout = QtWidgets.QGridLayout()
        self.content_layout.addLayout(layout)

        width_label = QtWidgets.QLabel('Width:', self.container)
        width_label.setStyleSheet("color: white;")
        layout.addWidget(width_label, 0, 0)
        self.width_input = QtWidgets.QSpinBox(self.container)
        self.width_input.setStyleSheet("background-color: rgba(255,255,255,0.1); color: white; border-radius: 4px; padding: 4px;")
        self.width_input.setRange(self.MIN_SIZE, self.MAX_SIZE)
        self.width_input.setValue(default_size.width())
        self.width_input.valueChanged.connect(self.on_width_changed)
        layout.addWidget(self.width_input, 0, 1)

        height_label = QtWidgets.QLabel('Height:', self.container)
        height_label.setStyleSheet("color: white;")
        layout.addWidget(height_label, 1, 0)
        self.height_input = QtWidgets.QSpinBox(self.container)
        self.height_input.setStyleSheet("background-color: rgba(255,255,255,0.1); color: white; border-radius: 4px; padding: 4px;")
        self.height_input.setMinimum(10)
        self.height_input.setRange(self.MIN_SIZE, self.MAX_SIZE)
        self.height_input.setValue(default_size.height())
        self.height_input.valueChanged.connect(self.on_height_changed)
        layout.addWidget(self.height_input, 1, 1)

        self.content_layout.addSpacing(15)

        # Bottom row of buttons
        self.cancel_btn = self._create_button("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        
        sep = QtWidgets.QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); border: none;")
        
        self.ok_btn = self._create_button("OK", is_primary=True)
        self.ok_btn.clicked.connect(self.accept)

        self.button_layout.addWidget(self.cancel_btn)
        self.button_layout.addWidget(sep)
        self.button_layout.addWidget(self.ok_btn)

    def on_width_changed(self, width):
        if not self.ignore_change:
            self.ignore_change = True
            new = self.default_size.scaled(
                width, self.MAX_SIZE, Qt.AspectRatioMode.KeepAspectRatio)
            self.height_input.setValue(new.height())
            self.ignore_change = False

    def on_height_changed(self, height):
        if not self.ignore_change:
            self.ignore_change = True
            new = self.default_size.scaled(
                self.MAX_SIZE, height, Qt.AspectRatioMode.KeepAspectRatio)
            self.width_input.setValue(new.width())
            self.ignore_change = False

    def value(self):
        return QtCore.QSize(self.width_input.value(),
                            self.height_input.value())


class ChangeOpacityDialog(ios_dialogs._IosDialogBase):

    def __init__(self, parent, images, undo_stack):
        super().__init__(parent, 'Change Opacity:')
        self.undo_stack = undo_stack
        self.images = images
        self.command = commands.ChangeOpacity(images, opacity=1)

        value = int(images[0].opacity() * 100) if images else 100

        self.label = QtWidgets.QLabel('Opacity:', self.container)
        self.label.setStyleSheet("color: white;")
        self.content_layout.addWidget(self.label)

        self.input = QtWidgets.QSlider(Qt.Orientation.Horizontal, self.container)
        self.input.valueChanged.connect(self.on_value_changed)
        self.input.setRange(0, 100)
        self.input.setValue(value)
        self.content_layout.addWidget(self.input)
        self.content_layout.addSpacing(15)

        # Bottom row of buttons
        self.cancel_btn = self._create_button("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        
        sep = QtWidgets.QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); border: none;")
        
        self.ok_btn = self._create_button("OK", is_primary=True)
        self.ok_btn.clicked.connect(self.accept)

        self.button_layout.addWidget(self.cancel_btn)
        self.button_layout.addWidget(sep)
        self.button_layout.addWidget(self.ok_btn)

        self.show()

    def on_value_changed(self, value):
        self.label.setText(f'Opacity: {value}%')
        self.command.opacity = value / 100
        self.command.redo()

    def accept(self):
        if self.images:
            logger.debug(f'Setting opacity to {self.command.opacity}')
            self.command.ignore_first_redo = True
            self.undo_stack.push(self.command)
        return super().accept()

    def reject(self):
        self.command.undo()
        return super().reject()


class BeeNotification(QtWidgets.QWidget):
    def __init__(self, parent, text):
        super().__init__(parent)
        self.label = QtWidgets.QLabel(text)
        self.setObjectName('BeeNotification')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAutoFillBackground(True)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)
        color = constants.COLORS['Active:Window']
        self.setStyleSheet(
            f'background-color: rgba({color[0]}, {color[1]}, {color[2]}, 0.9);'
            'padding: 0.7em;'
            'border-radius: 5px;')
        # Position notification in a safer way if parent is too small
        if parent.width() < 100:
            self.move(10, 10)
        else:
            x = (parent.width() - self.width()) / 2
            self.move(int(x), 10)
        self.show()
        self.raise_()  # Ensure it's on top of other widgets in the same window

        QtCore.QTimer.singleShot(1000 * 3, self.deleteLater)


class BeeWindowButton(QtWidgets.QPushButton):
    """iOS/macOS traffic-light style window control button."""

    # Circle colors for each button type
    COLORS = {
        'close':  (QtGui.QColor(255, 95, 87),  QtGui.QColor(220, 60, 54)),   # red
        'min':    (QtGui.QColor(255, 189, 46), QtGui.QColor(222, 160, 30)),   # yellow
        'max':    (QtGui.QColor(39, 201, 63),  QtGui.QColor(28, 175, 48)),    # green
        'pin':    (QtGui.QColor(80, 160, 255), QtGui.QColor(50, 130, 230)),   # blue
    }

    def __init__(self, parent, btn_type, callback=None):
        super().__init__(parent)
        self.btn_type = btn_type
        self.setFixedSize(20, 20)
        self.setFlat(True)
        self.setCheckable(btn_type == 'pin')
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.is_checked = False
        self._hovered = False
        if callback:
            self.clicked.connect(callback)

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)

    def enterEvent(self, event):
        self._hovered = True
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        super().leaveEvent(event)
        self.update()

    def mouseReleaseEvent(self, event):
        event.accept()
        super().mouseReleaseEvent(event)

    def setChecked(self, checked):
        self.is_checked = checked
        super().setChecked(checked)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        radius = 6.0

        normal_color, hover_color = self.COLORS.get(
            self.btn_type, (QtGui.QColor(120, 120, 120), QtGui.QColor(100, 100, 100)))

        # For pin button: brighter when checked
        if self.btn_type == 'pin' and self.is_checked:
            fill = QtGui.QColor(60, 180, 255)
        elif self._hovered:
            fill = hover_color
        else:
            fill = normal_color

        # Draw circle
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(QtCore.QPointF(cx, cy), radius, radius)

        # Draw glyph on hover
        if self._hovered or (self.btn_type == 'pin' and self.is_checked):
            glyph_color = QtGui.QColor(70, 0, 0) if self.btn_type == 'close' else QtGui.QColor(50, 50, 50)
            if self.btn_type == 'pin' and self.is_checked:
                glyph_color = QtGui.QColor(255, 255, 255)
            pen = QtGui.QPen(glyph_color)
            pen.setWidthF(1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)

            if self.btn_type == 'close':
                s = 3.0
                painter.drawLine(QtCore.QPointF(cx - s, cy - s), QtCore.QPointF(cx + s, cy + s))
                painter.drawLine(QtCore.QPointF(cx + s, cy - s), QtCore.QPointF(cx - s, cy + s))
            elif self.btn_type == 'min':
                s = 3.5
                painter.drawLine(QtCore.QPointF(cx - s, cy), QtCore.QPointF(cx + s, cy))
            elif self.btn_type == 'max':
                mw = getattr(self, '_main_window', None)
                is_maximized = mw.isMaximized() if mw else False
                if is_maximized:
                    # Two small overlapping rects (restore icon)
                    s = 2.5
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(QtCore.QRectF(cx - s, cy - s + 1, s * 2 - 1, s * 2 - 1))
                    painter.drawRect(QtCore.QRectF(cx - s + 1.5, cy - s - 0.5, s * 2 - 1, s * 2 - 1))
                else:
                    # Triangle/arrow pointing top-left + bottom-right (fullscreen)
                    s = 3.0
                    # Draw two opposing arrows
                    painter.drawLine(QtCore.QPointF(cx - s, cy - s), QtCore.QPointF(cx + s, cy + s))
                    # arrowhead top-left
                    painter.drawLine(QtCore.QPointF(cx - s, cy - s), QtCore.QPointF(cx - s + 2.5, cy - s))
                    painter.drawLine(QtCore.QPointF(cx - s, cy - s), QtCore.QPointF(cx - s, cy - s + 2.5))
                    # arrowhead bottom-right
                    painter.drawLine(QtCore.QPointF(cx + s, cy + s), QtCore.QPointF(cx + s - 2.5, cy + s))
                    painter.drawLine(QtCore.QPointF(cx + s, cy + s), QtCore.QPointF(cx + s, cy + s - 2.5))
            elif self.btn_type == 'pin':
                # Small pin glyph
                painter.save()
                painter.translate(cx, cy)
                painter.scale(0.28, 0.28)
                painter.translate(-12, -15.5)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QtGui.QBrush(glyph_color))
                path = QtGui.QPainterPath()
                path.setFillRule(Qt.FillRule.WindingFill)
                path.moveTo(6.5, 5)
                path.cubicTo(6.5, 4.45, 6.95, 4, 7.5, 4)
                path.lineTo(16.5, 4)
                path.cubicTo(17.05, 4, 17.5, 4.45, 17.5, 5)
                path.cubicTo(17.5, 5.55, 17.05, 6, 16.5, 6)
                path.lineTo(16.095, 6)
                path.lineTo(16.913, 15)
                path.lineTo(19, 15)
                path.cubicTo(19.55, 15, 20, 15.45, 20, 16)
                path.cubicTo(20, 16.55, 19.55, 17, 19, 17)
                path.lineTo(13, 17)
                path.lineTo(13, 22)
                path.cubicTo(13, 22.55, 12.55, 23, 12, 23)
                path.cubicTo(11.45, 23, 11, 22.55, 11, 22)
                path.lineTo(11, 17)
                path.lineTo(5, 17)
                path.cubicTo(4.45, 17, 4, 16.55, 4, 16)
                path.cubicTo(4, 15.45, 4.45, 15, 5, 15)
                path.lineTo(7.087, 15)
                path.lineTo(7.905, 6)
                path.lineTo(7.5, 6)
                path.cubicTo(6.95, 6, 6.5, 5.55, 6.5, 5)
                path.closeSubpath()
                painter.drawPath(path)
                painter.restore()





class BeeTitleBar(QtWidgets.QWidget):
    """iOS-style title bar — always visible, clean frosted-glass look."""

    TITLE_HEIGHT = 38

    def __init__(self, parent, view):
        super().__init__(parent)
        self.view = view
        self.main_window = parent.window()

        self.setObjectName("beeTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self.TITLE_HEIGHT)
        self.setMouseTracking(True)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(0)

        # LEFT — traffic-light controls
        self.controls = BeeWindowControls(self, view)
        layout.addWidget(self.controls)

        # CENTER — title (stretch on both sides to keep it centered)
        layout.addStretch(1)

        self.title_label = QtWidgets.QLabel(constants.APPNAME)
        self.title_label.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: rgba(255,255,255,0.85); background: transparent;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setCursor(Qt.CursorShape.ArrowCursor)
        layout.addWidget(self.title_label)

        layout.addStretch(1)

        # RIGHT — app icon (small branding)
        self.icon_label = QtWidgets.QLabel()
        from threecolref.assets import BeeAssets
        self.icon_label.setPixmap(BeeAssets().logo.pixmap(16, 16))
        self.icon_label.setCursor(Qt.CursorShape.ArrowCursor)
        self.icon_label.setStyleSheet("background: transparent;")
        layout.addWidget(self.icon_label)

        # Apply iOS-style background
        self._apply_style()

        self._dragging_window = False
        self._drag_start_pos = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _apply_style(self):
        self.setStyleSheet("""
            QWidget#beeTitleBar {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(44, 44, 48, 245),
                    stop:1 rgba(34, 34, 38, 245));
                border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            }
            QLabel {
                color: rgba(255, 255, 255, 0.85);
                background: transparent;
            }
        """)

    def _update_overlay_geometry(self):
        """Keep overlay at top, full width."""
        p = self.parent()
        if p and hasattr(p, 'width'):
            self.setGeometry(0, 0, p.width(), self.TITLE_HEIGHT)

    # --- No hover expand/collapse — always visible ---
    def enterEvent(self, event):
        super().enterEvent(event)

    def leaveEvent(self, event):
        super().leaveEvent(event)

    # --- Window dragging ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Don't drag if clicking on controls
            if self.controls.geometry().contains(event.pos()):
                super().mousePressEvent(event)
                return
            # Start window drag using native system move for reliable behavior
            wh = self.main_window.windowHandle()
            if wh is not None:
                wh.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Just keep arrow cursor in title bar area (no resize from title bar)
        if self.controls.geometry().contains(event.pos()):
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.controls.geometry().contains(event.pos()):
                self.controls.toggle_maximized()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging_window = False
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)


class BeeWindowControls(QtWidgets.QWidget):
    """iOS traffic-light container — Close, Min, Max, Pin (left-aligned)."""
    def __init__(self, parent, view):
        super().__init__(parent)
        self.view = view
        self.main_window = parent.window()

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # macOS order: close, minimize, maximize — then pin
        self.close_btn = BeeWindowButton(self, 'close', self.main_window.close)
        self.close_btn.setToolTip('Close')
        self.min_btn = BeeWindowButton(self, 'min', self.toggle_minimize)
        self.min_btn.setToolTip('Minimize')
        self.max_btn = BeeWindowButton(self, 'max', self.toggle_maximized)
        self.max_btn.setToolTip('Maximize / Restore')
        self.pin_btn = BeeWindowButton(self, 'pin')
        self.pin_btn.setToolTip('Always On Top (Ctrl+Shift+A)')

        layout.addWidget(self.close_btn)
        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.pin_btn)

        self.pin_btn.clicked.connect(self.on_pin_clicked)
        self.main_window.windowStateChanged.connect(self._on_window_state_changed)
        self.max_btn._main_window = self.main_window

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.show()

    def mousePressEvent(self, event):
        event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        event.accept()
        super().mouseReleaseEvent(event)

    def toggle_maximized(self):
        mw = self.main_window
        if mw.isMaximized():
            def _restore_centered():
                mw.setWindowState(Qt.WindowState.WindowNoState)
                screen = mw.screen().availableGeometry()
                w = min(int(screen.width() * 0.5), 900)
                h = min(int(screen.height() * 0.5), 600)
                x = screen.x() + (screen.width() - w) // 2
                y = screen.y() + (screen.height() - h) // 2
                mw.setGeometry(x, y, w, h)
            QtCore.QTimer.singleShot(0, _restore_centered)
        else:
            mw.showMaximized()

    def toggle_minimize(self):
        self.main_window.showMinimized()

    def _on_window_state_changed(self):
        self.max_btn.update()

    def on_pin_clicked(self):
        from threecolref.actions.actions import bee_actions
        action = bee_actions['always_on_top'].qaction
        action.trigger()

    def update_states(self):
        from threecolref.actions.actions import bee_actions
        checked = bee_actions['always_on_top'].qaction.isChecked()
        self.pin_btn.setChecked(checked)


class SampleColorWidget(QtWidgets.QWidget):

    OFFSET = 10  # Offset from mouse pointer
    SIZE = 50
    NONE_COLOR = QtGui.QColor(0, 0, 0, 0)

    def __init__(self, parent, pos, color):
        super().__init__(parent)
        self.color = color
        self.set_pos(pos)
        self.show()

    def set_pos(self, pos):
        self.setGeometry(int(pos.x() + self.OFFSET),
                         int(pos.y() + self.OFFSET),
                         self.SIZE, self.SIZE)

    def paintEvent(self, event):
        color = self.color if self.color else self.NONE_COLOR
        painter = QtGui.QPainter(self)
        painter.setBrush(QtGui.QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(0, 0, self.SIZE, self.SIZE)

    def update(self, pos, color):
        self.set_pos(pos)
        self.color = color
        self.repaint()


class ExportImagesFileExistsDialog(ios_dialogs._IosDialogBase):

    def __init__(self, parent, filename):
        super().__init__(parent, 'File exists')

        label = QtWidgets.QLabel(
            f'File already exists:\n{filename}', self.container)
        label.setStyleSheet("color: white;")
        self.content_layout.addWidget(label)
        self.content_layout.addSpacing(10)

        choices = (('skip', 'Skip this file'),
                   ('skip_all', 'Skip all existing files'),
                   ('overwrite', 'Overwrite this file'),
                   ('overwrite_all', 'Overwrite all existing files'))

        self.radio_buttons = {}
        for (value, text) in choices:
            btn = QtWidgets.QRadioButton(text, self.container)
            btn.setStyleSheet("color: white;")
            self.radio_buttons[value] = btn
            self.content_layout.addWidget(btn)
        self.radio_buttons['skip'].setChecked(True)
        self.content_layout.addSpacing(15)

        # Bottom row of buttons
        self.cancel_btn = self._create_button("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        
        sep = QtWidgets.QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); border: none;")
        
        self.ok_btn = self._create_button("OK", is_primary=True)
        self.ok_btn.clicked.connect(self.accept)

        self.button_layout.addWidget(self.cancel_btn)
        self.button_layout.addWidget(sep)
        self.button_layout.addWidget(self.ok_btn)


class UnsavedChangesDialog(ios_dialogs._IosDialogBase):
    """Custom dialog for unsaved changes with 'Remember my choice' option."""
    def __init__(self, parent):
        super().__init__(parent, "Discard unsaved changes?")
        self.setMinimumWidth(400)

        # Message
        self.label = QtWidgets.QLabel("You have unsaved changes. Would you like to save them before exiting?", self.container)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-size: 13px; color: rgba(255, 255, 255, 0.8);")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addWidget(self.label)
        self.content_layout.addSpacing(10)

        # Checkbox for "Remember my choice"
        self.remember_checkbox = QtWidgets.QCheckBox("Remember my choice", self.container)
        self.remember_checkbox.setToolTip("If checked, this choice will be applied automatically in the future.")
        self.remember_checkbox.setStyleSheet("color: white;")
        
        chk_layout = QtWidgets.QHBoxLayout()
        chk_layout.addStretch()
        chk_layout.addWidget(self.remember_checkbox)
        chk_layout.addStretch()
        self.content_layout.addLayout(chk_layout)
        self.content_layout.addSpacing(10)

        # Buttons
        self.cancel_btn = self._create_button("Cancel")
        self.cancel_btn.clicked.connect(lambda: self.done(QtWidgets.QMessageBox.StandardButton.Cancel.value))
        
        sep1 = QtWidgets.QFrame()
        sep1.setFixedWidth(1)
        sep1.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); border: none;")
        
        self.discard_btn = self._create_button("Discard", is_destructive=True)
        self.discard_btn.clicked.connect(lambda: self.done(QtWidgets.QMessageBox.StandardButton.Discard.value))
        
        sep2 = QtWidgets.QFrame()
        sep2.setFixedWidth(1)
        sep2.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); border: none;")

        self.save_btn = self._create_button("Save", is_primary=True)
        self.save_btn.clicked.connect(lambda: self.done(QtWidgets.QMessageBox.StandardButton.Save.value))

        self.button_layout.addWidget(self.cancel_btn)
        self.button_layout.addWidget(sep1)
        self.button_layout.addWidget(self.discard_btn)
        self.button_layout.addWidget(sep2)
        self.button_layout.addWidget(self.save_btn)

    def get_result(self):
        """Returns (choice_string, remember_boolean)"""
        res = self.result()
        remember = self.remember_checkbox.isChecked()
        
        if res == QtWidgets.QMessageBox.StandardButton.Save.value:
            return 'save', remember
        elif res == QtWidgets.QMessageBox.StandardButton.Discard.value:
            return 'discard', remember
        else:
            return 'cancel', False
