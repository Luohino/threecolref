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
import math
from queue import Queue

from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtCore import Qt

# import rpack  # Deferred to arrange_optimal

from threecolref import commands
from threecolref.collaboration import protocol
from threecolref.config import BeeSettings
from threecolref.items import item_registry, BeeErrorItem, sort_by_filename
from threecolref.selection import MultiSelectItem, RubberbandItem


logger = logging.getLogger(__name__)


class BeeGraphicsScene(QtWidgets.QGraphicsScene):
    cursor_changed = QtCore.pyqtSignal(QtGui.QCursor)
    cursor_cleared = QtCore.pyqtSignal()

    MOVE_MODE = 1
    RUBBERBAND_MODE = 2
    DRAW_MODE = 3
    ERASE_MODE = 4

    def __init__(self, undo_stack):
        super().__init__()
        self.active_mode = None
        self.undo_stack = undo_stack
        self.Z_STEP = 0.001
        self.selectionChanged.connect(self.on_selection_change)
        self.changed.connect(self.on_change)
        self.items_to_add = Queue()
        self.edit_item = None
        self.crop_item = None
        self.active_doodle_item = None
        self.active_tool = 'pencil' # 'pencil', 'rect', 'circle', 'line', 'arrow'
        self._erasing = False
        self._erased_items = []
        self.settings = BeeSettings()
        self.clear()
        self._clear_ongoing = False

    @property
    def max_z(self):
        """Returns the maximum Z-value of all top-level items in the scene."""
        try:
            items = [i for i in self.items() if i and not i.parentItem()]
            z_values = [i.zValue() for i in items if hasattr(i, 'ensure_collab_id')]
            return max(z_values) if z_values else 0.0
        except Exception:
            return 0.0

    @property
    def min_z(self):
        """Returns the minimum Z-value of all top-level items in the scene."""
        try:
            items = [i for i in self.items() if i and not i.parentItem()]
            z_values = [i.zValue() for i in items if hasattr(i, 'ensure_collab_id')]
            return min(z_values) if z_values else 0.0
        except Exception:
            return 0.0

    def clear(self):
        self._clear_ongoing = True
        super().clear()
        self.internal_clipboard = []
        self.rubberband_item = RubberbandItem()
        self.multi_select_item = MultiSelectItem()
        self._clear_ongoing = False

    def addItem(self, item):
        logger.debug(f'Adding item {item}')
        super().addItem(item)
        self._broadcast_item_added(item)

    def on_view_scale_change(self):
        """Called when the view scale changes. Updates the rubberband item."""
        if hasattr(self, 'rubberband_item'):
            self.rubberband_item.prepareGeometryChange()
        self.update()

    def removeItem(self, item):
        logger.debug(f'Removing item {item}')
        self._broadcast_item_removed(item)
        super().removeItem(item)

    # ------------------------------------------------------------------
    # Collaboration broadcasting
    # ------------------------------------------------------------------

    def _get_collab_manager(self):
        """Return the CollaborationManager from the view, or None."""
        for view in self.views():
            mgr = getattr(view, 'collab', None)
            if mgr is not None:
                return mgr
        return None

    def _broadcast_item_added(self, item):
        mgr = self._get_collab_manager()
        if mgr is None or mgr.applying_remote or not mgr.is_active:
            return
        if not hasattr(item, 'ensure_collab_id'):
            return  # not a user item (rubberband, multiselect, etc.)
        import base64
        cid = item.ensure_collab_id()
        mgr.register_item(cid, item)
        item_type = getattr(item, 'TYPE', 'unknown')
        data = {
            'x': item.pos().x(),
            'y': item.pos().y(),
            'z': item.zValue(),
            'scale': item.scale(),
            'rotation': item.rotation(),
            'filename': getattr(item, 'filename', None),
            'parent_id': getattr(item.parentItem(), 'collab_id', None) if item.parentItem() else None,
        }
        if item_type == 'pixmap':
            img_bytes, _ = item.pixmap_to_bytes()
            data['image_b64'] = base64.b64encode(img_bytes).decode('ascii')
        elif item_type == 'text':
            data['text'] = item.toPlainText()
        elif item_type == 'doodle':
            data['color'] = item._color_hex
            data['width'] = item._width
            data['points'] = item._points
        elif item_type == 'shape':
            data.update(item.get_extra_save_data())
        elif item_type == 'video':
            data['filename'] = item.filename
            # Send thumbnail as bytes if available, otherwise it will be probed on joiner side
            pixmap = item.pixmap()
            if pixmap and not pixmap.isNull():
                ba = QtCore.QByteArray()
                buffer = QtCore.QBuffer(ba)
                buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
                pixmap.save(buffer, "PNG")
                data['image_bytes'] = ba.data() # Binary transport
        
        mgr.broadcast_item_added(cid, item_type, data)

    def _broadcast_item_removed(self, item):
        mgr = self._get_collab_manager()
        if mgr is None or mgr.applying_remote or not mgr.is_active:
            return
        cid = getattr(item, 'collab_id', None)
        if cid:
            mgr.broadcast_item_removed([cid])

    def _broadcast_doodle_start(self, item):
        mgr = self._get_collab_manager()
        if mgr is None or mgr.applying_remote or not mgr.is_active:
            return
        cid = item.ensure_collab_id()
        item_type = getattr(item, 'TYPE', 'doodle')
        if item_type == 'shape':
            item_type = getattr(item, 'shape_type', 'rect')
            
        color = item._color_hex
        width = item._width
        pos = item.pos()
        parent_id = getattr(item.parentItem(), 'collab_id', None) if item.parentItem() else None
        mgr.broadcast_doodle_start(cid, item_type, color, width, pos.x(), pos.y(), parent_id)

    def _broadcast_doodle_point(self, item, x, y):
        mgr = self._get_collab_manager()
        if mgr is None or mgr.applying_remote or not mgr.is_active:
            return
        cid = item.collab_id
        mgr.broadcast_doodle_point(cid, x, y)

    def _broadcast_doodle_end(self, item):
        mgr = self._get_collab_manager()
        if mgr is None or mgr.applying_remote or not mgr.is_active:
            return
        cid = item.collab_id
        mgr.broadcast_doodle_end(cid)

    def _do_erase(self, pos):
        """Remove doodle items under the cursor."""
        try:
            if not self.views(): 
                return

            # STABILITY: Use view-aware item selection for better precision.
            # descending order ensures we see top items first.
            view = self.views()[0]
            found = self.items(pos, Qt.ItemSelectionMode.IntersectsItemShape, 
                               Qt.SortOrder.DescendingOrder, view.transform())
            
            from threecolref.items import BeeDoodleItem
            erased_now = []
            for item in found:
                # ONLY process doodles that are in this scene and currently visible.
                # item.isVisible() check is crucial here because hidden items are
                # still physically in the scene index.
                if isinstance(item, BeeDoodleItem) and item.scene() == self and item.isVisible():
                    # STABILITY: Just hide the item during the drag-session.
                    # This avoids the destructive C++ scene graph re-indexing 
                    # during high-frequency mouse events.
                    item.hide()
                    erased_now.append(item)
                    if self._erasing:
                        self._erased_items.append(item)
            
            # If not in a drag-session (force push), push immediately.
            if not self._erasing and erased_now:
                self.undo_stack.push(commands.DeleteItems(self, erased_now))
                
        except Exception as e:
            logger.error(f"Error in _do_erase: {e}", exc_info=True)

    def broadcast_move(self, items, dx, dy):
        """Called after items have been moved. Broadcasts absolute positions for reliability."""
        mgr = self._get_collab_manager()
        if mgr is None or mgr.applying_remote or not mgr.is_active:
            return
        for item in items:
            if hasattr(item, 'ensure_collab_id'):
                iid = item.ensure_collab_id()
                # Broadcast absolute position to avoid drift from relative deltas
                mgr.broadcast_item_transformed(
                    [iid], 'move',
                    x=item.pos().x(), y=item.pos().y())

    def cancel_active_modes(self):
        """Cancels ongoing crop modes, rubberband modes etc, if there are
        any.
        """
        self.cancel_crop_mode()
        self.end_rubberband_mode()

    def end_rubberband_mode(self):
        if self.rubberband_item.scene():
            logger.debug('Ending rubberband selection')
            self.removeItem(self.rubberband_item)
        self.active_mode = None

    def cancel_crop_mode(self):
        """Cancels an ongoing crop mode, if there is any."""
        if self.crop_item:
            self.crop_item.exit_crop_mode(confirm=False)

    def copy_selection_to_internal_clipboard(self):
        self.internal_clipboard = []
        for item in self.selectedItems(user_only=True):
            self.internal_clipboard.append(item)

    def paste_from_internal_clipboard(self, position):
        copies = []
        for item in self.internal_clipboard:
            copy = item.create_copy()
            copies.append(copy)
        self.undo_stack.push(commands.InsertItems(self, copies, position))

    def _get_hierarchical_z(self, items, is_raise=True):
        """Calculates new Z-values for items, respecting their parenting hierarchy."""
        from collections import defaultdict
        by_parent = defaultdict(list)
        for item in items:
            by_parent[item.parentItem()].append(item)

        new_z_map = {}
        for parent, child_list in by_parent.items():
            if parent is None:
                # Global items: use max_z/min_z
                z_values = [i.zValue() for i in child_list]
                if is_raise:
                    delta = self.max_z + self.Z_STEP - min(z_values)
                else:
                    delta = self.min_z - self.Z_STEP - max(z_values)
                for item in child_list:
                    new_z_map[item] = item.zValue() + delta
            else:
                # Child items: use sibling z_values
                others = [s for s in parent.childItems() if s not in child_list]
                sib_z = [s.zValue() for s in others]
                
                # Base target: Parent is at local Z=0. 
                # Raise -> top of siblings AND > 0
                # Lower -> bottom of siblings AND < 0
                if is_raise:
                    target_z = max(0.001, max(sib_z) if sib_z else 0.001) + self.Z_STEP
                else:
                    target_z = min(-0.001, min(sib_z) if sib_z else -0.001) - self.Z_STEP
                
                # Maintain relative order among selected children
                child_list.sort(key=lambda i: i.zValue(), reverse=(not is_raise))
                for i, item in enumerate(child_list):
                    new_z_map[item] = target_z + (i * self.Z_STEP if is_raise else -i * self.Z_STEP)
        
        return [new_z_map[item] for item in items]

    def raise_to_top(self):
        self.cancel_active_modes()
        items = self.selectedItems(user_only=True)
        if not items:
            return
        
        new_values = self._get_hierarchical_z(items, is_raise=True)
        self.undo_stack.push(commands.SetItemsZValue(items, new_values))

    def lower_to_bottom(self):
        self.cancel_active_modes()
        items = self.selectedItems(user_only=True)
        if not items:
            return
            
        new_values = self._get_hierarchical_z(items, is_raise=False)
        self.undo_stack.push(commands.SetItemsZValue(items, new_values))

    def normalize_width_or_height(self, mode):
        """Scale the selected images to have the same width or height, as
        specified by ``mode``.

        :param mode: "width" or "height".
        """

        self.cancel_active_modes()
        values = []
        items = self.selectedItems(user_only=True)
        for item in items:
            rect = self.itemsBoundingRect(items=[item])
            values.append(getattr(rect, mode)())
        if len(values) < 2:
            return
        avg = sum(values) / len(values)
        logger.debug(f'Calculated average {mode} {avg}')

        scale_factors = []
        for item in items:
            rect = self.itemsBoundingRect(items=[item])
            scale_factors.append(avg / getattr(rect, mode)())
        self.undo_stack.push(
            commands.NormalizeItems(items, scale_factors))

    def normalize_height(self):
        """Scale selected images to the same height."""
        return self.normalize_width_or_height('height')

    def normalize_width(self):
        """Scale selected images to the same width."""
        return self.normalize_width_or_height('width')

    def normalize_size(self):
        """Scale selected images to the same size.

        Size meaning the area = widh * height.
        """

        self.cancel_active_modes()
        sizes = []
        items = self.selectedItems(user_only=True)
        for item in items:
            rect = self.itemsBoundingRect(items=[item])
            sizes.append(rect.width() * rect.height())

        if len(sizes) < 2:
            return

        avg = sum(sizes) / len(sizes)
        logger.debug(f'Calculated average size {avg}')

        scale_factors = []
        for item in items:
            rect = self.itemsBoundingRect(items=[item])
            scale_factors.append(math.sqrt(avg / rect.width() / rect.height()))
        self.undo_stack.push(
            commands.NormalizeItems(items, scale_factors))

    def arrange_default(self):
        default = self.settings.valueOrDefault('Items/arrange_default')
        MAPPING = {
            'optimal': self.arrange_optimal,
            'horizontal': self.arrange,
            'vertical': partial(self.arrange, vertical=True),
            'square': self.arrange_square,
        }

        MAPPING[default]()

    def arrange(self, vertical=False):
        """Arrange items in a line (horizontally or vertically)."""

        self.cancel_active_modes()

        items = sort_by_filename(self.selectedItems(user_only=True))
        if len(items) < 2:
            return

        gap = self.settings.valueOrDefault('Items/arrange_gap')
        center = self.get_selection_center()
        positions = []
        rects = []
        for item in items:
            rects.append({
                'rect': self.itemsBoundingRect(items=[item]),
                'item': item})

        if vertical:
            rects.sort(key=lambda r: r['rect'].topLeft().y())
            sum_height = sum(map(lambda r: r['rect'].height(), rects))
            y = round(center.y() - sum_height/2)
            for rect in rects:
                positions.append(
                    QtCore.QPointF(
                        round(center.x() - rect['rect'].width()/2), y))
                y += rect['rect'].height() + gap

        else:
            rects.sort(key=lambda r: r['rect'].topLeft().x())
            sum_width = sum(map(lambda r: r['rect'].width(), rects))
            x = round(center.x() - sum_width/2)
            for rect in rects:
                positions.append(
                    QtCore.QPointF(
                        x, round(center.y() - rect['rect'].height()/2)))
                x += rect['rect'].width() + gap

        self.undo_stack.push(
            commands.ArrangeItems(self,
                                  [r['item'] for r in rects],
                                  positions))

    def arrange_optimal(self):
        self.cancel_active_modes()

        items = self.selectedItems(user_only=True)
        if len(items) < 2:
            return

        gap = self.settings.valueOrDefault('Items/arrange_gap')

        sizes = []
        for item in items:
            rect = self.itemsBoundingRect(items=[item])
            sizes.append((round(rect.width() + gap),
                          round(rect.height() + gap)))

        # The minimal area the items need if they could be packed optimally;
        # we use this as a starting shape for the packing algorithm
        min_area = sum(map(lambda s: s[0] * s[1], sizes))
        width = math.ceil(math.sqrt(min_area))

        try:
            import rpack
        except ImportError:
            logger.warning('rpack not installed, falling back to horizontal arrange')
            self.arrange()
            return
        positions = None
        while not positions:
            try:
                positions = rpack.pack(
                    sizes, max_width=width, max_height=width)
            except rpack.PackingImpossibleError:
                width = math.ceil(width * 1.2)

        # We want the items to center around the selection's center,
        # not (0, 0)
        center = self.get_selection_center()
        bounds = rpack.bbox_size(sizes, positions)
        diff = center - QtCore.QPointF(bounds[0]/2, bounds[1]/2)
        positions = [QtCore.QPointF(*pos) + diff for pos in positions]

        self.undo_stack.push(commands.ArrangeItems(self, items, positions))

    def arrange_square(self):
        self.cancel_active_modes()
        max_width = 0
        max_height = 0
        gap = self.settings.valueOrDefault('Items/arrange_gap')
        items = sort_by_filename(self.selectedItems(user_only=True))

        if len(items) < 2:
            return

        for item in items:
            rect = self.itemsBoundingRect(items=[item])
            max_width = max(max_width, rect.width() + gap)
            max_height = max(max_height, rect.height() + gap)

        # We want the items to center around the selection's center,
        # not (0, 0)
        num_rows = math.ceil(math.sqrt(len(items)))
        center = self.get_selection_center()
        diff = center - num_rows/2 * QtCore.QPointF(max_width, max_height)

        iter_items = iter(items)
        positions = []
        for j in range(num_rows):
            for i in range(num_rows):
                try:
                    item = next(iter_items)
                    rect = self.itemsBoundingRect(items=[item])
                    point = QtCore.QPointF(
                        i * max_width + (max_width - rect.width())/2,
                        j * max_height + (max_height - rect.height())/2)
                    positions.append(point + diff)
                except StopIteration:
                    break

        self.undo_stack.push(commands.ArrangeItems(self, items, positions))

    def flip_items(self, vertical=False):
        """Flip selected items."""
        self.cancel_active_modes()
        self.undo_stack.push(
            commands.FlipItems(self.selectedItems(user_only=True),
                               self.get_selection_center(),
                               vertical=vertical))

    def crop_items(self):
        """Crop selected item."""

        if self.crop_item:
            return
        if self.has_single_image_selection():
            item = self.selectedItems(user_only=True)[0]
            if item.is_image:
                item.enter_crop_mode()

    def sample_color_at(self, position):
        item_at_pos = self.itemAt(position, self.views()[0].transform())
        if item_at_pos:
            return item_at_pos.sample_color_at(position)

    def select_all_items(self):
        self.cancel_active_modes()
        path = QtGui.QPainterPath()
        path.addRect(self.itemsBoundingRect())
        # This is faster than looping through all items and calling setSelected
        self.setSelectionArea(path)

    def deselect_all_items(self):
        self.cancel_active_modes()
        self.clearSelection()

    def has_selection(self):
        """Checks whether there are currently items selected."""

        return bool(self.selectedItems(user_only=True))

    def has_single_selection(self):
        """Checks whether there's currently exactly one item selected."""

        return len(self.selectedItems(user_only=True)) == 1

    def has_multi_selection(self):
        """Checks whether there are currently more than one items selected."""

        return len(self.selectedItems(user_only=True)) > 1

    def has_single_image_selection(self):
        """Checks whether the current selection is a single image."""

        if self.has_single_selection():
            return self.selectedItems(user_only=True)[0].is_image
        return False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            # Right-click invokes the context menu on the
            # GraphicsView. We don't need it here.
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self.event_start = event.scenePos()

            if self.active_mode == self.DRAW_MODE:
                # UX: If user clicks inside the bounding box of any selected item,
                # let them move/transform it instead of starting a new drawing.
                click_pos = self.event_start
                for sel_item in self.selectedItems():
                    if sel_item.sceneBoundingRect().contains(click_pos):
                        super().mousePressEvent(event)
                        return

                color = self.settings.valueOrDefault('Items/doodle_color') or '#FF0000'
                width = int(self.settings.valueOrDefault('Items/doodle_width') or 2)
                
                if self.active_tool == 'pencil':
                    from threecolref.items import BeeDoodleItem
                    self.active_doodle_item = BeeDoodleItem(color_hex=color, width=width)
                else:
                    from threecolref.items import BeeShapeItem
                    self.active_doodle_item = BeeShapeItem(
                        shape_type=self.active_tool, color_hex=color, width=width)
                
                # FIGMA-STYLE AUTO-PARENTING:
                # Find the top-most item (non-doodle/shape) at the click position.
                parent = None
                items_under = self.items(self.event_start)
                for item in items_under:
                    if (hasattr(item, 'TYPE') 
                            and item.TYPE not in ('doodle', 'shape')
                            and item.isVisible()):
                        parent = item
                        break
                
                if parent:
                    self.active_doodle_item.setParentItem(parent)
                    # Convert start pos to parent local coords
                    start_local = parent.mapFromScene(self.event_start)
                    self.active_doodle_item.setPos(start_local)
                else:
                    self.active_doodle_item.setPos(self.event_start)
                
                # Optimization: Disable flags during stroke
                self.active_doodle_item.setFlag(
                    QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
                self.active_doodle_item.setFlag(
                    QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                
                if hasattr(self.active_doodle_item, 'add_point'):
                    self.active_doodle_item.add_point(0, 0)
                self.addItem(self.active_doodle_item)
                
                # STACKING SAFETY:
                # Always ensure the new doodle is on top of everything else.
                if hasattr(self.active_doodle_item, 'bring_to_front'):
                    self.active_doodle_item.bring_to_front()
                    
                self._broadcast_doodle_start(self.active_doodle_item)
                event.accept()
                return

            if self.active_mode == self.ERASE_MODE:
                # Mark as session start
                self._erasing = True
                self._erased_items = []
                self._do_erase(event.scenePos())
                event.accept()
                return

            view = self.views()[0] if self.views() else None
            item_at_pos = self.itemAt(event.scenePos(), view.transform()) if view else None

            if self.edit_item:
                if item_at_pos != self.edit_item:
                    self.edit_item.exit_edit_mode()
                else:
                    super().mousePressEvent(event)
                    return
            if self.crop_item:
                if item_at_pos != self.crop_item:
                    self.cancel_crop_mode()
                else:
                    super().mousePressEvent(event)
                    return

            if item_at_pos:
                self.active_mode = self.MOVE_MODE
            elif self.items():
                self.active_mode = self.RUBBERBAND_MODE

        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.cancel_active_modes()
        view = self.views()[0] if self.views() else None
        item = self.itemAt(event.scenePos(), view.transform()) if view else None
        if item:
            if not item.isSelected():
                item.setSelected(True)
            # Video items: toggle live playback on double-click
            if getattr(item, 'is_video', False):
                if getattr(item, '_live', False):
                    item._stop_live()
                else:
                    item._start_live()
                return
            if item.is_editable:
                item.enter_edit_mode()
                self.mousePressEvent(event)
            else:
                self.views()[0].fit_rect(
                    self.itemsBoundingRect(items=[item]),
                    toggle_item=item)
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        if self.active_mode == self.RUBBERBAND_MODE:
            if not self.rubberband_item.scene():
                logger.debug('Activating rubberband selection')
                self.addItem(self.rubberband_item)
                self.rubberband_item.bring_to_front()
            self.rubberband_item.fit(self.event_start, event.scenePos())
            self.setSelectionArea(self.rubberband_item.shape())
            self.views()[0].reset_previous_transform()

        if self.active_mode == self.DRAW_MODE:
            if self.active_doodle_item:
                rel_pos = self.active_doodle_item.mapFromScene(event.scenePos())
                
                if self.active_tool == 'pencil':
                    self.active_doodle_item.add_point(rel_pos.x(), rel_pos.y())
                    self._broadcast_doodle_point(
                        self.active_doodle_item, rel_pos.x(), rel_pos.y())
                else:
                    # Shapes: p1 is (0,0) in local coords (since item is at event_start)
                    # p2 is rel_pos
                    self.active_doodle_item.update_points(QtCore.QPointF(0, 0), rel_pos)
                    # For shapes, we broadcast the updated item state
                    self._broadcast_item_added(self.active_doodle_item)
                    from threecolref.items import BeeShapeItem
                    if isinstance(self.active_doodle_item, BeeShapeItem):
                        self.active_doodle_item.update_points(QtCore.QPointF(0, 0), rel_pos)
                    
            event.accept()
            return

        if self.active_mode == self.ERASE_MODE:
            if self._erasing:
                self._do_erase(event.scenePos())
            event.accept()
            return

        # Broadcast cursor even when hovering over items
        mgr = self._get_collab_manager()
        if mgr and mgr.is_active:
            pos = event.scenePos()
            mgr.broadcast_cursor(pos.x(), pos.y())

        # Live drag broadcast: send absolute positions to peers while dragging
        if self.active_mode == self.MOVE_MODE and self.has_selection():
            if mgr and mgr.is_active and not mgr.applying_remote:
                import time as _time
                now = _time.monotonic() * 1000
                if not hasattr(self, '_last_move_broadcast_ms'):
                    self._last_move_broadcast_ms = 0
                if now - self._last_move_broadcast_ms >= 33:
                    self._last_move_broadcast_ms = now
                    for item in self.selectedItems():
                        if hasattr(item, 'ensure_collab_id'):
                            iid = item.ensure_collab_id()
                            # ABSOLUTE POSITION SYNC
                            mgr.broadcast_item_transformed(
                                [iid], 'move',
                                x=item.pos().x(), y=item.pos().y())
        
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.active_mode == self.RUBBERBAND_MODE:
            self.end_rubberband_mode()

        if self.active_mode == self.DRAW_MODE:
            if self.active_doodle_item:
                item = self.active_doodle_item
                if hasattr(item, 'finish_path'):
                    item.finish_path()
                
                self.active_doodle_item = None
                
                # CRITICAL FIX: Shapes use item_added protocol; pencil doodles use doodle streaming
                from threecolref.items import BeeShapeItem
                if isinstance(item, BeeShapeItem):
                    self._broadcast_item_added(item)
                else:
                    self._broadcast_doodle_end(item)
                
                # Item already in scene from mousePressEvent; skip first redo
                item.setFlag(
                    QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                item.setFlag(
                    QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
                
                # UX: Select the item immediately so it can be moved/resized
                self.clearSelection()
                item.setSelected(True)
                
                self.undo_stack.push(
                    commands.InsertItems(self, [item], ignore_first_redo=True))
            event.accept()
            return  # Stay in DRAW_MODE for next stroke

        if self.active_mode == self.ERASE_MODE:
            if self._erasing:
                if self._erased_items:
                    self.undo_stack.push(commands.DeleteItems(self, self._erased_items))
                self._erasing = False
                self._erased_items = []
            event.accept()
            return  # Stay in ERASE_MODE

        if (self.active_mode == self.MOVE_MODE
                and self.has_selection()
                and self.multi_select_item.active_mode is None
                and self.selectedItems()[0].active_mode is None):
            delta = event.scenePos() - self.event_start
            if not delta.isNull():
                self._updating_scene = True
                try:
                    self.undo_stack.push(
                        commands.MoveItemsBy(self.selectedItems(user_only=True),
                                             delta,
                                             ignore_first_redo=True))
                    # CRITICAL: Since ignore_first_redo skips redo() on the first
                    # push, the broadcast inside redo() never fires for a fresh move.
                    # Broadcast the final absolute position explicitly here.
                    self.broadcast_move(self.selectedItems(user_only=True), delta.x(), delta.y())
                finally:
                    self._updating_scene = False
                
                # Manual GUI layout flush after massive bulk move:
                if self.has_multi_selection() and self.multi_select_item.scene():
                    self.multi_select_item.fit_selection_area(
                        self.itemsBoundingRect(selection_only=True))
        self.active_mode = None
        super().mouseReleaseEvent(event)

    def selectedItems(self, user_only=False):
        """If ``user_only`` is set to ``True``, only return items added
        by the user (i.e. no multi select outlines and other UI items).

        User items are items that have a ``save_id`` attribute.
        """

        items = super().selectedItems()
        if user_only:
            return list(filter(lambda i: hasattr(i, 'save_id'), items))
        return items

    def items_by_type(self, itype):
        """Returns all items of the given type."""

        return filter(lambda i: getattr(i, 'TYPE', None) == itype,
                      self.items())

    def items_for_save(self):

        """Returns the items that are to be saved.

        Items to be saved are items that have a save_id attribute.
        """

        return filter(lambda i: hasattr(i, 'save_id'),
                      self.items(order=Qt.SortOrder.AscendingOrder))

    def clear_save_ids(self):
        for item in self.items_for_save():
            item.save_id = None

    def on_view_scale_change(self):
        for item in self.selectedItems():
            item.on_view_scale_change()

    def itemsBoundingRect(self, selection_only=False, items=None):
        """Returns the bounding rect of the scene's items; either all of them
        or only selected ones, or the items givin in ``items``.

        Re-implemented to not include the items's selection handles.
        """

        def filter_user_items(ilist):
            return list(filter(lambda i: hasattr(i, 'save_id'), ilist))

        if selection_only:
            base = filter_user_items(self.selectedItems())
        elif items:
            base = items
        else:
            base = filter_user_items(self.items())

        if not base:
            return QtCore.QRectF(0, 0, 0, 0)

        x = []
        y = []

        for item in base:
            for corner in item.corners_scene_coords:
                x.append(corner.x())
                y.append(corner.y())

        return QtCore.QRectF(
            QtCore.QPointF(min(x), min(y)),
            QtCore.QPointF(max(x), max(y)))

    def get_selection_center(self):
        rect = self.itemsBoundingRect(selection_only=True)
        return (rect.topLeft() + rect.bottomRight()) / 2

    def on_selection_change(self):
        if self._clear_ongoing:
            # Ignore events while clearing the scene since the
            # multiselect item will get cleared, too
            return
        if self.has_multi_selection():
            self.multi_select_item.fit_selection_area(
                self.itemsBoundingRect(selection_only=True))
        if self.has_multi_selection() and not self.multi_select_item.scene():
            self.addItem(self.multi_select_item)
            self.multi_select_item.bring_to_front()
        if not self.has_multi_selection() and self.multi_select_item.scene():
            self.removeItem(self.multi_select_item)

    def on_change(self, region):
        if self._clear_ongoing or getattr(self, '_updating_scene', False):
            # Ignore events while clearing the scene or if we're already
            # updating the scene to avoid infinite recursion
            return
            
        self._updating_scene = True
        try:
            if self.active_mode in (self.DRAW_MODE, self.ERASE_MODE):
                return  # Skip expensive recalc during drawing/erasing
                
            # GHOST-BORDER FIX: Only update the MultiSelectItem if we actually
            # have a multi-selection. Without this guard, the border persists
            # visually when transitioning from group → single selection.
            if (self.has_multi_selection()
                    and self.multi_select_item.scene()
                    and self.multi_select_item.active_mode is None):
                self.multi_select_item.fit_selection_area(
                    self.itemsBoundingRect(selection_only=True))
        finally:
            self._updating_scene = False

    def clear_doodles(self):
        """Removes all doodle items from the scene."""
        from threecolref.items import BeeDoodleItem
        to_remove = [i for i in self.items() if isinstance(i, BeeDoodleItem)]
        if not to_remove:
            return
            
        self.undo_stack.beginMacro("Clear Doodles")
        try:
            # DeleteItems handles the list of items correctly
            self.undo_stack.push(commands.DeleteItems(self, to_remove))
        finally:
            self.undo_stack.endMacro()
        logger.info(f"Cleared {len(to_remove)} doodles")

    def add_item_later(self, itemdata, selected=False):
        """Keep an item for adding later via ``add_queued_items``

        :param dict itemdata: Defines the item's data
        :param bool selected: Whether the item is initialised as selected
        """

        self.items_to_add.put((itemdata, selected))

    def add_queued_items(self):
        """Adds items added via ``add_item_later``"""
        
        id_to_item = {}
        relationships = []

        while not self.items_to_add.empty():
            data, selected = self.items_to_add.get()
            typ = data.get('type')
            cls = item_registry.get(typ)
            if not cls:
                cls = BeeErrorItem
                data['data'] = {'text': f'Item of unknown type: {typ}'}
            
            try:
                item = cls.create_from_data(**data)
                item.update_from_data(**data)
                
                # Store for second pass
                save_id = data.get('save_id')
                if save_id is not None:
                    id_to_item[save_id] = item
                
                parent_id = data.get('parent_id')
                if parent_id is not None:
                    relationships.append((item, parent_id))

                self.addItem(item)
                item.setZValue(item.zValue())
                if selected:
                    item.setSelected(True)
                    item.bring_to_front()
            except Exception as e:
                logger.error(f'Failed to add queued item: {e}')

        # Second Pass: Restore parent relationships
        for item, parent_id in relationships:
            parent = id_to_item.get(parent_id)
            if parent:
                # Store scene pos, set parent, then restore scene pos
                # because QGraphicsItem.setParentItem moves the item 
                # relative to the new parent's coordinate system.
                scene_pos = item.scenePos()
                item.setParentItem(parent)
                item.setPos(parent.mapFromScene(scene_pos))
                logger.debug(f'Restored parenting: {item} -> {parent}')
