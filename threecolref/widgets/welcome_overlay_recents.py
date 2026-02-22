import os
import time

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from threecolref.config import BeeSettings
from threecolref.utils import format_relative_time
from threecolref.fileio.sql import SQLiteIO
from threecolref.assets import BeeAssets


class RecentFileCard(QtWidgets.QFrame):
    """A vertical card representing a recent file on the welcome screen."""

    clicked = QtCore.pyqtSignal(str)
    removed = QtCore.pyqtSignal(str)

    def __init__(self, filename, parent=None):
        super().__init__(parent)
        self.filename = filename
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(160, 180) # Vertical card

        # Style: Glassmorphism effect, subtle border
        self.setObjectName("RecentFileCard")
        self.setStyleSheet("""
            #RecentFileCard {
                background-color: rgba(45, 45, 45, 100);
                border: 1px solid rgba(255, 255, 255, 10);
                border-radius: 8px;
            }
            #RecentFileCard:hover {
                background-color: rgba(65, 65, 65, 180);
                border: 1px solid rgba(255, 255, 255, 25);
            }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Thumbnail Container
        self.thumb = QtWidgets.QLabel()
        self.thumb.setFixedSize(140, 95)
        self.thumb.setStyleSheet("""
            background-color: rgba(0, 0, 0, 80);
            border-radius: 4px;
            border: 1px solid rgba(255, 255, 255, 5);
        """)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Load real preview or use dynamic fallback
        preview = self._get_preview_pixmap(filename)
        self.thumb.setPixmap(preview)
            
        layout.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignCenter)

        # Info layout
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setSpacing(2)
        info_layout.setContentsMargins(2, 0, 2, 0)

        name = os.path.basename(filename)
        # Strip extension if it's there for a cleaner look
        name_no_ext = os.path.splitext(name)[0]
        self.name_label = QtWidgets.QLabel(name_no_ext)
        self.name_label.setStyleSheet("color: #ffffff; font-weight: 600; font-size: 13px; background: transparent;")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        info_layout.addWidget(self.name_label)

        # Mtime info
        mtime = os.path.getmtime(filename) if os.path.exists(filename) else 0
        time_str = f"Edited {format_relative_time(mtime)}" if mtime else "File missing"
        self.time_label = QtWidgets.QLabel(time_str)
        self.time_label.setStyleSheet("color: rgba(255, 255, 255, 100); font-size: 11px; background: transparent;")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        info_layout.addWidget(self.time_label)

        layout.addLayout(info_layout)
        layout.addStretch()

        # Remove button (X) - hidden by default, shown on hover
        self.remove_btn = QtWidgets.QPushButton("×", self)
        self.remove_btn.setFixedSize(22, 22)
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: rgba(255, 255, 255, 80);
                border-radius: 11px;
                font-size: 18px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(232, 17, 35, 180);
                color: #ffffff;
            }
        """)
        self.remove_btn.hide()
        self.remove_btn.clicked.connect(self._on_remove_clicked)
        
        # Position it top right
        self.remove_btn.move(135, 3)

    def _get_preview_pixmap(self, filename):
        """Try to load a real preview, fallback to a smart placeholder."""
        try:
            thumb_bytes = SQLiteIO.get_thumbnail(filename)
            if thumb_bytes:
                img = QtGui.QImage.fromData(thumb_bytes)
                if not img.isNull():
                    pix = QtGui.QPixmap.fromImage(img)
                    return pix.scaled(self.thumb.size(), 
                                    Qt.AspectRatioMode.KeepAspectRatioByExpanding, 
                                    Qt.TransformationMode.SmoothTransformation)
        except Exception:
            pass

        # If no real images found, return a clean abstract placeholder
        placeholder = QtGui.QPixmap(self.thumb.size())
        placeholder.fill(QtGui.QColor(30, 30, 30))
        painter = QtGui.QPainter(placeholder)
        
        # Draw a subtle gradient
        grad = QtGui.QLinearGradient(0, 0, 0, 95)
        grad.setColorAt(0, QtGui.QColor(40, 40, 40))
        grad.setColorAt(1, QtGui.QColor(25, 25, 25))
        painter.fillRect(placeholder.rect(), grad)
        
        # Render a centered app logo at 50% opacity
        logo_pix = BeeAssets().logo.pixmap(48, 48)
        painter.setOpacity(0.4)
        x = (140 - 48) // 2
        y = (95 - 48) // 2
        painter.drawPixmap(x, y, logo_pix)
        painter.end()
        
        return placeholder

    def _on_remove_clicked(self):
        self.removed.emit(self.filename)

    def enterEvent(self, event):
        self.remove_btn.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.remove_btn.hide()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if clicked on remove button manually because move() positioning might bypass button events
            if self.remove_btn.geometry().contains(event.pos()):
                 return # Let the button handle it
            self.clicked.emit(self.filename)
        super().mousePressEvent(event)


class RecentFilesContainer(QtWidgets.QFrame):
    """The wide, dark container for recent projects on the welcome screen."""

    file_selected = QtCore.pyqtSignal(str)
    browse_requested = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = BeeSettings()
        
        self.setObjectName("RecentFilesContainer")
        self.setFixedHeight(300) # Fixed height for the history box
        self.setStyleSheet("""
            #RecentFilesContainer {
                background-color: rgba(25, 25, 25, 220);
                border: 1px solid rgba(255, 255, 255, 8);
                border-radius: 12px;
            }
        """)
        
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(25, 20, 25, 20)
        main_layout.setSpacing(15)

        # Header
        header = QtWidgets.QLabel("Recent")
        header.setStyleSheet("""
            font-size: 14px; 
            font-weight: 600; 
            color: rgba(255, 255, 255, 180);
            letter-spacing: 0.5px;
        """)
        main_layout.addWidget(header)

        # Horizontal layout for the cards list and the browse button
        content_layout = QtWidgets.QHBoxLayout()
        content_layout.setSpacing(20)

        # Left side: Scroll area for cards
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("background: transparent;")
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.cards_widget = QtWidgets.QWidget()
        self.cards_widget.setStyleSheet("background: transparent;")
        self.cards_layout = QtWidgets.QHBoxLayout(self.cards_widget)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(15)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        self.scroll.setWidget(self.cards_widget)
        content_layout.addWidget(self.scroll, 1)

        # Subtle separator
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        line.setStyleSheet("background-color: rgba(255, 255, 255, 12); width: 1px; margin: 15px 0;")
        content_layout.addWidget(line)

        # Right side: Browse button (Styled to match screenshot)
        self.browse_btn = QtWidgets.QPushButton("Browse")
        self.browse_btn.setFixedSize(100, 36)
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #3d9fc0;
                color: #ffffff;
                border-radius: 6px;
                font-weight: 600;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background-color: #4db8dc;
            }
            QPushButton:pressed {
                background-color: #2d7a96;
            }
        """)
        self.browse_btn.clicked.connect(self.browse_requested.emit)
        content_layout.addWidget(self.browse_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        main_layout.addLayout(content_layout)

        self.refresh()

    def refresh(self):
        """Rebuild the list of recent file cards."""
        # Clear existing
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        files = self.settings.get_recent_files(existing_only=True)
        if not files:
            self.hide()
            return

        self.show()
        for filename in files:
            card = RecentFileCard(filename)
            card.clicked.connect(self.file_selected.emit)
            card.removed.connect(self._on_file_removed)
            self.cards_layout.addWidget(card)
        
        # Ensure scroll area works
        self.cards_widget.adjustSize()

    def _on_file_removed(self, filename):
        self.settings.remove_recent_file(filename)
        self.refresh()
