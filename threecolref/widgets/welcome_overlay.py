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

import json
import logging
import math
import os
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
    """Content block for the welcome overlay — corners resize only, otherwise no dragging."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._resize_margin = 10   # Corner hit zone in px
        self._resizing = False
        self._resize_corner = None
        self._press_geom = None    # Geometry at the time of press (parent-space)
        self._press_mouse = None   # Mouse position at the time of press (parent-space)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setStyleSheet('''
            ResizableFloatingWidget {
                background-color: transparent;
                border: none;
            }
        ''')
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _corner_at(self, pos):
        """Return corner name if pos (local widget coords) is in a resize corner, else None."""
        w, h = self.width(), self.height()
        rm = self._resize_margin
        in_left  = pos.x() <= rm
        in_right = pos.x() >= w - rm
        in_top   = pos.y() <= rm
        in_bot   = pos.y() >= h - rm
        if in_left  and in_top:  return 'tl'
        if in_right and in_top:  return 'tr'
        if in_left  and in_bot:  return 'bl'
        if in_right and in_bot:  return 'br'
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            child = self.childAt(pos)
            if child is not None:
                super().mousePressEvent(event)
                return
            corner = self._corner_at(pos)
            if corner:
                self._resizing = True
                self._resize_corner = corner
                # Store starting state in parent-space coordinates
                self._press_geom = self.geometry()
                self._press_mouse = self.mapToParent(pos)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing and self._resize_corner and self._press_geom is not None:
            # Convert current mouse position to PARENT coordinate space
            cur = self.mapToParent(event.position().toPoint())
            pg = self._press_geom
            pm = self._press_mouse
            dx = cur.x() - pm.x()
            dy = cur.y() - pm.y()

            if self._resize_corner == 'br':
                nw = max(200, pg.width()  + dx)
                nh = max(150, pg.height() + dy)
                self.resize(nw, nh)

            elif self._resize_corner == 'bl':
                nw = max(200, pg.width()  - dx)
                nh = max(150, pg.height() + dy)
                nx = pg.right() - nw
                self.setGeometry(nx, pg.y(), nw, nh)

            elif self._resize_corner == 'tr':
                nw = max(200, pg.width()  + dx)
                nh = max(150, pg.height() - dy)
                ny = pg.bottom() - nh
                self.setGeometry(pg.x(), ny, nw, nh)

            elif self._resize_corner == 'tl':
                nw = max(200, pg.width()  - dx)
                nh = max(150, pg.height() - dy)
                nx = pg.right()  - nw
                ny = pg.bottom() - nh
                self.setGeometry(nx, ny, nw, nh)

            event.accept()
            return

        # Not resizing — update cursor based on position
        pos = event.position().toPoint()
        corner = self._corner_at(pos)
        if corner:
            if corner in ('tl', 'br'):
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
        self._press_geom = None
        self._press_mouse = None
        super().mouseReleaseEvent(event)



class UpdateBanner(QtWidgets.QFrame):
    """A collapsible banner on the welcome screen driven by a remote update.json.

    Fetches https://raw.githubusercontent.com/Luohino/threecolrefupdate/main/update.json
    in a background thread at startup. If message is empty or fetch fails, stays hidden.
    Fields: version, message, link, link_text
    """

    _RAW_URL = 'https://raw.githubusercontent.com/Luohino/threecolrefupdate/main/update.json'

    # Internal Qt signal to safely update UI from background thread
    _data_ready = QtCore.pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('UpdateBanner')
        self.hide()  # Always start hidden; show only after fetch succeeds
        self._data_ready.connect(self._on_data_ready)
        self._fetch_in_background()

    def _fetch_in_background(self):
        import threading
        t = threading.Thread(target=self._fetch, daemon=True, name='update-banner-fetch')
        t.start()

    def _fetch(self):
        try:
            import urllib.request
            req = urllib.request.Request(
                self._RAW_URL,
                headers={'User-Agent': 'Mozilla/5.0 ThreeColRef updater'}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                self._data_ready.emit(data)
        except Exception as e:
            logger.debug(f'[update-banner] Could not fetch update.json: {e}')

    def _on_data_ready(self, data):
        if not data.get('message'):
            return  # Nothing to show — stay hidden
        self._data = data
        self._build_ui()
        self.show()
        # Force parent layout to reflow
        if self.parent() and self.parent().layout():
            self.parent().layout().activate()

    def _build_ui(self):
        msg = self._data.get('message', '')
        version = self._data.get('version', '')
        link = self._data.get('link', '')
        link_text = self._data.get('link_text', 'Learn more')

        self.setStyleSheet('''
            #UpdateBanner {
                background-color: rgba(255, 214, 10, 0.10);
                border: 1px solid rgba(255, 214, 10, 0.30);
                border-radius: 10px;
            }
        ''')

        h_layout = QtWidgets.QHBoxLayout(self)
        h_layout.setContentsMargins(16, 10, 12, 10)
        h_layout.setSpacing(10)

        # Icon
        icon_lbl = QtWidgets.QLabel('✦')
        icon_lbl.setStyleSheet('color: #FFD60A; font-size: 14px; background: transparent;')
        h_layout.addWidget(icon_lbl)

        # Text block
        v = QtWidgets.QVBoxLayout()
        v.setSpacing(1)

        if version:
            ver_lbl = QtWidgets.QLabel(f'v{version}')
            ver_lbl.setStyleSheet('color: #FFD60A; font-size: 10px; font-weight: bold; background: transparent;')
            v.addWidget(ver_lbl)

        msg_lbl = QtWidgets.QLabel(msg)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet('color: rgba(220, 220, 220, 0.90); font-size: 12px; background: transparent;')
        v.addWidget(msg_lbl)

        if link:
            link_lbl = QtWidgets.QLabel(f'<a href="{link}" style="color:#53a7a5;">{link_text}</a>')
            link_lbl.setOpenExternalLinks(True)
            link_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            link_lbl.setStyleSheet('background: transparent; font-size: 12px;')
            v.addWidget(link_lbl)

        h_layout.addLayout(v)
        h_layout.addStretch()

        # Dismiss ✕
        close_btn = QtWidgets.QPushButton('✕')
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet('''
            QPushButton { background: transparent; color: rgba(180,180,180,0.6); border: none; font-size: 12px; }
            QPushButton:hover { color: white; }
        ''')
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        h_layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)


class WelcomeOverlay(MainControlsMixin, QtWidgets.QWidget):
    """Some basic info to be displayed when the scene is empty."""

    def paintEvent(self, event):
        """Draw a dark overlay. Solid if loading, semi-transparent otherwise."""
        painter = QtGui.QPainter(self)
        if self._loading_container.isVisible():
            # Solid backdrop when loading to obscure everything (pills, scene, etc.)
            painter.fillRect(self.rect(), QtGui.QColor(30, 30, 30))
        else:
            # Subtle semi-transparent backdrop for normal state
            painter.fillRect(self.rect(), QtGui.QColor(30, 30, 30, 180))
        painter.end()

    def __init__(self, parent, view=None):
        super().__init__(parent)
        self.control_target = view or parent
        main_window = getattr(self.control_target, 'host_window', None) or self.control_target.window()
        self.init_main_controls(main_window=main_window)
        
        # Disable context menu that is inherited from init_main_controls
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        
        self.setStyleSheet('background-color: transparent;')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        # ---------------------------------------------------------------
        # Flat layout: all content goes directly here, no child widget.
        # A plain QVBoxLayout with equal top/bottom stretches guarantees
        # centering regardless of overlay size. No coordinate confusion.
        # ---------------------------------------------------------------
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(6)
        
        # Update banner — reads update.json; hidden automatically if no message
        self._update_banner = UpdateBanner(self)
        layout.addWidget(self._update_banner)
        layout.addSpacing(4)
        
        # Central widget to contain original content for smooth hiding
        self._content_container = QtWidgets.QWidget(self)
        self._content_container.setStyleSheet('background: transparent;')
        self._content_layout = QtWidgets.QVBoxLayout(self._content_container)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(6)
        layout.addWidget(self._content_container)

        font = QtGui.QFont('Open Sans', 10, QtGui.QFont.Weight.Light)
        font_or = QtGui.QFont('Open Sans', 9, QtGui.QFont.Weight.Light)

        self._content_layout.addStretch(1)

        self.drop_icon = DropZoneIcon(self)
        self._content_layout.addWidget(self.drop_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self._content_layout.addSpacing(8)

        self.label = QtWidgets.QLabel('Drag and drop images here', self)
        self.label.setFont(font)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet('color: rgba(180, 180, 180, 0.75); background: transparent;')
        self._content_layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignHCenter)
        self._content_layout.addSpacing(6)

        self.or_label = QtWidgets.QLabel('or', self)
        self.or_label.setFont(font_or)
        self.or_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.or_label.setStyleSheet('color: rgba(120, 120, 120, 0.6); background: transparent;')
        self._content_layout.addWidget(self.or_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self._content_layout.addSpacing(6)

        self.browse_btn = QtWidgets.QPushButton('Browse', self)
        self.browse_btn.setFixedSize(110, 32)
        self.browse_btn.setFont(QtGui.QFont('Open Sans', 10, QtGui.QFont.Weight.Bold))
        self.browse_btn.setStyleSheet('''
            QPushButton { background-color: #3d9fc0; color: white; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #4db8dc; }
            QPushButton:pressed { background-color: #2d7a96; }
        ''')
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.clicked.connect(self._on_browse)
        self._content_layout.addWidget(self.browse_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self._content_layout.addSpacing(6)

        self.or_join_label = QtWidgets.QLabel('or', self)
        self.or_join_label.setFont(font_or)
        self.or_join_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.or_join_label.setStyleSheet('color: rgba(120, 120, 120, 0.6); background: transparent;')
        self._content_layout.addWidget(self.or_join_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self._content_layout.addSpacing(6)

        self.join_btn = QtWidgets.QPushButton('Join Session', self)
        self.join_btn.setFixedSize(130, 32)
        self.join_btn.setFont(QtGui.QFont('Open Sans', 10, QtGui.QFont.Weight.Bold))
        self.join_btn.setStyleSheet('''
            QPushButton { background-color: #53a7a5; color: white; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #65c2c0; }
            QPushButton:pressed { background-color: #3d8180; }
        ''')
        self.join_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.join_btn.clicked.connect(self._on_join_session)
        self._content_layout.addWidget(self.join_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self._content_layout.addStretch(1)

        # Loading view container
        self._loading_container = QtWidgets.QWidget(self)
        self._loading_container.hide()
        self._loading_layout = QtWidgets.QVBoxLayout(self._loading_container)
        
        self.spinner = QtWidgets.QLabel(self)
        self.spinner.setFixedSize(40, 40)
        self.spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spinner.setStyleSheet('''
            background: transparent;
            border: 4px solid #53a7a5;
            border-radius: 20px;
        ''')
        self._loading_layout.addStretch(1)
        self._loading_layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignHCenter)
        self._loading_layout.addSpacing(15)
        
        self.loading_label = QtWidgets.QLabel('Joining session...', self)
        self.loading_label.setFont(QtGui.QFont('Open Sans', 11, QtGui.QFont.Weight.Bold))
        self.loading_label.setStyleSheet('color: #e0e0e0;')
        self._loading_layout.addWidget(self.loading_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self._loading_layout.addStretch(1)
        
        layout.addWidget(self._loading_container)

        # Recent files bar — anchored at the very bottom via resizeEvent
        self.recent_container = RecentFilesContainer(self)
        self.recent_container.file_selected.connect(self._on_recent_selected)
        self.recent_container.browse_requested.connect(self._on_browse_recent)
        self.recent_container.hide()  # hidden by default; shown only when maximized/fullscreen

        # Compatibility
        self.floating_widget = self
        self.content_block = self  # some legacy references may use content_block

        self.update_visibility()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Force the layout to cover the entire widget rect
        if self.layout() is not None:
            self.layout().setGeometry(self.rect())
            self.layout().activate()
        self._anchor_recents()

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(50, self.update_visibility)

    def changeEvent(self, event):
        if event.type() in (QtCore.QEvent.Type.WindowStateChange,
                            QtCore.QEvent.Type.ActivationChange):
            self.update_visibility()
        super().changeEvent(event)

    def _anchor_recents(self):
        """Pin recent_container to the bottom of the overlay with tasteful margins."""
        if not self.recent_container.isVisible():
            return
        ow, oh = self.width(), self.height()
        if ow == 0 or oh == 0:
            return
        rh = self.recent_container.height() or 210
        h_margin = 80   # left/right inset — very premium
        b_margin = 40   # larger gap from bottom
        self.recent_container.setGeometry(
            h_margin, oh - rh - b_margin, ow - 2 * h_margin, rh
        )

    def _on_browse(self):
        self.control_target.on_action_insert_images()

    def _on_browse_recent(self):
        self.control_target.on_action_open()

    def _on_join_session(self):
        self.control_target.on_action_join_session()

    def _on_recent_selected(self, filename):
        self.control_target.open_from_file(filename)

    def update_visibility(self):
        """Show/hide recent files based on window state."""
        # If we are loading, stay centered and ignore the recents bar logic
        if self._loading_container.isVisible():
            if self.layout():
                self.layout().setContentsMargins(40, 40, 40, 40)
            self.recent_container.hide()
            return

        # Robust fullscreen detection
        top_window = self.window()
        is_full = top_window.isFullScreen() if top_window else False
        is_max = top_window.isMaximized() if top_window else False
        
        # Smart visibility: Show in Fullscreen or Maximized, 
        # but ALWAYS hide if the window is too small (e.g. resized to a floating box)
        show_recents = is_full or is_max
        if top_window and top_window.height() < 700:
            show_recents = False

        layout = self.layout()
        files = BeeSettings().get_recent_files(existing_only=True)
        if files and show_recents:
            self.recent_container.show()
            self.recent_container.refresh()
            self._anchor_recents()
            # Push content up by setting a large bottom margin
            # (Height 240 + Bottom offset 40 = 280)
            if layout:
                layout.setContentsMargins(40, 40, 40, 280)
        else:
            self.recent_container.hide()
            if layout:
                layout.setContentsMargins(40, 40, 40, 40)

        self.label.setText('Drag and drop images here')
        self.update()

    def disable_mouse_events(self):
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.browse_btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def enable_mouse_events(self):
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, on=False)
        self.browse_btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, on=False)

    def mousePressEvent(self, event):
        event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        event.accept()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        event.accept()
        super().keyPressEvent(event)

    def show_loading(self, message="Joining session..."):
        self.loading_label.setText(message)
        
        # Ensure the entire overlay is visible and on top
        self.show()
        self.raise_()
        
        self._content_container.hide()
        self.recent_container.hide()
        self._loading_container.show()
        
        # Reset layout margins to ensure centering during loading
        if self.layout():
            self.layout().setContentsMargins(40, 40, 40, 40)
        
        # Hide the status pill if it exists on our parent
        if hasattr(self.parent(), 'collab_status'):
            self.parent().collab_status.hide()

        # Force GUI update to show the loading screen immediately
        QtWidgets.QApplication.processEvents()
        
        # Start a simple rotation animation for the spinner
        if not hasattr(self, '_spinner_angle'):
            self._spinner_angle = 0
            self._spinner_timer = QtCore.QTimer(self)
            self._spinner_timer.timeout.connect(self._rotate_spinner)
        self._spinner_timer.start(16) # ~60fps

    def hide_loading(self):
        if hasattr(self, '_spinner_timer'):
            self._spinner_timer.stop()
        self._loading_container.hide()
        self._content_container.show()
        
        # We don't explicitly show collab_status here because update_visibility
        # or subsequent status_changed signals will handle it correctly.
        
        self.update_visibility()

    def _rotate_spinner(self):
        self._spinner_angle = (self._spinner_angle + 10) % 360
        self.spinner.setStyleSheet(f'''
            background: transparent;
            border: 3px solid rgba(255, 255, 255, 20);
            border-top: 3px solid #53a7a5;
            border-radius: 20px;
            qproperty-text: "";
        ''')
        # We use a transform to rotate the label's "border-top" visually
        # Since style sheets don't support rotation easily, we'll use a QTransform in paintEvent
        # but for now, even a static spinner is better than a flicker.
        # Let's actually use a proper rotation:
        trans = QtGui.QTransform()
        trans.rotate(self._spinner_angle)
        # However, QLabel doesn't have a setTransform. 
        # For maximum WOW, let's just use a simple pulsating opacity if rotation is too complex for 1 tool call
        opacity = 0.3 + (math.sin(self._spinner_angle * math.pi / 180) + 1) * 0.35
        self.spinner.setStyleSheet(f'''
            background: transparent;
            border: 4px solid rgba(83, 167, 165, {opacity});
            border-radius: 20px;
        ''')
