"""Floating drawing toolbar with Pencil, Eraser, Color, and Width controls."""

import logging
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from threecolref import constants

logger = logging.getLogger(__name__)

STROKE_WIDTHS = [1, 2, 3, 4, 5, 8, 12, 16, 24, 32, 48, 64]
QUICK_COLORS = [
    '#FF0000', '#FF7F00', '#FFFF00', '#00FF00', 
    '#0000FF', '#4B0082', '#9400D3', '#FFFFFF', '#000000'
]

class DoodleToolbar(QtWidgets.QWidget):
    """Floating toolbar for drawing tools and properties."""

    tool_changed = QtCore.pyqtSignal(str)   # 'pencil' | 'eraser'
    color_changed = QtCore.pyqtSignal(str)  # hex
    width_changed = QtCore.pyqtSignal(int)
    undo_clicked = QtCore.pyqtSignal()
    redo_clicked = QtCore.pyqtSignal()
    clear_clicked = QtCore.pyqtSignal()
    closed = QtCore.pyqtSignal()

    def __init__(self, parent_view):
        super().__init__(parent_view)
        self.view = parent_view
        self.setObjectName('DoodleToolbar')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        
        self._current_color = '#FF0000'
        self._current_width = 4
        self._drag_pos = None
        
        self._build_ui()
        self._apply_style()
        self.hide()

    def _build_ui(self):
        from threecolref.assets import BeeAssets
        assets = BeeAssets()
        
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        # 0. Drag Handle
        self.drag_handle = QtWidgets.QLabel()
        self.drag_handle.setPixmap(QtGui.QIcon(assets.icon_grip).pixmap(16, 16))
        self.drag_handle.setObjectName("DragHandle")
        self.drag_handle.setFixedSize(20, 36)
        self.drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self.drag_handle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.drag_handle)

        tools_layout = QtWidgets.QHBoxLayout()
        tools_layout.setSpacing(6)
        
        self.select_btn = self._tool_btn(assets.icon_select, 'Selection (V)', checkable=True)
        self.select_btn.clicked.connect(lambda: self.tool_changed.emit('select'))
        tools_layout.addWidget(self.select_btn)

        self.pencil_btn = self._tool_btn(assets.icon_pencil, 'Pencil (Ctrl+Shift+P)', checkable=True)
        self.pencil_btn.setChecked(True)
        self.pencil_btn.clicked.connect(lambda: self.tool_changed.emit('pencil'))
        tools_layout.addWidget(self.pencil_btn)

        self.eraser_btn = self._tool_btn(assets.icon_eraser, 'Eraser (Ctrl+Shift+E)', checkable=True)
        self.eraser_btn.clicked.connect(lambda: self.tool_changed.emit('eraser'))
        tools_layout.addWidget(self.eraser_btn)

        self.rect_btn = self._tool_btn(assets.icon_rect, 'Rectangle', checkable=True)
        self.rect_btn.clicked.connect(lambda: self.tool_changed.emit('rect'))
        tools_layout.addWidget(self.rect_btn)

        self.circle_btn = self._tool_btn(assets.icon_circle, 'Circle', checkable=True)
        self.circle_btn.clicked.connect(lambda: self.tool_changed.emit('circle'))
        tools_layout.addWidget(self.circle_btn)

        self.line_btn = self._tool_btn(assets.icon_line, 'Line', checkable=True)
        self.line_btn.clicked.connect(lambda: self.tool_changed.emit('line'))
        tools_layout.addWidget(self.line_btn)

        self.arrow_btn = self._tool_btn(assets.icon_arrow, 'Arrow', checkable=True)
        self.arrow_btn.clicked.connect(lambda: self.tool_changed.emit('arrow'))
        tools_layout.addWidget(self.arrow_btn)

        self.tool_group = QtWidgets.QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_group.addButton(self.select_btn)
        self.tool_group.addButton(self.pencil_btn)
        self.tool_group.addButton(self.eraser_btn)
        self.tool_group.addButton(self.rect_btn)
        self.tool_group.addButton(self.circle_btn)
        self.tool_group.addButton(self.line_btn)
        self.tool_group.addButton(self.arrow_btn)
        
        layout.addLayout(tools_layout)
        layout.addWidget(self._sep())

        # 2. History Group (Undo/Redo)
        history_layout = QtWidgets.QHBoxLayout()
        history_layout.setSpacing(6)
        
        self.undo_btn = self._tool_btn(assets.icon_undo, 'Undo (Ctrl+Z)')
        self.undo_btn.clicked.connect(self.undo_clicked)
        history_layout.addWidget(self.undo_btn)
        
        self.redo_btn = self._tool_btn(assets.icon_redo, 'Redo (Ctrl+Y)')
        self.redo_btn.clicked.connect(self.redo_clicked)
        history_layout.addWidget(self.redo_btn)
        
        layout.addLayout(history_layout)
        layout.addWidget(self._sep())

        # 3. Color & Width Group
        prop_layout = QtWidgets.QHBoxLayout()
        prop_layout.setSpacing(8)
        
        self.color_preview = QtWidgets.QPushButton()
        self.color_preview.setFixedSize(24, 24)
        self.color_preview.setToolTip('Change Color')
        self.color_preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_color_preview(self._current_color)
        self.color_preview.clicked.connect(self._select_color)
        prop_layout.addWidget(self.color_preview)

        self.width_combo = QtWidgets.QComboBox()
        self.width_combo.setEditable(True)
        self.width_combo.setFixedWidth(55)
        for w in STROKE_WIDTHS:
            self.width_combo.addItem(str(w))
        self.width_combo.setCurrentText(str(self._current_width))
        self.width_combo.currentTextChanged.connect(self._on_width_changed)
        prop_layout.addWidget(self.width_combo)
        
        layout.addLayout(prop_layout)
        layout.addWidget(self._sep())

        # 4. Action Group
        actions_layout = QtWidgets.QHBoxLayout()
        actions_layout.setSpacing(6)
        
        self.clear_btn = self._tool_btn(assets.icon_trash, 'Clear All Doodles')
        self.clear_btn.setObjectName("ActionBtn")
        self.clear_btn.clicked.connect(self.clear_clicked)
        actions_layout.addWidget(self.clear_btn)
        
        self.close_btn = self._tool_btn(assets.icon_close, 'Close Drawing')
        self.close_btn.setObjectName("ActionBtn")
        self.close_btn.clicked.connect(self._on_close_clicked)
        actions_layout.addWidget(self.close_btn)
        
        layout.addLayout(actions_layout)

        self.adjustSize()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()

    def _tool_btn(self, icon_path, tooltip, checkable=False):
        btn = QtWidgets.QPushButton()
        btn.setIcon(QtGui.QIcon(icon_path))
        btn.setIconSize(QtCore.QSize(20, 20))
        btn.setFixedSize(40, 40)
        btn.setCheckable(checkable)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _sep(self):
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet('background-color: rgba(255,255,255,30); margin: 6px 2px;')
        return sep

    def _update_color_preview(self, color_hex):
        self.color_preview.setStyleSheet(f"""
            QPushButton {{
                background-color: {color_hex};
                border: 2px solid rgba(255,255,255,60);
                border-radius: 12px;
            }}
            QPushButton:hover {{
                border-color: rgba(255,255,255,100);
            }}
        """)

    def _select_color(self):
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self._current_color), self, "Select Stroke Color")
        if color.isValid():
            self._current_color = color.name()
            self._update_color_preview(self._current_color)
            self.color_changed.emit(self._current_color)

    def _on_width_changed(self, text):
        try:
            val = int(text)
            if 1 <= val <= 256:
                self._current_width = val
                self.width_changed.emit(val)
        except ValueError:
            pass

    def _apply_style(self):
        self.setStyleSheet("""
            QWidget#DoodleToolbar {
                background-color: rgba(28, 28, 30, 240);
                border: 1px solid rgba(255, 255, 255, 45);
                border-radius: 20px;
            }
            QLabel#DragHandle {
                margin-right: -2px;
                opacity: 0.6;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 10px;
                padding: 4px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 30);
            }
            QPushButton:checked {
                background-color: rgba(0, 122, 255, 60);
                border: 1px solid rgba(0, 122, 255, 100);
            }
            QPushButton#ActionBtn:hover {
                background-color: rgba(255, 59, 48, 40);
            }
            QComboBox {
                background-color: rgba(44, 44, 46, 220);
                color: white;
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 10px;
                padding: 4px 10px;
                font-size: 14px;
                font-weight: 600;
            }
            QComboBox:hover {
                background-color: rgba(58, 58, 60, 220);
                border-color: rgba(255, 255, 255, 50);
            }
            QComboBox::drop-down { border: none; width: 0px; }
            QComboBox QAbstractItemView {
                background-color: #1c1c1e;
                color: #ffffff;
                selection-background-color: #0a84ff;
                border: 1px solid #38383a;
                border-radius: 8px;
            }
        """)

    def _on_close_clicked(self):
        self.hide()
        self.closed.emit()

    def show_at(self, x, y):
        self.move(x, y)
        self.show()
        self.raise_()

    def position_in_view(self):
        """Position toolbar at bottom-center of the view's viewport."""
        try:
            viewport = self.view.viewport() if self.view is not None else None
            if viewport is None:
                self.show()
                self.raise_()
                return

            vw = viewport.width()
            vh = viewport.height()
            if vw <= 0 or vh <= 0:
                self.show()
                self.raise_()
                return

            # If it hasn't been moved by user yet, center it
            if not getattr(self, '_user_moved', False):
                tw = self.width()
                th = self.height()
                self.show_at(int((vw - tw) // 2), int(vh - th - 30))
            else:
                self.show()
                self.raise_()

        except Exception as e:
            logger.error(f'Error positioning toolbar: {e}', exc_info=True)
            self.show()
            self.raise_()

    def move(self, *args, **kwargs):
        # Track if the user moved the toolbar to avoid snapping back on resize/show
        if self._drag_pos:
            self._user_moved = True
        super().move(*args, **kwargs)
