"""Floating rich-text formatting toolbar shown when editing a BeeTextItem."""

import logging
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from threecolref import constants

logger = logging.getLogger(__name__)

FONT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 64, 72, 96]


class TextFormatToolbar(QtWidgets.QWidget):
    """Figma-style floating toolbar for rich-text formatting."""

    def __init__(self, parent_view):
        super().__init__(parent_view)
        self.view = parent_view
        self._item = None
        self._updating = False  # Prevent signal loops

        self.setObjectName('TextFormatToolbar')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)

        self._build_ui()
        self._apply_style()
        self.hide()

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # Font family
        self.font_combo = QtWidgets.QFontComboBox()
        self.font_combo.setMaximumWidth(160)
        self.font_combo.currentFontChanged.connect(self._on_font_family)
        layout.addWidget(self.font_combo)

        layout.addWidget(self._sep())

        # Font size
        self.size_combo = QtWidgets.QComboBox()
        self.size_combo.setEditable(True)
        self.size_combo.setMaximumWidth(56)
        for s in FONT_SIZES:
            self.size_combo.addItem(str(s))
        self.size_combo.setCurrentText('16')
        self.size_combo.currentTextChanged.connect(self._on_font_size)
        layout.addWidget(self.size_combo)

        layout.addWidget(self._sep())

        # Bold / Italic / Underline / Strikethrough
        self.bold_btn = self._tool_btn('B', 'Bold (Ctrl+B)', checkable=True)
        self.bold_btn.setStyleSheet(self.bold_btn.styleSheet() + 'font-weight:bold;')
        self.bold_btn.toggled.connect(self._on_bold)
        layout.addWidget(self.bold_btn)

        self.italic_btn = self._tool_btn('I', 'Italic (Ctrl+I)', checkable=True)
        self.italic_btn.setStyleSheet(self.italic_btn.styleSheet() + 'font-style:italic;')
        self.italic_btn.toggled.connect(self._on_italic)
        layout.addWidget(self.italic_btn)

        self.underline_btn = self._tool_btn('U', 'Underline (Ctrl+U)', checkable=True)
        self.underline_btn.setStyleSheet(self.underline_btn.styleSheet() + 'text-decoration:underline;')
        self.underline_btn.toggled.connect(self._on_underline)
        layout.addWidget(self.underline_btn)

        self.strike_btn = self._tool_btn('S', 'Strikethrough', checkable=True)
        self.strike_btn.setStyleSheet(self.strike_btn.styleSheet() + 'text-decoration:line-through;')
        self.strike_btn.toggled.connect(self._on_strike)
        layout.addWidget(self.strike_btn)

        layout.addWidget(self._sep())

        # Text color
        self.color_btn = QtWidgets.QPushButton()
        self.color_btn.setFixedSize(26, 26)
        self.color_btn.setToolTip('Text Color')
        self.color_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._set_color_btn_style(QtGui.QColor(*constants.COLORS['Scene:Text']))
        self.color_btn.clicked.connect(self._on_color)
        layout.addWidget(self.color_btn)

        layout.addWidget(self._sep())

        # Alignment
        self.align_left = self._tool_btn('≡', 'Align Left', checkable=True)
        self.align_left.toggled.connect(lambda c: c and self._on_align(Qt.AlignmentFlag.AlignLeft))
        layout.addWidget(self.align_left)

        self.align_center = self._tool_btn('≡', 'Align Center', checkable=True)
        self.align_center.toggled.connect(lambda c: c and self._on_align(Qt.AlignmentFlag.AlignCenter))
        layout.addWidget(self.align_center)

        self.align_right = self._tool_btn('≡', 'Align Right', checkable=True)
        self.align_right.toggled.connect(lambda c: c and self._on_align(Qt.AlignmentFlag.AlignRight))
        layout.addWidget(self.align_right)

        self.align_group = QtWidgets.QButtonGroup(self)
        self.align_group.setExclusive(True)
        self.align_group.addButton(self.align_left)
        self.align_group.addButton(self.align_center)
        self.align_group.addButton(self.align_right)

        self.adjustSize()

    # ── Helpers ──────────────────────────────────────────────────────

    def _tool_btn(self, label, tooltip, checkable=False):
        btn = QtWidgets.QPushButton(label)
        btn.setFixedSize(26, 26)
        btn.setCheckable(checkable)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.ArrowCursor)
        return btn

    def _sep(self):
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet('color: rgba(255,255,255,20);')
        return sep

    def _set_color_btn_style(self, color):
        self.color_btn.setStyleSheet(
            f'background-color: {color.name()}; border: 1px solid rgba(255,255,255,40); border-radius: 4px;')
        self._current_color = color

    def _apply_style(self):
        self.setStyleSheet("""
            QWidget#TextFormatToolbar {
                background-color: rgba(35, 35, 35, 235);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 8px;
            }
            QPushButton {
                background-color: transparent;
                color: #e0e0e0;
                border: 1px solid transparent;
                border-radius: 4px;
                font-size: 13px;
                font-family: 'Segoe UI', 'SF Pro Display', sans-serif;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 25);
            }
            QPushButton:checked {
                background-color: rgba(255, 255, 255, 40);
                color: white;
            }
            QFontComboBox, QComboBox {
                background-color: rgba(50, 50, 50, 200);
                color: #e0e0e0;
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 4px;
                padding: 2px 4px;
                font-size: 12px;
            }
            QFontComboBox::drop-down, QComboBox::drop-down {
                border: none;
                width: 16px;
            }
        """)

    # ── Show / hide ─────────────────────────────────────────────────

    def show_for_item(self, item):
        """Attach to a BeeTextItem and show the toolbar."""
        self._item = item
        item.document().contentsChanged.connect(self._on_cursor_moved)
        self._sync_from_cursor()
        self._position_above_item()
        self.show()
        self.raise_()

    def hide_from_item(self):
        if self._item:
            try:
                self._item.document().contentsChanged.disconnect(self._on_cursor_moved)
            except (TypeError, RuntimeError):
                pass
        self._item = None
        self.hide()

    def _position_above_item(self):
        """Position toolbar centered above the text item in viewport coords."""
        if not self._item:
            return
        # Map item's top-center to view coords
        item_rect = self._item.boundingRect()
        scene_top = self._item.mapToScene(
            QtCore.QPointF(item_rect.width() / 2, 0))
        view_pos = self.view.mapFromScene(scene_top)

        x = max(4, view_pos.x() - self.width() // 2)
        y = max(4, view_pos.y() - self.height() - 8)

        # Clamp to viewport
        vw = self.view.viewport().width()
        if x + self.width() > vw - 4:
            x = vw - self.width() - 4
        self.move(int(x), int(y))

    # ── Sync toolbar state from cursor ──────────────────────────────

    def _on_cursor_moved(self):
        if not self._updating:
            self._sync_from_cursor()

    def _sync_from_cursor(self):
        if not self._item:
            return
        self._updating = True
        cursor = self._item.textCursor()
        fmt = cursor.charFormat()
        bfmt = cursor.blockFormat()

        self.bold_btn.setChecked(fmt.fontWeight() == QtGui.QFont.Weight.Bold)
        self.italic_btn.setChecked(fmt.fontItalic())
        self.underline_btn.setChecked(fmt.fontUnderline())
        self.strike_btn.setChecked(fmt.fontStrikeOut())

        font = fmt.font()
        self.font_combo.setCurrentFont(font)
        size = int(font.pointSizeF()) if font.pointSizeF() > 0 else 16
        self.size_combo.setCurrentText(str(size))

        align = bfmt.alignment()
        if align == Qt.AlignmentFlag.AlignCenter or align == Qt.AlignmentFlag.AlignHCenter:
            self.align_center.setChecked(True)
        elif align == Qt.AlignmentFlag.AlignRight:
            self.align_right.setChecked(True)
        else:
            self.align_left.setChecked(True)

        color = fmt.foreground().color()
        if color.isValid():
            self._set_color_btn_style(color)

        self._updating = False

    # ── Formatting actions ──────────────────────────────────────────

    def _apply_char_format(self, fmt):
        if not self._item or self._updating:
            return
        cursor = self._item.textCursor()
        if not cursor.hasSelection():
            cursor.select(QtGui.QTextCursor.SelectionType.Document)
        cursor.mergeCharFormat(fmt)
        self._item.setTextCursor(cursor)

    def _on_bold(self, checked):
        fmt = QtGui.QTextCharFormat()
        fmt.setFontWeight(QtGui.QFont.Weight.Bold if checked else QtGui.QFont.Weight.Normal)
        self._apply_char_format(fmt)

    def _on_italic(self, checked):
        fmt = QtGui.QTextCharFormat()
        fmt.setFontItalic(checked)
        self._apply_char_format(fmt)

    def _on_underline(self, checked):
        fmt = QtGui.QTextCharFormat()
        fmt.setFontUnderline(checked)
        self._apply_char_format(fmt)

    def _on_strike(self, checked):
        fmt = QtGui.QTextCharFormat()
        fmt.setFontStrikeOut(checked)
        self._apply_char_format(fmt)

    def _on_font_family(self, font):
        if self._updating:
            return
        fmt = QtGui.QTextCharFormat()
        fmt.setFontFamilies([font.family()])
        self._apply_char_format(fmt)

    def _on_font_size(self, text):
        if self._updating:
            return
        try:
            size = float(text)
            if size < 1 or size > 500:
                return
        except ValueError:
            return
        fmt = QtGui.QTextCharFormat()
        fmt.setFontPointSize(size)
        self._apply_char_format(fmt)

    def _on_color(self):
        if not self._item:
            return
        color = QtWidgets.QColorDialog.getColor(
            self._current_color, self, 'Text Color')
        if color.isValid():
            self._set_color_btn_style(color)
            fmt = QtGui.QTextCharFormat()
            fmt.setForeground(QtGui.QBrush(color))
            self._apply_char_format(fmt)

    def _on_align(self, alignment):
        if not self._item or self._updating:
            return
        cursor = self._item.textCursor()
        bfmt = QtGui.QTextBlockFormat()
        bfmt.setAlignment(alignment)
        cursor.mergeBlockFormat(bfmt)
        self._item.setTextCursor(cursor)
