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
from . import controls, settings, welcome_overlay, color_gamut
from .hierarchy import HierarchyOverlay


logger = logging.getLogger(__name__)


class BeeProgressDialog(QtWidgets.QProgressDialog):

    def __init__(self, label, worker, maximum=0, parent=None):
        super().__init__(label, 'Cancel', 0, maximum, parent=parent)
        logger.debug('Initialised progress bar')
        self.setMinimumDuration(0)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAutoReset(False)
        self.setAutoClose(False)
        worker.begin_processing.connect(self.on_begin_processing)
        worker.progress.connect(self.on_progress)
        worker.finished.connect(self.on_finished)
        worker.user_input_required.connect(self.on_finished)
        self.canceled.connect(worker.on_canceled)

    def on_progress(self, value):
        logger.debug(f'Progress dialog: {value}')
        self.setValue(value)

    def on_begin_processing(self, value):
        logger.debug(f'Beginn progress dialog: {value}')
        self.setMaximum(value)

    def on_finished(self, *args, **kwargs):
        logger.debug('Finished progress dialog')
        self.setValue(self.maximum())
        self.reset()
        self.hide()
        QtCore.QTimer.singleShot(100, self.deleteLater)


class HelpDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(f'{constants.APPNAME} Help')

        tabs = QtWidgets.QTabWidget()

        # Controls
        controls_txt = rsc_files(
            'threecolref.documentation').joinpath('controls.html').read_text()
        controls_label = QtWidgets.QLabel(controls_txt)
        controls_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(controls_label)
        tabs.addTab(scroll, '&Controls')

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)
        layout.addWidget(tabs)

        # Bottom row of buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.show()


class DebugLogDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(f'{constants.APPNAME} Debug Log')
        with open(logfile_name()) as f:
            self.log_txt = f.read()

        self.log = QtWidgets.QPlainTextEdit(self.log_txt)
        self.log.setReadOnly(True)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self.copy_button = QtWidgets.QPushButton('Co&py To Clipboard')
        self.copy_button.released.connect(self.copy_to_clipboard)
        buttons.addButton(
            self.copy_button, QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)
        name_widget = QtWidgets.QLabel(logfile_name())
        name_widget.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(name_widget)
        layout.addWidget(self.log)
        layout.addWidget(buttons)
        self.show()

    def copy_to_clipboard(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.log_txt)


class SceneToPixmapExporterDialog(QtWidgets.QDialog):
    MIN_SIZE = 10
    MAX_SIZE = 100000

    def __init__(self, parent, default_size):
        super().__init__(parent)
        self.default_size = default_size
        if (self.default_size.width() > self.MAX_SIZE
                or self.default_size.width() >= self.MAX_SIZE):
            self.default_size.scale(
                self.MAX_SIZE, self.MAX_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio)

        self.ignore_change = False
        self.setWindowTitle('Export Scene to Image')
        self.setWindowModality(Qt.WindowModality.WindowModal)
        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)

        width_label = QtWidgets.QLabel('Width:')
        layout.addWidget(width_label, 0, 0)
        self.width_input = QtWidgets.QSpinBox()
        self.width_input.setRange(self.MIN_SIZE, self.MAX_SIZE)
        self.width_input.setValue(default_size.width())
        self.width_input.valueChanged.connect(self.on_width_changed)
        layout.addWidget(self.width_input, 0, 1)

        height_label = QtWidgets.QLabel('Height:')
        layout.addWidget(height_label, 1, 0)
        self.height_input = QtWidgets.QSpinBox()
        self.height_input.setMinimum(10)
        self.height_input.setRange(self.MIN_SIZE, self.MAX_SIZE)
        self.height_input.setValue(default_size.height())
        self.height_input.valueChanged.connect(self.on_height_changed)
        layout.addWidget(self.height_input, 1, 1)

        # Bottom row of buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel)

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 3, 1)

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


class ChangeOpacityDialog(QtWidgets.QDialog):

    def __init__(self, parent, images, undo_stack):
        super().__init__(parent)
        self.undo_stack = undo_stack
        self.images = images
        self.command = commands.ChangeOpacity(images, opacity=1)

        value = int(images[0].opacity() * 100) if images else 100

        self.setWindowTitle('Change Opacity:')
        self.setWindowModality(Qt.WindowModality.WindowModal)
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.label = QtWidgets.QLabel('Opacity:')
        layout.addWidget(self.label)

        self.input = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.input.valueChanged.connect(self.on_value_changed)
        self.input.setRange(0, 100)
        self.input.setValue(value)
        layout.addWidget(self.input)

        # Bottom row of buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel)

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
    """Minimalist window control button."""
    def __init__(self, parent, btn_type, callback=None):
        super().__init__(parent)
        self.btn_type = btn_type
        self.setFixedSize(28, 24)
        self.setFlat(True)
        self.setCheckable(btn_type == 'pin')
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.is_checked = False # Used for Pin button
        if callback:
            self.clicked.connect(callback)
        
        # Ensure buttons receive mouse events and stop propagation
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def enterEvent(self, event):
        # Force cursor reset on entry
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def mouseReleaseEvent(self, event):
        # Stop event propagation
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
        cx, cy = w // 2, h // 2
        
        # Draw hover background
        if self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            if self.btn_type == 'close':
                painter.setBrush(QtGui.QColor(232, 17, 35, 200)) # Red
            else:
                painter.setBrush(QtGui.QColor(255, 255, 255, 25)) # Light highlight
                
            margin = 2
            from PyQt6.QtCore import QRectF
            rect = QRectF(margin, margin, w - 2*margin, h - 2*margin)
            painter.drawRoundedRect(rect, 4, 4)
            
        # Determine icon color
        icon_color = QtGui.QColor(200, 200, 200)
        if self.underMouse() and self.btn_type == 'close':
            icon_color = QtGui.QColor(255, 255, 255)
            
        pen = QtGui.QPen(icon_color)
        pen.setWidth(1)
        painter.setPen(pen)
        
        if self.btn_type == 'close':
            size = 4
            painter.drawLine(cx - size, cy - size, cx + size, cy + size)
            painter.drawLine(cx + size, cy - size, cx - size, cy + size)
        elif self.btn_type == 'min':
            size = 5
            painter.drawLine(cx - size, cy, cx + size, cy)
        elif self.btn_type == 'max':
            # Maximize: single square. Restore: two overlapping squares
            size = 4
            mw = getattr(self, '_main_window', None)
            is_maximized = mw.isMaximized() if mw else False
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if is_maximized:
                # Restore icon: two overlapping squares
                painter.drawRect(cx - size, cy - size + 2, size * 2, size * 2)
                painter.drawRect(cx - size + 2, cy - size - 2, size * 2, size * 2)
            else:
                # Maximize icon: single square (fullscreen)
                painter.drawRect(cx - size, cy - size, size * 2, size * 2)
        elif self.btn_type == 'pin':
            # Custom push-pin icon based on provided SVG, adjusted for weight and state
            painter.save()
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

            # Use white when active (checked), otherwise theme gray/hover color
            color = QtGui.QColor(255, 255, 255) if self.is_checked else icon_color
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QBrush(color))

            painter.translate(cx, cy)
            painter.scale(0.5, 0.5) # Scale to fit vertically
            # Move it UP by decreasing the Y translation (more negative)
            # Full path Y range is [4, 23], center is 13.5. 
            # Shifting to -16 moves it up by 2.5 pixels in path-space (~1.25 pixels in button-space at 0.5 scale)
            painter.translate(-12, -15.5) 

            path = QtGui.QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill if self.is_checked else Qt.FillRule.OddEvenFill)
            
            # Restore FULL Outer boundary from pin-svgrepo-com.svg
            path.moveTo(6.5, 5)
            path.cubicTo(6.5, 4.45, 6.95, 4, 7.5, 4)
            path.lineTo(9, 4)
            path.lineTo(15, 4)
            path.lineTo(16.5, 4)
            path.cubicTo(17.05, 4, 17.5, 4.45, 17.5, 5)
            path.cubicTo(17.5, 5.55, 17.05, 6, 16.5, 6)
            path.lineTo(16.095, 6)
            path.lineTo(16.913, 15)
            path.lineTo(19, 15)
            path.cubicTo(19.55, 15, 20, 15.45, 20, 16)
            path.cubicTo(20, 16.55, 19.55, 17, 19, 17)
            path.lineTo(16, 17)
            path.lineTo(13, 17)
            path.lineTo(13, 22)
            path.cubicTo(13, 22.55, 12.55, 23, 12, 23)
            path.cubicTo(11.45, 23, 11, 22.55, 11, 22)
            path.lineTo(11, 17)
            path.lineTo(8, 17)
            path.lineTo(5, 17)
            path.cubicTo(4.45, 17, 4, 16.55, 4, 16)
            path.cubicTo(4, 15.45, 4.45, 15, 5, 15)
            path.lineTo(7.087, 15)
            path.lineTo(7.905, 6)
            path.lineTo(7.5, 6)
            path.cubicTo(6.95, 6, 6.5, 5.55, 6.5, 5)
            path.closeSubpath()

            # Inner cutout (makes it an outline when inactive)
            if not self.is_checked:
                path.moveTo(9.913, 6)
                path.lineTo(9.095, 15)
                path.lineTo(12, 15)
                path.lineTo(14.905, 15)
                path.lineTo(14.087, 6)
                path.lineTo(9.913, 6)
                path.closeSubpath()

            painter.drawPath(path)
            painter.restore()





class BeeTitleBar(QtWidgets.QWidget):
    """Integrated title bar that auto-hides like PureRef and is resizable in height."""

    def __init__(self, parent, view):
        super().__init__(parent)
        self.view = view
        self.main_window = parent.window()

        self._expanded_height = 30
        self._collapsed_height = 4
        self._expanded = False
        self._resizing_height = False
        self._resize_start_y = None
        self._resize_start_height = None
        self._resize_margin = 4

        self.setObjectName("beeTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(10)

        # Left: App Icon and Title
        self.icon_label = QtWidgets.QLabel()
        from threecolref.assets import BeeAssets

        self.icon_label.setPixmap(BeeAssets().logo.pixmap(16, 16))
        self.icon_label.setCursor(Qt.CursorShape.ArrowCursor)
        layout.addWidget(self.icon_label)

        self.title_label = QtWidgets.QLabel(constants.APPNAME)
        self.title_label.setStyleSheet("font-size: 11px; font-weight: bold;")
        self.title_label.setCursor(Qt.CursorShape.ArrowCursor)
        layout.addWidget(self.title_label)

        # Middle: Stretch
        layout.addStretch()

        # Right: Window Controls
        self.controls = BeeWindowControls(self, view)
        layout.addWidget(self.controls)

        # Base cursor for title bar is standard arrow
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setMouseTracking(True)
        self.icon_label.setMouseTracking(True)
        self.title_label.setMouseTracking(True)
        self.controls.setMouseTracking(True)

        self._dragging_window = False
        self._resizing_height = False
        self._drag_start_pos = None

        # Start collapsed; expand on hover
        self._set_collapsed()

    def _set_expanded(self):
        self._expanded = True
        self.setMinimumHeight(self._expanded_height)
        self.setMaximumHeight(200)  # Allow resizing up to 200px
        self.setFixedHeight(self._expanded_height)
        self.setStyleSheet("""
            QWidget#beeTitleBar { background-color: #1e1e1e; }
            QLabel { color: #cccccc; background-color: transparent; }
        """)
        self.icon_label.show()
        self.title_label.show()
        self.controls.show()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._update_overlay_geometry()

    def _set_collapsed(self):
        self._expanded = False
        self.setFixedHeight(self._collapsed_height)
        self.setStyleSheet("""
            QWidget#beeTitleBar { background-color: transparent; }
            QLabel { color: #cccccc; background-color: transparent; }
        """)
        self.icon_label.hide()
        self.title_label.hide()
        self.controls.hide()
        self._update_overlay_geometry()

    def _update_overlay_geometry(self):
        """Keep overlay at top, full width (parent may be BeeMainWidget)."""
        p = self.parent()
        if p and hasattr(p, 'width'):
            self.setGeometry(0, 0, p.width(), self.height())

    def enterEvent(self, event):
        self._set_expanded()
        super().enterEvent(event)

    def leaveEvent(self, event):
        # Collapse when mouse leaves the title bar
        self._set_collapsed()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            
            is_interactive = False
            # Allow interacting with controls
            if self.controls.geometry().contains(pos):
                is_interactive = True
                
            if not is_interactive:
                if pos.y() >= self.height() - self._resize_margin:
                    self._resizing_height = True
                    self._resize_start_y = event.globalPosition().y()
                    self._resize_start_height = self.height()
                    event.accept()
                else:
                    self._dragging_window = True
                    self._drag_start_pos = event.globalPosition().toPoint()
                    event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._expanded:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(event)
            return

        pos = event.pos()
        x, y = pos.x(), pos.y()

        # Check if over controls or labels
        is_over_interactive = False
        if self.icon_label.isVisible() and self.icon_label.geometry().contains(pos):
            is_over_interactive = True
        if self.title_label.isVisible() and self.title_label.geometry().contains(pos):
            is_over_interactive = True
        if self.controls.isVisible() and self.controls.geometry().contains(pos):
            is_over_interactive = True

        if is_over_interactive:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif y >= self.height() - self._resize_margin:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)

        # Handle window dragging and resizing
        if self._resizing_height:
            delta_y = event.globalPosition().y() - self._resize_start_y
            new_height = max(self._expanded_height, 
                             min(200, self._resize_start_height + delta_y))
            self.setFixedHeight(int(new_height))
            event.accept()
        elif self._dragging_window:
            if self._drag_start_pos is not None:
                delta = event.globalPosition().toPoint() - self._drag_start_pos
                new_pos = self.main_window.pos() + delta
                self.main_window.move(new_pos)
                self._drag_start_pos = event.globalPosition().toPoint()
                event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Don't toggle maximize if double-clicking on controls
            if not self.controls.geometry().contains(event.pos()):
                self.controls.toggle_maximized()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging_window = False
        self._resizing_height = False
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)


class BeeWindowControls(QtWidgets.QWidget):
    """Container for Pin, Min, Max, and Close buttons."""
    def __init__(self, parent, view):
        super().__init__(parent)
        self.view = view
        self.main_window = parent.window()
        
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.pin_btn = BeeWindowButton(self, 'pin')
        self.pin_btn.setToolTip('Always On Top (Ctrl+Shift+A)')
        
        self.min_btn = BeeWindowButton(self, 'min', self.toggle_minimize)
        self.min_btn.setToolTip('Minimize')
        self.max_btn = BeeWindowButton(self, 'max', self.toggle_maximized)
        self.max_btn.setToolTip('Maximize / Restore (centered)')
        self.close_btn = BeeWindowButton(self, 'close', self.main_window.close)
        self.close_btn.setToolTip('Close')

        layout.addWidget(self.pin_btn)
        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)
        
        self.pin_btn.clicked.connect(self.on_pin_clicked)
        # Update max/restore icon when window state changes
        self.main_window.windowStateChanged.connect(self._on_window_state_changed)
        self.max_btn._main_window = self.main_window  # For max/restore icon state
        
        # Ensure controls widget receives mouse events and has a standard pointer
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.show()

    
    def mousePressEvent(self, event):
        # Stop event propagation - don't let title bar handle button area clicks
        event.accept()
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        # Stop event propagation
        event.accept()
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        # Stop event propagation
        event.accept()
        super().mouseReleaseEvent(event)

    def toggle_maximized(self):
        """Maximize when floating; when maximized, restore to centered window (not fullscreen)."""
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
        """Minimize window to taskbar."""
        self.main_window.showMinimized()

    def _on_window_state_changed(self):
        self.max_btn.update()

    def on_pin_clicked(self):
        from threecolref.actions.actions import bee_actions
        action = bee_actions['always_on_top'].qaction
        # Toggle the main action, which will in turn call update_states
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


class ExportImagesFileExistsDialog(QtWidgets.QDialog):

    def __init__(self, parent, filename):
        super().__init__(parent)
        self.setWindowTitle('File exists')

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        label = QtWidgets.QLabel(
            f'File already exists:\n{filename}')
        layout.addWidget(label)

        choices = (('skip', 'Skip this file'),
                   ('skip_all', 'Skip all existing files'),
                   ('overwrite', 'Overwrite this file'),
                   ('overwrite_all', 'Overwrite all existing files'))

        self.radio_buttons = {}
        for (value, label) in choices:
            btn = QtWidgets.QRadioButton(label)
            self.radio_buttons[value] = btn
            layout.addWidget(btn)
        self.radio_buttons['skip'].setChecked(True)

        # Bottom row of buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class UnsavedChangesDialog(QtWidgets.QDialog):
    """Custom dialog for unsaved changes with 'Remember my choice' option."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Discard unsaved changes?")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(400)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)

        # Message
        self.label = QtWidgets.QLabel("You have unsaved changes. Would you like to save them before exiting?")
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-size: 13px;")
        layout.addWidget(self.label)

        # Checkbox for "Remember my choice"
        self.remember_checkbox = QtWidgets.QCheckBox("Remember my choice")
        self.remember_checkbox.setToolTip("If checked, this choice will be applied automatically in the future.")
        layout.addWidget(self.remember_checkbox)

        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(10)
        
        from threecolref.utils import qcolor_to_hex
        
        self.save_btn = QtWidgets.QPushButton("Save")
        self.save_btn.setMinimumHeight(32)
        active_color = constants.COLORS['Active:Button']
        self.save_btn.setStyleSheet(f"background-color: rgb({active_color[0]}, {active_color[1]}, {active_color[2]}); color: white; font-weight: bold; padding: 0 15px;")
        
        self.discard_btn = QtWidgets.QPushButton("Discard")
        self.discard_btn.setMinimumHeight(32)
        self.discard_btn.setStyleSheet("padding: 0 15px;")
        
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(32)
        self.cancel_btn.setStyleSheet("padding: 0 15px;")

        button_layout.addStretch()
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.discard_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)

        # Connect buttons
        self.save_btn.clicked.connect(lambda: self.done(QtWidgets.QMessageBox.StandardButton.Save.value))
        self.discard_btn.clicked.connect(lambda: self.done(QtWidgets.QMessageBox.StandardButton.Discard.value))
        self.cancel_btn.clicked.connect(lambda: self.done(QtWidgets.QMessageBox.StandardButton.Cancel.value))

        # Default button
        self.save_btn.setDefault(True)

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
