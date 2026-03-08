import logging

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)

class _IosDialogBase(QtWidgets.QDialog):
    """Base class for iOS-style frameless, rounded dialogs."""
    def __init__(self, parent=None, title=""):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(300)
        
        # Main layout
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Container frame for rounded corners and styling
        self.container = QtWidgets.QFrame(self)
        self.container.setObjectName("iosContainer")
        self.container.setStyleSheet("""
            #iosContainer {
                background-color: rgba(45, 45, 45, 245);
                border-radius: 14px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
        """)
        self.container_layout = QtWidgets.QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 20, 0, 0)
        self.container_layout.setSpacing(15)
        self.main_layout.addWidget(self.container)
        
        # Title
        self.title_label = QtWidgets.QLabel(title, self.container)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 16px; font-weight: bold; color: white;")
        self.container_layout.addWidget(self.title_label)
        
        # Content area (to be populated by subclasses)
        self.content_layout = QtWidgets.QVBoxLayout()
        self.content_layout.setContentsMargins(20, 0, 20, 5)
        self.container_layout.addLayout(self.content_layout)
        
        # Button area
        self.button_layout = QtWidgets.QHBoxLayout()
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self.button_layout.setSpacing(0)
        
        # Add a top border to buttons area
        self.btn_container = QtWidgets.QFrame(self.container)
        self.btn_container.setStyleSheet("border-top: 1px solid rgba(255, 255, 255, 0.1);")
        self.btn_container.setLayout(self.button_layout)
        self.container_layout.addWidget(self.btn_container)

    def _create_button(self, text, is_primary=False, is_destructive=False):
        btn = QtWidgets.QPushButton(text)
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        if is_destructive:
            color = "#FF3B30"
        elif is_primary:
            color = "#0A84FF"
        else:
            color = "#0A84FF"
            
        weight = "bold" if is_primary else "normal"
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {color};
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                font-size: 16px;
                font-weight: {weight};
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.05);
            }}
            QPushButton:pressed {{
                background-color: rgba(255, 255, 255, 0.1);
            }}
        """)
        return btn


class BeeIosInputDialog(_IosDialogBase):
    """An iOS-style replacement for QInputDialog.getText."""
    def __init__(self, parent=None, title="", label=""):
        super().__init__(parent, title)
        
        # Label
        if label:
            desc = QtWidgets.QLabel(label, self.container)
            desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc.setWordWrap(True)
            desc.setStyleSheet("font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; color: rgba(255, 255, 255, 0.8);")
            self.content_layout.addWidget(desc)
            
        # Input Field
        self.line_edit = QtWidgets.QLineEdit(self.container)
        self.line_edit.setFixedHeight(30)
        self.line_edit.setStyleSheet("""
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 6px;
                color: white;
                padding: 0 8px;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #0A84FF;
                background-color: rgba(255, 255, 255, 0.15);
            }
        """)
        self.content_layout.addWidget(self.line_edit)
        self.content_layout.addSpacing(10)
        
        # Buttons
        self.cancel_btn = self._create_button("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.button_layout.addWidget(self.cancel_btn)
        
        # Separator line
        sep = QtWidgets.QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); border: none;")
        self.button_layout.addWidget(sep)
        
        self.ok_btn = self._create_button("OK", is_primary=True)
        self.ok_btn.clicked.connect(self.accept)
        self.button_layout.addWidget(self.ok_btn)

    @classmethod
    def get_text(cls, parent, title, label):
        dialog = cls(parent, title, label)
        # Position roughly centered on parent if possible
        if parent:
            geom = parent.geometry()
            x = geom.x() + (geom.width() - dialog.width()) // 2
            y = geom.y() + (geom.height() - dialog.height()) // 2
            dialog.move(x, y)
            
        result = dialog.exec()
        return dialog.line_edit.text(), result == QtWidgets.QDialog.DialogCode.Accepted


class BeeIosMessageDialog(_IosDialogBase):
    """An iOS-style replacement for QMessageBox."""
    def __init__(self, parent=None, title="", text="", buttons=None):
        super().__init__(parent, title)
        
        if not buttons:
            buttons = ["OK"]
            
        # Content text
        if text:
            desc = QtWidgets.QLabel(text, self.container)
            desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc.setWordWrap(True)
            desc.setStyleSheet("font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; color: rgba(255, 255, 255, 0.8);")
            self.content_layout.addWidget(desc)
            self.content_layout.addSpacing(10)
            
        self.clicked_button = None
        
        # Create action buttons
        for i, btn_text in enumerate(buttons):
            if i > 0:
                sep = QtWidgets.QFrame()
                sep.setFixedWidth(1)
                sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); border: none;")
                self.button_layout.addWidget(sep)
                
            is_primary = (i == len(buttons) - 1)
            btn = self._create_button(btn_text, is_primary=is_primary)
            
            # Use lambda default arg capture to bind current btn_text
            btn.clicked.connect(lambda checked=False, t=btn_text: self._on_button_clicked(t))
            self.button_layout.addWidget(btn)

    def _on_button_clicked(self, text):
        self.clicked_button = text
        self.accept()

    @classmethod
    def show_message(cls, parent, title, text, buttons=None):
        dialog = cls(parent, title, text, buttons)
        if parent:
            geom = parent.geometry()
            x = geom.x() + (geom.width() - dialog.width()) // 2
            y = geom.y() + (geom.height() - dialog.height()) // 2
            dialog.move(x, y)
        dialog.exec()
        return dialog.clicked_button
class BeeIosProgressDialog(_IosDialogBase):
    """An iOS-style replacement for QProgressDialog."""
    canceled = QtCore.pyqtSignal()
    
    def __init__(self, label, parent=None, title="Progress"):
        super().__init__(parent, title)
        self.setMinimumWidth(320)
        
        # Status Label
        self.label = QtWidgets.QLabel(label, self.container)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; color: rgba(255, 255, 255, 0.85);")
        self.content_layout.addWidget(self.label)
        self.content_layout.addSpacing(12)
        
        # Progress Bar and Percentage
        prog_container = QtWidgets.QHBoxLayout()
        prog_container.setSpacing(10)
        
        self.progress_bar = QtWidgets.QProgressBar(self.container)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: rgba(255, 255, 255, 0.1);
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #AF52DE;
                border-radius: 3px;
            }
        """)
        prog_container.addWidget(self.progress_bar)
        
        self.percent_label = QtWidgets.QLabel("0%", self.container)
        self.percent_label.setFixedWidth(45)
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.percent_label.setStyleSheet("font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 12px; color: rgba(255, 255, 255, 0.7);")
        prog_container.addWidget(self.percent_label)
        
        self.content_layout.addLayout(prog_container)
        self.content_layout.addSpacing(15)
        
        # Buttons
        self.cancel_btn = self._create_button("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.button_layout.addWidget(self.cancel_btn)
        
        # Center and Show
        if parent:
            # We use parent.window().geometry() to get the actual main window pos
            parent_window = parent.window()
            geom = parent_window.geometry()
            self.adjustSize() # Ensure we have correct width/height before moving
            x = geom.x() + (geom.width() - self.width()) // 2
            y = geom.y() + (geom.height() - self.height()) // 2
            self.move(x, y)
            
        self.show()
        self.raise_()
        
        # For compatibility with workers expecting direct calls
        self.canceled_signal_emitted = False

    def _on_cancel(self):
        self.canceled.emit()
        self.reject()

    def setValue(self, value):
        self.progress_bar.setValue(value)
        max_val = self.progress_bar.maximum()
        if max_val > 0:
            percent = int((value / max_val) * 100)
            self.percent_label.setText(f"{percent}%")
        else:
            self.percent_label.setText("100%" if value >= 0 else "0%")
        # Force UI update
        QtWidgets.QApplication.processEvents()

    def setMaximum(self, value):
        self.progress_bar.setMaximum(value)

    def maximum(self):
        return self.progress_bar.maximum()

    def reset(self):
        self.progress_bar.reset()
        self.percent_label.setText("0%")
        self.hide()
class BeeIosSessionCodeDialog(_IosDialogBase):
    """An iOS-style replacement for the Session Code popup."""
    def __init__(self, parent=None, code=""):
        super().__init__(parent, "Session Code")
        self.code = code
        self.setMinimumWidth(320)
        
        # Description
        desc = QtWidgets.QLabel("Share this code with others so they can join:", self.container)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; color: rgba(255, 255, 255, 0.8);")
        self.content_layout.addWidget(desc)
        self.content_layout.addSpacing(15)
        
        # Code Display
        self.code_label = QtWidgets.QLabel(code, self.container)
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_label.setStyleSheet("font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 28px; font-weight: bold; color: white; letter-spacing: 2px;")
        self.content_layout.addWidget(self.code_label)
        self.content_layout.addSpacing(15)
        
        # Help text
        help_text = QtWidgets.QLabel("They can join via Collaborate → Join Session.", self.container)
        help_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        help_text.setStyleSheet("font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 12px; color: rgba(255, 255, 255, 0.6);")
        self.content_layout.addWidget(help_text)
        self.content_layout.addSpacing(10)
        
        # Buttons
        self.copy_btn = self._create_button("Copy & Close", is_primary=True)
        self.copy_btn.clicked.connect(self._on_copy_clicked)
        self.button_layout.addWidget(self.copy_btn)
        
        # Separator line
        sep = QtWidgets.QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); border: none;")
        self.button_layout.addWidget(sep)
        
        self.close_btn = self._create_button("Close")
        self.close_btn.clicked.connect(self.reject)
        self.button_layout.addWidget(self.close_btn)

    def _on_copy_clicked(self):
        QtWidgets.QApplication.clipboard().setText(self.code)
        self.accept()

    @classmethod
    def show_session_code(cls, parent, code):
        dialog = cls(parent, code)
        if parent:
            geom = parent.geometry()
            x = geom.x() + (geom.width() - dialog.width()) // 2
            y = geom.y() + (geom.height() - dialog.height()) // 2
            dialog.move(x, y)
        dialog.exec()


class BeeIosUserListDialog(_IosDialogBase):
    """An iOS-style dialog showing connected users with kick capability."""
    def __init__(self, parent, collab_manager):
        super().__init__(parent, "Participants")
        self.collab = collab_manager
        self.setMinimumWidth(340)
        
        # Add Close Button (top-right X)
        self.close_btn = QtWidgets.QPushButton("✕", self.container)
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 15px;
                color: rgba(255, 255, 255, 0.6);
                font-size: 16px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
                color: white;
            }
        """)
        self.close_btn.clicked.connect(self.accept)
        # Position in top right
        self.close_btn.move(340 - 45, 12)
        
        # Pull user data
        peers = self.collab.get_connected_users()
        is_hosting = self.collab.is_hosting
        
        # User List Scroll Area
        self.scroll = QtWidgets.QScrollArea(self.container)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        
        self.list_container = QtWidgets.QWidget()
        self.list_container.setStyleSheet("background: transparent;")
        self.list_layout = QtWidgets.QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(15, 5, 15, 20)
        self.list_layout.setSpacing(10)
        
        self.list_layout.addStretch()
        self.scroll.setWidget(self.list_container)
        self.content_layout.addWidget(self.scroll)
        
        # Connect signals for reactive updates
        self.collab.user_count_changed.connect(lambda n: self.refresh())
        self.collab.remote_user_left.connect(lambda uid: self.refresh())

        # Perform initial build
        self.refresh()

        # Remove the bottom button container from base class since we use top X
        self.btn_container.hide()

    def refresh(self):
        """Clean and rebuild the list based on current manager state."""
        # Clear EVERYTHING
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 1. Add Session Code Section at the top
        code = self.collab.session_code
        if code:
            self._add_session_code_row(code)
            # Separator
            sep = QtWidgets.QFrame()
            sep.setFixedHeight(1)
            sep.setStyleSheet("background: rgba(255, 255, 255, 0.08); margin: 5px 10px;")
            self.list_layout.addWidget(sep)
        
        # 2. Re-add "You"
        is_hosting = self.collab.is_hosting
        my_name = f"{self.collab.username} (You)"
        if is_hosting:
            my_name = f"{self.collab.username} (You, Host)"
        self._add_user_row(my_name, is_self=True)
        
        # 3. Re-add peers
        peers = self.collab.get_connected_users()
        for p in peers:
            uid = p.get('user_id', 'Unknown')
            name = p.get('username') or uid
            self._add_user_row(name, user_id=uid, can_kick=is_hosting)
            
        # Add new stretch at the end
        self.list_layout.addStretch()

    def _add_session_code_row(self, code):
        """Add a row showing the session code with a copy button."""
        row = QtWidgets.QFrame()
        row.setFixedHeight(60)
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(15, 0, 15, 0)
        
        label = QtWidgets.QLabel("SESSION CODE")
        label.setStyleSheet("color: rgba(255, 255, 255, 0.4); font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        
        code_label = QtWidgets.QLabel(code)
        code_label.setStyleSheet("color: #FFD60A; font-family: monospace; font-size: 18px; font-weight: bold;")
        
        v_layout = QtWidgets.QVBoxLayout()
        v_layout.setSpacing(2)
        v_layout.addWidget(label)
        v_layout.addWidget(code_label)
        row_layout.addLayout(v_layout)
        row_layout.addStretch()
        
        copy_btn = QtWidgets.QPushButton("Copy")
        copy_btn.setFixedSize(60, 30)
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                color: white;
                border-radius: 15px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.15);
            }
        """)
        
        def copy_code():
            QtWidgets.QApplication.clipboard().setText(code)
            copy_btn.setText("Copied!")
            copy_btn.setStyleSheet(copy_btn.styleSheet().replace("rgba(255, 255, 255, 0.08)", "#32D74B"))
            QtCore.QTimer.singleShot(2000, lambda: [
                copy_btn.setText("Copy"),
                copy_btn.setStyleSheet(copy_btn.styleSheet().replace("#32D74B", "rgba(255, 255, 255, 0.08)"))
            ])
            
        copy_btn.clicked.connect(copy_code)
        row_layout.addWidget(copy_btn)
        self.list_layout.addWidget(row)

    def _add_user_row(self, name, user_id=None, is_self=False, can_kick=False):
        row = QtWidgets.QFrame()
        row.setObjectName("row")
        row.setFixedHeight(54)
        # Use specific ID selector to avoid CSS inheritance to child labels/buttons
        row.setStyleSheet("""
            #row {
                background-color: rgba(255, 255, 255, 0.04);
                border-radius: 12px;
                border: none;
            }
        """)
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(14, 0, 14, 0)
        row_layout.setSpacing(12)
        
        # User Icon / Initial
        icon = QtWidgets.QLabel(name[0].upper() if name else "?")
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        color = "#0A84FF" if is_self else "#AF52DE"
        icon.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                border-radius: 16px;
                color: white;
                font-weight: bold;
                font-size: 15px;
                border: none;
            }}
        """)
        row_layout.addWidget(icon)
        
        # Name
        name_label = QtWidgets.QLabel(name)
        # Explicit transparent background to stop "boxy" inheritance
        name_label.setStyleSheet("background: transparent; color: white; font-size: 15px; font-weight: 500; border: none;")
        row_layout.addWidget(name_label)
        row_layout.addStretch()
        
        # Kick Button / Badge
        if can_kick and not is_self:
            kick_btn = QtWidgets.QPushButton("✕")
            kick_btn.setFixedSize(26, 26)
            kick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            kick_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 69, 58, 0.15);
                    border-radius: 13px;
                    color: #FF453A;
                    font-size: 14px;
                    font-weight: bold;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #FF453A;
                    color: white;
                }
            """)
            kick_btn.clicked.connect(lambda: self._on_kick_clicked(user_id, name))
            row_layout.addWidget(kick_btn)
        elif is_self:
            status = QtWidgets.QLabel("Me")
            status.setStyleSheet("background: transparent; color: rgba(255, 255, 255, 0.3); font-size: 13px; border: none;")
            row_layout.addWidget(status)
            
        self.list_layout.addWidget(row)

    def _on_kick_clicked(self, user_id, name):
        from .ios_dialogs import BeeIosMessageDialog
        msg = f"Disconnect '{name}'?"
        res = BeeIosMessageDialog.show_message(self, "Remove User", msg, buttons=["Cancel", "Remove"])
        if res == "Remove":
            self.collab.kick_user(user_id)
            # The dialog now refreshes automatically via the user_count_changed signal 
            # emitted by the manager's proactive removal.

    @classmethod
    def show_user_list(cls, parent, collab_manager):
        dialog = cls(parent, collab_manager)
        if parent:
            # We use parent.window().geometry() to get reliable window pos
            p_win = parent.window()
            geom = p_win.geometry()
            x = geom.x() + (geom.width() - 340) // 2
            y = geom.y() + (geom.height() - dialog.sizeHint().height()) // 2
            dialog.move(x, y)
        dialog.exec()
