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
import os.path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QRect, QPoint

from threecolref.config import BeeSettings
from threecolref.main_controls import MainControlsMixin
from .welcome_overlay_recents import RecentFilesContainer


logger = logging.getLogger(__name__)


class RecentFilesModel(QtCore.QAbstractListModel):
    """An entry in the 'Recent Files' list."""

    def __init__(self, files):
        super().__init__()
        self.files = files

    def rowCount(self, parent):
        return len(self.files)

    def data(self, index, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return os.path.basename(self.files[index.row()])
        if role == QtCore.Qt.ItemDataRole.FontRole:
            font = QtGui.QFont()
            font.setUnderline(True)
            return font


class RecentFilesView(QtWidgets.QListView):

    def __init__(self, parent, view, files=None):
        super().__init__(parent)
        self.view = view
        self.files = files or []
        self.clicked.connect(self.on_clicked)
        self.setModel(RecentFilesModel(self.files))
        self.setMouseTracking(True)

    def on_clicked(self, index):
        self.view.open_from_file(self.files[index.row()])

    def update_files(self, files):
        self.files = files
        self.model().files = files
        self.reset()

    def sizeHint(self):
        size = QtCore.QSize()
        height = sum(
            (self.sizeHintForRow(i) + 2) for i in range(len(self.files)))
        width = max(self.sizeHintForColumn(i) for i in range(len(self.files)))
        size.setHeight(height)
        size.setWidth(width + 2)
        return size

    def mouseMoveEvent(self, event):
        index = self.indexAt(
            QtCore.QPoint(int(event.position().x()),
                          int(event.position().y())))
        if index.isValid():
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        super().mouseMoveEvent(event)


class DropZoneIcon(QtWidgets.QWidget):
    """Custom widget that draws a PureRef-style dashed image drop zone icon."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 65)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        pen = QtGui.QPen(QtGui.QColor(100, 100, 100, 160))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)

        # Outer dashed rectangle (scaled from 100x80 to 60x50)
        rect = QtCore.QRect(10, 8, 60, 50)
        painter.drawRoundedRect(rect, 3, 3)

        # Inner image icon - mountain/landscape placeholder (scaled)
        painter.setPen(QtGui.QPen(QtGui.QColor(90, 90, 90, 140), 1.5))
        painter.setBrush(QtGui.QBrush(QtGui.QColor(80, 80, 80, 80)))

        # Image frame
        img_rect = QtCore.QRect(18, 12, 40, 28)
        painter.drawRect(img_rect)

        # Sun circle
        painter.setBrush(QtGui.QBrush(QtGui.QColor(100, 100, 100, 120)))
        painter.drawEllipse(24, 17, 8, 8)

        # Mountain polygon (scaled)
        mountain = QtGui.QPolygon([
            QtCore.QPoint(18, 42), QtCore.QPoint(30, 26),
            QtCore.QPoint(38, 34), QtCore.QPoint(46, 24),
            QtCore.QPoint(58, 42)
        ])
        painter.drawPolygon(mountain)
        painter.end()


class ResizableFloatingWidget(QtWidgets.QWidget):
    """Fixed drop zone: not draggable, always centered. Corners=resize only."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._resize_margin = 8   # Corners only for resize
        self._resizing = False
        self._resize_corner = None
        
        # Make it float/overlay without affecting layout - use widget flags, not window flags
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        
        # Ensure widget can receive mouse events
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        
        # Semi-transparent dark background with rounded corners
        self.setStyleSheet('''
            ResizableFloatingWidget {
                background-color: transparent;
                border: none;
            }
        ''')
        
        self.setCursor(Qt.CursorShape.ArrowCursor)
    
    def _is_in_resize_corner(self, pos):
        """Corners only for resize."""
        w, h = self.width(), self.height()
        rm = self._resize_margin
        return (pos.x() <= rm and pos.y() <= rm) or (pos.x() >= w - rm and pos.y() <= rm) or \
               (pos.x() <= rm and pos.y() >= h - rm) or (pos.x() >= w - rm and pos.y() >= h - rm)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            rect = self.rect()

            # Never drag/resize when clicking on center content (icon, label, browse)
            child = self.childAt(pos)
            if child is not None:
                super().mousePressEvent(event)
                return

            # Corners: resize
            if (pos.x() <= self._resize_margin and pos.y() <= self._resize_margin):
                self._resizing = True
                self._resize_corner = 'top-left'
            elif (pos.x() >= rect.width() - self._resize_margin and pos.y() <= self._resize_margin):
                self._resizing = True
                self._resize_corner = 'top-right'
            elif (pos.x() <= self._resize_margin and pos.y() >= rect.height() - self._resize_margin):
                self._resizing = True
                self._resize_corner = 'bottom-left'
            elif (pos.x() >= rect.width() - self._resize_margin and pos.y() >= rect.height() - self._resize_margin):
                self._resizing = True
                self._resize_corner = 'bottom-right'
            # No dragging - widget stays fixed in place
        
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        if self._resizing and self._resize_corner:
            # Use local coordinates relative to parent
            local_pos = event.position().toPoint()
            geom = self.geometry()
            
            if self._resize_corner == 'top-left':
                delta = local_pos - geom.topLeft()
                new_width = max(200, geom.width() - delta.x())
                new_height = max(150, geom.height() - delta.y())
                self.setGeometry(geom.x() + delta.x(), geom.y() + delta.y(),
                               new_width, new_height)
            elif self._resize_corner == 'top-right':
                delta_y = local_pos.y() - geom.top()
                new_width = max(200, local_pos.x() - geom.x())
                new_height = max(150, geom.height() - delta_y)
                self.setGeometry(geom.x(), geom.y() + delta_y, new_width, new_height)
            elif self._resize_corner == 'bottom-left':
                delta_x = local_pos.x() - geom.left()
                new_width = max(200, geom.width() - delta_x)
                new_height = max(150, local_pos.y() - geom.y())
                self.setGeometry(geom.x() + delta_x, geom.y(), new_width, new_height)
            elif self._resize_corner == 'bottom-right':
                new_width = max(200, local_pos.x() - geom.x())
                new_height = max(150, local_pos.y() - geom.y())
                self.setGeometry(geom.x(), geom.y(), new_width, new_height)
            elif self._resize_corner == 'left':
                delta_x = local_pos.x() - geom.left()
                new_width = max(200, geom.width() - delta_x)
                self.setGeometry(geom.x() + delta_x, geom.y(), new_width, geom.height())
            elif self._resize_corner == 'right':
                new_width = max(200, local_pos.x() - geom.x())
                self.setGeometry(geom.x(), geom.y(), new_width, geom.height())
            elif self._resize_corner == 'top':
                delta_y = local_pos.y() - geom.top()
                new_height = max(150, geom.height() - delta_y)
                self.setGeometry(geom.x(), geom.y() + delta_y, geom.width(), new_height)
            elif self._resize_corner == 'bottom':
                new_height = max(150, local_pos.y() - geom.y())
                self.setGeometry(geom.x(), geom.y(), geom.width(), new_height)
        else:
            # Update cursor: corners=resize only, no drag
            pos = event.position().toPoint()
            rect = self.rect()
            if self._is_in_resize_corner(pos):
                if (pos.x() <= self._resize_margin and pos.y() <= self._resize_margin) or \
                   (pos.x() >= rect.width() - self._resize_margin and pos.y() >= rect.height() - self._resize_margin):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                else:
                    self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        if self._resizing:
            event.accept()
        self._resizing = False
        self._resize_corner = None
        super().mouseReleaseEvent(event)


class WelcomeOverlay(MainControlsMixin, QtWidgets.QWidget):
    """Some basic info to be displayed when the scene is empty."""

    txt = """<p>Paste or drop images here.</p>
             <p>Right-click for more options.</p>"""

    def __init__(self, parent):
        super().__init__(parent)
        self.control_target = parent
        # Robustly find the main window
        main_window = getattr(parent, 'host_window', None) or parent.window()
        self.init_main_controls(main_window=main_window)
        # Ensure proper rendering - don't use NoSystemBackground as it can cause double rendering
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        # Set transparent background so graphics view shows through
        self.setStyleSheet('background-color: transparent;')
        # Make overlay not affect layout - position absolutely
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        
        # Create resizable floating widget container
        self.floating_widget = ResizableFloatingWidget(self)
        
        # PureRef-style center widget - not draggable, blocks drag events
        center = QtWidgets.QWidget(self.floating_widget)
        center.setCursor(Qt.CursorShape.ArrowCursor)
        center_layout = QtWidgets.QVBoxLayout(center)
        center_layout.setContentsMargins(12, 12, 12, 12)
        center_layout.setSpacing(8)
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Add stretches to keep content centered
        center_layout.addStretch()

        # Use Open Sans (falls back to system sans-serif if not installed)
        font = QtGui.QFont('Open Sans', 10, QtGui.QFont.Weight.Light)
        font_or = QtGui.QFont('Open Sans', 9, QtGui.QFont.Weight.Light)

        # Dashed drop icon (custom painted widget) - parent to center, not self
        self.drop_icon = DropZoneIcon(center)
        center_layout.addWidget(self.drop_icon, 0, Qt.AlignmentFlag.AlignCenter)

        # "Drag and drop images or videos here" - parent to center, not self
        self.label = QtWidgets.QLabel('Drag and drop images or videos here', center)
        self.label.setFont(font)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet('color: rgba(180, 180, 180, 0.75); background: transparent;')
        center_layout.addWidget(self.label)

        # "or" - parent to center, not self
        self.or_label = QtWidgets.QLabel('or', center)
        self.or_label.setFont(font_or)
        self.or_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.or_label.setStyleSheet('color: rgba(120, 120, 120, 0.6); background: transparent;')
        center_layout.addWidget(self.or_label)

        # Browse button - parent to center, not self
        self.browse_btn = QtWidgets.QPushButton('Browse', center)
        self.browse_btn.setFixedSize(90, 28)
        self.browse_btn.setFont(QtGui.QFont('Open Sans', 10))
        self.browse_btn.setStyleSheet('''
            QPushButton {
                background-color: #3d9fc0;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 16px;
            }
            QPushButton:hover {
                background-color: #4db8dc;
            }
            QPushButton:pressed {
                background-color: #2d7a96;
            }
        ''')
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.clicked.connect(self._on_browse)
        center_layout.addWidget(self.browse_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Add stretch at bottom to keep content centered vertically
        center_layout.addStretch()

        # Recent Files section
        self.recent_container = RecentFilesContainer(self.floating_widget)
        self.recent_container.file_selected.connect(self._on_recent_selected)
        self.recent_container.browse_requested.connect(self._on_browse_recent)
        
        # Main floating widget layout: 
        # 1. Top region (Drop zone) - floating freely
        # 2. Bottom region (History box) - distinct dark container
        self.floating_layout = QtWidgets.QVBoxLayout(self.floating_widget)
        self.floating_layout.setContentsMargins(0, 0, 0, 0)
        self.floating_layout.setSpacing(0) 
        
        # Add stretches around center content for dynamic centering
        self.top_spacer = self.floating_layout.addStretch(0)
        
        # Add drop zone content (center widget)
        self.center_container = QtWidgets.QWidget()
        center_container_layout = QtWidgets.QVBoxLayout(self.center_container)
        center_container_layout.setContentsMargins(0, 0, 0, 0)
        center_container_layout.addWidget(center, 0, Qt.AlignmentFlag.AlignCenter)
        
        self.floating_layout.addWidget(self.center_container, 0, Qt.AlignmentFlag.AlignCenter)
        
        self.mid_spacer = self.floating_layout.addStretch(1)
        
        # Add Recent container at the bottom (The dark box)
        self.floating_layout.addWidget(self.recent_container)
        
        # WelcomeOverlay has no layout - floating widget is positioned absolutely
        # Make it a child but don't add to layout - truly floating
        self.floating_widget.setParent(self)
        self.floating_widget.raise_()  # Ensure it's on top
        
        # Size to accommodate both sections plus some breathing room
        self.floating_widget.setMinimumSize(250, 200)
        self._preferred_float_size = QtCore.QSize(900, 680)
        self.floating_widget.resize(900, 680)
        
        self.update_visibility()
        
        # Ensure overlay doesn't affect layout - make it transparent to layout
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def resizeEvent(self, event):
        """Resize and re-center floating widget when overlay is resized."""
        super().resizeEvent(event)
        try:
            if hasattr(self, 'floating_widget') and self.floating_widget is not None:
                pw, ph = self.width(), self.height()
                if pw > 0 and ph > 0:  # Only resize if parent has valid size
                    pref = getattr(self, '_preferred_float_size', self.floating_widget.size())
                    fw = min(pref.width(), pw)
                    fh = min(pref.height(), ph)
                    if fw > 0 and fh > 0:  # Only apply valid sizes
                        self.floating_widget.resize(fw, fh)
                        self._center_floating_widget()
        except Exception:
            pass

    def _on_browse(self):
        """Open file dialog to browse and insert images."""
        self.control_target.on_action_insert_images()

    def _on_browse_recent(self):
        """Open file dialog to browse and open existing 3col projects."""
        self.control_target.on_action_open()

    def _on_recent_selected(self, filename):
        """Open a recent file."""
        self.control_target.open_from_file(filename)

    def update_visibility(self):
        """Update visibility of components based on recent files."""
        files = BeeSettings().get_recent_files(existing_only=True)
        if files:
            self.recent_container.show()
            self.recent_container.refresh()
            self.label.setText("Drag and drop images here")
            
            # Position drop zone in top half
            self.floating_layout.setStretch(0, 0) # Top stretch 0
            self.floating_layout.setStretch(2, 1) # Mid stretch 1
            
            self._preferred_float_size = QtCore.QSize(900, 680)
            self.floating_widget.resize(900, 680)
        else:
            self.recent_container.hide()
            self.label.setText("Drag and drop images here")
            
            # Position drop zone in dead center
            self.floating_layout.setStretch(0, 1) # Top stretch 1
            self.floating_layout.setStretch(2, 1) # Mid stretch 1
            
            self._preferred_float_size = QtCore.QSize(600, 400)
            self.floating_widget.resize(600, 400)
            
        # CRITICAL: Always re-center after resizing
        self._center_floating_widget()

    def show(self):
        super().show()
        # Center the floating widget when shown
        if hasattr(self, 'floating_widget'):
            self._center_floating_widget()
        self.floating_widget.show()
    
    def _center_floating_widget(self):
        """Center the floating widget within the overlay, clamped to bounds."""
        parent_rect = self.rect()
        widget_size = self.floating_widget.size()
        x = max(0, (parent_rect.width() - widget_size.width()) // 2)
        y = max(0, (parent_rect.height() - widget_size.height()) // 2)
        self.floating_widget.move(x, y)

    def disable_mouse_events(self):
        self.label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.browse_btn.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def enable_mouse_events(self):
        self.label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, on=False)
        self.browse_btn.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, on=False)

    def mousePressEvent(self, event):
        # Don't forward events - let the floating widget receive them directly
        # The floating widget is a child, so it should receive events naturally
        if self.mousePressEventMainControls(event):
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Don't forward - let natural event propagation handle it
        if self.mouseMoveEventMainControls(event):
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # Don't forward - let natural event propagation handle it
        if self.mouseReleaseEventMainControls(event):
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self.keyPressEventMainControls(event):
            return
        super().keyPressEvent(event)
