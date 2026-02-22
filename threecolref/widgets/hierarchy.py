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
import os

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)

THUMB_SIZE = 22   # px — icon thumbnail size in list
DETAIL_THUMB = 80 # px — thumbnail in detail panel


_PANEL_STYLE = """
    QFrame {
        background-color: rgba(28, 28, 28, 245);
        border: 1px solid rgba(255, 255, 255, 22);
        border-radius: 12px;
    }
"""
_LIST_STYLE = """
    QListWidget {
        background-color: transparent;
        border: none;
        outline: none;
        color: #cccccc;
        font-family: 'Segoe UI', 'Inter', sans-serif;
        font-size: 12px;
    }
    QListWidget::item {
        padding: 5px 6px;
        border-radius: 6px;
        margin: 1px 0;
    }
    QListWidget::item:hover {
        background-color: rgba(255, 255, 255, 10);
        color: white;
    }
    QListWidget::item:selected {
        background-color: rgba(0, 160, 240, 80);
        color: white;
    }
"""
_LABEL_STYLE = "background: transparent; border: none; color: {}; font-family: 'Segoe UI','Inter',sans-serif;"


class HierarchyOverlay(QtWidgets.QWidget):
    """A floating panel showing all scene items — inspired by PureRef."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.scene = view.scene

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint)

        # Per-item custom labels: id(scene_item) -> str
        self._custom_labels: dict[int, str] = {}
        self._renaming = False
        self._internal_sync = False

        # Debounce timer — prevents constant rebuild on every scene.changed frame
        self._sync_timer = QtCore.QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(200)          # ms
        self._sync_timer.timeout.connect(self._do_sync_from_scene)

        self._setup_ui()

        # Connect signals
        self.scene.changed.connect(self._schedule_sync)
        self.scene.selectionChanged.connect(self._sync_selection_from_scene)

        self._do_sync_from_scene()

    # ------------------------------------------------------------------ UI --

    def _setup_ui(self):
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # ---- Left: list panel ----
        self.list_frame = QtWidgets.QFrame()
        self.list_frame.setStyleSheet(_PANEL_STYLE)
        self.list_frame.setMinimumWidth(220)
        list_layout = QtWidgets.QVBoxLayout(self.list_frame)
        list_layout.setContentsMargins(10, 10, 10, 10)
        list_layout.setSpacing(6)

        self.header = QtWidgets.QLabel("Hierarchy")
        self.header.setStyleSheet("font-size: 13px; font-weight: bold; color: white;"
                             + _LABEL_STYLE.format('white'))
        list_layout.addWidget(self.header)

        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setStyleSheet("border: none; background: rgba(255,255,255,18); max-height: 1px;")
        list_layout.addWidget(line)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setIconSize(QtCore.QSize(THUMB_SIZE, THUMB_SIZE))
        self.list_widget.setStyleSheet(_LIST_STYLE)
        self.list_widget.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self._on_list_selection_changed)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_list_context_menu)
        list_layout.addWidget(self.list_widget)

        outer.addWidget(self.list_frame)

        # ---- Right: detail panel ----
        self.detail_frame = QtWidgets.QFrame()
        self.detail_frame.setStyleSheet(_PANEL_STYLE)
        self.detail_frame.setFixedWidth(200)
        detail_layout = QtWidgets.QVBoxLayout(self.detail_frame)
        detail_layout.setContentsMargins(12, 12, 12, 12)
        detail_layout.setSpacing(8)
        detail_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.detail_thumb = QtWidgets.QLabel()
        self.detail_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_thumb.setFixedSize(DETAIL_THUMB + 16, DETAIL_THUMB + 16)
        self.detail_thumb.setStyleSheet(
            "border: 1px solid rgba(255,255,255,20); border-radius: 6px; background: rgba(0,0,0,40);")
        detail_layout.addWidget(self.detail_thumb, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.detail_name = QtWidgets.QLabel()
        self.detail_name.setStyleSheet("font-size: 12px; font-weight: bold; color: white;"
                                       + _LABEL_STYLE.format('white'))
        self.detail_name.setWordWrap(True)
        detail_layout.addWidget(self.detail_name)

        self.detail_info = QtWidgets.QLabel()
        self.detail_info.setStyleSheet("font-size: 11px; color: #999999; line-height: 160%;"
                                       + _LABEL_STYLE.format('#999999'))
        self.detail_info.setWordWrap(True)
        detail_layout.addWidget(self.detail_info)

        detail_layout.addStretch()
        self.detail_frame.hide()
        outer.addWidget(self.detail_frame)

        # Drag state
        self._dragging = False
        self._drag_start_global = QtCore.QPoint()
        self._panel_start_pos = QtCore.QPoint()
        self._user_moved = False

        self.resize(440, 420)

    # ----------------------------------------------------------- Drag panel --

    def mousePressEvent(self, event):
        # Only handle dragging if clicked outside children or on the header
        child = self.childAt(event.pos())
        if child in (self, self.list_frame, self.detail_frame, self.header):
            if event.button() == Qt.MouseButton.LeftButton:
                self._dragging = True
                self._drag_start_global = event.globalPosition().toPoint()
                self._panel_start_pos = self.pos()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            delta = event.globalPosition().toPoint() - self._drag_start_global
            self.move(self._panel_start_pos + delta)
            self._user_moved = True
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)

    # ------------------------------------------------- Helpers for items --

    def _is_user_item(self, item) -> bool:
        return hasattr(item, 'is_image') or hasattr(item, 'is_editable')

    def _get_label(self, item) -> str:
        iid = id(item)
        if iid in self._custom_labels:
            return self._custom_labels[iid]
        cls = item.__class__.__name__
        if cls == 'BeePixmapItem':
            return os.path.splitext(os.path.basename(item.filename))[0] if item.filename else 'Pasted Image'
        if cls == 'BeeVideoItem':
            fn = getattr(item, 'filename', None)
            return os.path.splitext(os.path.basename(fn))[0] if fn else 'Video'
        if cls == 'BeeTextItem':
            txt = item.toPlainText()
            return ('Text: ' + txt[:22] + '…') if len(txt) > 22 else f'Text: {txt}'
        return cls

    def _get_thumbnail(self, item) -> QtGui.QIcon:
        if item.__class__.__name__ == 'BeePixmapItem':
            pm = item.pixmap()
            if not pm.isNull():
                scaled = pm.scaled(
                    THUMB_SIZE, THUMB_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                return QtGui.QIcon(scaled)
        return QtGui.QIcon()

    # ------------------------------------------------- Scene → list sync --

    def _schedule_sync(self, _region=None):
        """Debounce: restart the timer each time scene.changed fires."""
        if not self._internal_sync and not self._renaming:
            self._sync_timer.start()

    def _do_sync_from_scene(self):
        """Rebuild the list."""
        if self._renaming or self._internal_sync:
            return
            
        self.list_widget.blockSignals(True)

        # Remember selected items by their scene object ID
        selected_ids = {
            self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list_widget.count())
            if self.list_widget.item(i).isSelected()
        }

        self.list_widget.clear()

        user_items = sorted(
            [i for i in self.scene.items() if self._is_user_item(i)],
            key=lambda i: -i.zValue())

        for item in user_items:
            label = self._get_label(item)
            icon  = self._get_thumbnail(item)
            list_item = QtWidgets.QListWidgetItem(icon, label)
            list_item.setData(Qt.ItemDataRole.UserRole, id(item))

            if id(item) in selected_ids or item.isSelected():
                list_item.setSelected(True)

            self.list_widget.addItem(list_item)

        self.list_widget.blockSignals(False)
        self._sync_selection_from_scene() # Ensure detail panel updates

    def _sync_selection_from_scene(self):
        """Scene selection changed → update list highlight."""
        if self._internal_sync:
            return
            
        selected_scene_ids = {
            id(item) for item in self.scene.selectedItems()
            if self._is_user_item(item)
        }
        
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            li = self.list_widget.item(i)
            li.setSelected(li.data(Qt.ItemDataRole.UserRole) in selected_scene_ids)
        self.list_widget.blockSignals(False)
        
        # Update detail panel for the first selected item
        sel = self.list_widget.selectedItems()
        if sel:
            self._show_detail(sel[0])
        else:
            self.detail_frame.hide()

    # ------------------------------------------------- List → scene sync --

    def _on_list_selection_changed(self):
        if self._internal_sync:
            return
            
        selected_ids = {
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.list_widget.selectedItems()
        }

        self._internal_sync = True
        self.scene.blockSignals(True)
        self.scene.clearSelection()
        for item in self.scene.items():
            if self._is_user_item(item) and id(item) in selected_ids:
                item.setSelected(True)
        self.scene.blockSignals(False)
        self.scene.update()
        if hasattr(self.scene, 'on_selection_change'):
            self.scene.on_selection_change()
        self._internal_sync = False

        # Show detail panel
        sel = self.list_widget.selectedItems()
        if sel:
            self._show_detail(sel[0])
        else:
            self.detail_frame.hide()

    # --------------------------------------------------- Detail panel --

    def _show_detail(self, list_item):
        item_id = list_item.data(Qt.ItemDataRole.UserRole)
        scene_item = next(
            (i for i in self.scene.items()
             if self._is_user_item(i) and id(i) == item_id),
            None)
        if not scene_item:
            self.detail_frame.hide()
            return

        cls = scene_item.__class__.__name__
        name = self._get_label(scene_item)
        self.detail_name.setText(name)

        info_lines = []
        thumb_pm = None

        if cls == 'BeePixmapItem':
            if scene_item.filename:
                info_lines.append(f'<b>Source:</b> {scene_item.filename}')
                ext = os.path.splitext(scene_item.filename)[1].lstrip('.').upper()
                info_lines.append(f'<b>Format:</b> {ext}')
            pm = scene_item.pixmap()
            if not pm.isNull():
                info_lines.append(f'<b>Dimensions:</b> {pm.width()}×{pm.height()}')
                if scene_item.filename and os.path.exists(scene_item.filename):
                    size = os.path.getsize(scene_item.filename)
                    info_lines.append(f'<b>Size:</b> {size / 1024:.2f} KB')
                thumb_pm = pm.scaled(
                    DETAIL_THUMB, DETAIL_THUMB,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)

        self.detail_info.setText('<br>'.join(info_lines))
        if thumb_pm:
            self.detail_thumb.setPixmap(thumb_pm)
        else:
            self.detail_thumb.clear()

        self.detail_frame.show()

    # --------------------------------------------------- Rename (right-click) --

    def _show_list_context_menu(self, pos):
        """Show a small context menu with a Rename option."""
        list_item = self.list_widget.itemAt(pos)
        if not list_item:
            return
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: rgba(35,35,35,240);
                border: 1px solid rgba(255,255,255,30);
                border-radius: 8px;
                color: #e0e0e0;
                font-family: 'Segoe UI','Inter',sans-serif;
                font-size: 13px;
                padding: 4px;
            }
            QMenu::item { padding: 6px 20px; border-radius: 5px; }
            QMenu::item:selected { background: rgba(255,255,255,25); color: white; }
        """)
        rename_action = menu.addAction('Rename')
        
        # Block sync while menu is open
        self._sync_timer.stop()
        self._renaming = True
        
        action = menu.exec(self.list_widget.mapToGlobal(pos))
        if action == rename_action:
            self._start_rename(list_item)
        else:
            self._renaming = False
            self._do_sync_from_scene()

    def _start_rename(self, list_item):
        """Show an inline text editor directly over the list item."""
        self._sync_timer.stop()
        self._renaming = True

        item_id   = list_item.data(Qt.ItemDataRole.UserRole)
        item_rect = self.list_widget.visualItemRect(list_item)

        origin = self.list_widget.mapTo(self, item_rect.topLeft())
        width  = item_rect.width() - THUMB_SIZE - 12
        height = item_rect.height()

        editor = QtWidgets.QLineEdit(self)
        editor.setText(list_item.text())
        editor.selectAll()
        editor.setGeometry(
            origin.x() + THUMB_SIZE + 8,
            origin.y(),
            max(width, 80),
            height)
        editor.setStyleSheet("""
            QLineEdit {
                background: rgb(20, 100, 180);
                border: 1px solid rgba(0, 200, 255, 220);
                border-radius: 4px;
                color: white;
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 12px;
                padding: 0 4px;
            }
        """)
        editor.show()
        editor.raise_()
        editor.setFocus(Qt.FocusReason.OtherFocusReason)

        committed = [False]

        def _commit():
            if committed[0]:
                return
            committed[0] = True
            editor.hide()
            editor.deleteLater()
            
            new_name_stem = editor.text().strip()
            
            # --- Real File Renaming Logic ---
            scene_item = next((i for i in self.scene.items() if id(i) == item_id), None)
            if scene_item:
                if getattr(scene_item, 'filename', None):
                    old_path = scene_item.filename
                    directory = os.path.dirname(old_path)
                    extension = os.path.splitext(old_path)[1]
                    new_path = os.path.join(directory, new_name_stem + extension)
                    if new_path != old_path:
                        try:
                            if os.path.exists(new_path):
                                QtWidgets.QMessageBox.warning(self.view, "Rename Error", f"A file with the name '{new_name_stem + extension}' already exists.")
                            else:
                                os.rename(old_path, new_path)
                                # Use undo command to update the application state
                                cmd = commands.RenameItem(scene_item, new_path, old_path, is_file=True, hierarchy_overlay=self)
                                self.view.undo_stack.push(cmd)
                                logger.info(f"Renamed file on disk and pushed undo command: {old_path} -> {new_path}")
                        except OSError as e:
                            logger.error(f"Failed to rename file: {e}")
                            QtWidgets.QMessageBox.critical(self.view, "Rename Error", f"Could not rename file on disk:\n{e}")
                else:
                    # Custom label (pasted image/text)
                    old_label = self._custom_labels.get(item_id, "")
                    if new_name_stem != old_label:
                        cmd = commands.RenameItem(scene_item, new_name_stem, old_label, is_file=False, hierarchy_overlay=self)
                        self.view.undo_stack.push(cmd)
            
            self._renaming = False
            self._do_sync_from_scene()

        def _cancel():
            if committed[0]:
                return
            committed[0] = True
            editor.hide()
            editor.deleteLater()
            self._renaming = False
            self._do_sync_from_scene()

        def _key_press(event):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                _commit()
            elif event.key() == Qt.Key.Key_Escape:
                _cancel()
            else:
                QtWidgets.QLineEdit.keyPressEvent(editor, event)

        def _focus_out(event):
            QtWidgets.QLineEdit.focusOutEvent(editor, event)
            _cancel()

        editor.keyPressEvent = _key_press
        editor.focusOutEvent = _focus_out

    # --------------------------------------------------- Positioning --

    def update_position(self):
        if not self._user_moved:
            v = self.view.size()
            s = self.size()
            self.move(v.width() - s.width() - 20, 50)

    def showEvent(self, event):
        super().showEvent(event)
        self.update_position()
        self._do_sync_from_scene()
