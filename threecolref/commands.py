# This file is part of threecolref.
#
# 3ColRef is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# 3ColRef is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with threecolref.  If not, see <https://www.gnu.org/licenses/>.

from PyQt6 import QtCore, QtGui


class InsertItems(QtGui.QUndoCommand):

    def __init__(self, scene, items, position=None, ignore_first_redo=False):
        super().__init__('Insert items')
        self.scene = scene
        self.items = items
        self.position = position
        self.ignore_first_redo = ignore_first_redo

    def redo(self):
        try:
            if self.ignore_first_redo:
                self.ignore_first_redo = False
                return

            self.scene.deselect_all_items()
            if self.position:
                self.old_positions = []
                rect = self.scene.itemsBoundingRect(items=self.items)
                for item in self.items:
                    self.old_positions.append(item.pos())
                    item.setPos(item.pos() + self.position - rect.center())
            for item in self.items:
                self.scene.addItem(item)
                item.setSelected(True)
                item.bring_to_front()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to redo InsertItems: {e}")
            # Do not re-raise to prevent application crash in event loop

    def undo(self):
        self.scene.deselect_all_items()
        for item in self.items:
            self.scene.removeItem(item)
        if self.position:
            for item, pos in zip(self.items, self.old_positions):
                item.setPos(pos)


class DeleteItems(QtGui.QUndoCommand):
    def __init__(self, scene, items):
        super().__init__('Delete items')
        self.scene = scene
        self.items = items
        # Store parents to restore them on undo
        self.items_and_parents = [(item, item.parentItem()) for item in items]

    def redo(self):
        for item in self.items:
            if item.scene() == self.scene:
                self.scene.removeItem(item)

    def undo(self):
        self.scene.clearSelection()
        for item, parent in self.items_and_parents:
            item.show() # Ensure item is visible after undo
            if parent and parent.scene() == self.scene:
                item.setParentItem(parent)
            else:
                item.setParentItem(None)
                if item.scene() != self.scene:
                    self.scene.addItem(item)
            item.setSelected(True)


class MoveItemsBy(QtGui.QUndoCommand):

    def __init__(self, items, delta, ignore_first_redo=False):
        super().__init__('Move items')
        # FIGMA-STYLE SAFETY: 
        # Only move items whose parents are NOT also in the selection.
        # Otherwise, children move twice (once from parent, once from command).
        item_set = set(items)
        top_items = []
        for item in items:
            p = item.parentItem()
            is_child_of_moving_parent = False
            while p:
                if p in item_set:
                    is_child_of_moving_parent = True
                    break
                p = p.parentItem()
            
            if not is_child_of_moving_parent:
                top_items.append(item)
                
        self.items = top_items
        self.delta = delta
        self.ignore_first_redo = ignore_first_redo

    def _broadcast(self, dx, dy):
        for item in self.items:
            scene = item.scene()
            if scene:
                scene.broadcast_move(self.items, dx, dy)
                break

    def redo(self):
        if self.ignore_first_redo:
            self.ignore_first_redo = False
            return
        for item in self.items:
            item.moveBy(self.delta.x(), self.delta.y())
        self._broadcast(self.delta.x(), self.delta.y())

    def undo(self):
        for item in self.items:
            item.moveBy(-self.delta.x(), -self.delta.y())
        self._broadcast(-self.delta.x(), -self.delta.y())


class ScaleItemsBy(QtGui.QUndoCommand):
    """Scale items by a given factor around the given anchor."""

    def __init__(self, items, factor, anchor, ignore_first_redo=False):
        super().__init__('Scale items')
        self.ignore_first_redo = ignore_first_redo
        self.items = items
        self.factor = factor
        self.anchor = anchor

    def _broadcast(self):
        for item in self.items:
            scene = item.scene()
            if scene and hasattr(scene, '_get_collab_manager'):
                mgr = scene._get_collab_manager()
                if mgr and not mgr.applying_remote and mgr.is_active:
                    iid = item.ensure_collab_id() if hasattr(item, 'ensure_collab_id') else None
                    if iid:
                        mgr.broadcast_item_transformed(
                            [iid], 'scale',
                            scale=item.scale(),
                            x=item.pos().x(), y=item.pos().y())

    def redo(self):
        if self.ignore_first_redo:
            self.ignore_first_redo = False
            return
        for item in self.items:
            item.setScale(item.scale() * self.factor,
                          item.mapFromScene(self.anchor))
        self._broadcast()

    def undo(self):
        for item in self.items:
            item.setScale(item.scale() / self.factor,
                          item.mapFromScene(self.anchor))
        self._broadcast()


class RotateItemsBy(QtGui.QUndoCommand):
    """Rotate items by a given delta around the given anchor."""

    def __init__(self, items, delta, anchor, ignore_first_redo=False):
        super().__init__('Rotate items')
        self.ignore_first_redo = ignore_first_redo
        self.items = items
        self.delta = delta
        self.anchor = anchor

    def _broadcast(self):
        for item in self.items:
            scene = item.scene()
            if scene and hasattr(scene, '_get_collab_manager'):
                mgr = scene._get_collab_manager()
                if mgr and not mgr.applying_remote and mgr.is_active:
                    iid = item.ensure_collab_id() if hasattr(item, 'ensure_collab_id') else None
                    if iid:
                        mgr.broadcast_item_transformed(
                            [iid], 'rotate',
                            rotation=item.rotation(),
                            x=item.pos().x(), y=item.pos().y())

    def redo(self):
        if self.ignore_first_redo:
            self.ignore_first_redo = False
            return
        for item in self.items:
            item.setRotation(
                item.rotation() + self.delta * item.flip(),
                item.mapFromScene(self.anchor))
        self._broadcast()

    def undo(self):
        for item in self.items:
            item.setRotation(item.rotation() - self.delta * item.flip(),
                             item.mapFromScene(self.anchor))
        self._broadcast()


class NormalizeItems(QtGui.QUndoCommand):

    def __init__(self, items, scale_factors):
        super().__init__('Normalize items')
        self.items = items
        self.scale_factors = scale_factors

    def redo(self):
        self.old_scale_factors = []
        for item, factor in zip(self.items, self.scale_factors):
            self.old_scale_factors.append(item.scale())
            item.setScale(item.scale() * factor, item.center)

    def undo(self):
        for item, factor in zip(self.items, self.old_scale_factors):
            item.setScale(factor, item.center)


class FlipItems(QtGui.QUndoCommand):

    def __init__(self, items, anchor, vertical):
        super().__init__('Flip items')
        self.items = items
        self.anchor = anchor
        self.vertical = vertical

    def redo(self):
        for item in self.items:
            item.do_flip(self.vertical, item.mapFromScene(self.anchor))

    def undo(self):
        self.redo()


class ResetScale(QtGui.QUndoCommand):

    def __init__(self, items):
        super().__init__('Reset Scale')
        self.items = items

    def redo(self):
        self.old_scale_factors = []
        for item in self.items:
            self.old_scale_factors.append(item.scale())
            item.setScale(1, anchor=item.center)

    def undo(self):
        for item, scale_factor in zip(self.items, self.old_scale_factors):
            item.setScale(scale_factor, anchor=item.center)


class ResetRotation(QtGui.QUndoCommand):

    def __init__(self, items):
        super().__init__('Reset Rotation')
        self.items = items

    def redo(self):
        self.old_rotations = []
        for item in self.items:
            self.old_rotations.append(item.rotation())
            item.setRotation(0, anchor=item.center)

    def undo(self):
        for item, rotation in zip(self.items, self.old_rotations):
            item.setRotation(rotation, anchor=item.center)


class ResetFlip(QtGui.QUndoCommand):

    def __init__(self, items):
        super().__init__('Reset Flip')
        self.items = items

    def redo(self):
        self.old_flips = []
        for item in self.items:
            self.old_flips.append(item.flip())
            if item.flip() == -1:
                item.do_flip(anchor=item.center)

    def undo(self):
        for item, flip in zip(self.items, self.old_flips):
            if flip == -1:
                item.do_flip(anchor=item.center)


class ResetCrop(QtGui.QUndoCommand):

    def __init__(self, items):
        super().__init__('Reset Crop')
        self.items = [item for item in items if item.is_image]

    def redo(self):
        self.old_crops = []
        for item in self.items:
            self.old_crops.append(item.crop)
            item.reset_crop()

    def undo(self):
        for item, crop in zip(self.items, self.old_crops):
            item.crop = crop


class ResetTransforms(QtGui.QUndoCommand):

    def __init__(self, items):
        super().__init__('Reset All Transformations')
        self.items = items

    def redo(self):
        self.old_values = []
        for item in self.items:
            values = {
                'scale': item.scale(),
                'rotation': item.rotation(),
                'flip': item.flip(),
            }
            if item.is_image:
                values['crop'] = item.crop
                item.reset_crop()
            self.old_values.append(values)

            item.setScale(1, anchor=item.center)
            item.setRotation(0, anchor=item.center)
            if item.flip() == -1:
                item.do_flip(anchor=item.center)

    def undo(self):
        for item, old in zip(self.items, self.old_values):
            item.setScale(old['scale'], anchor=item.center)
            item.setRotation(old['rotation'], anchor=item.center)
            if old['flip'] == -1:
                item.do_flip(anchor=item.center)
            if item.is_image:
                item.crop = old['crop']


class ArrangeItems(QtGui.QUndoCommand):

    def __init__(self, scene, items, positions):
        super().__init__('Arrange items')
        self.scene = scene
        self.items = items
        self.positions = positions

    def redo(self):
        self.old_positions = []
        for item, pos in zip(self.items, self.positions):
            self.old_positions.append(item.pos())
            orig_topleft = item.mapToScene(QtCore.QPointF(0, 0))
            rect_topleft = self.scene.itemsBoundingRect(
                items=[item]).topLeft()
            item.setPos(pos + orig_topleft - rect_topleft)

    def undo(self):
        for item, pos in zip(self.items, self.old_positions):
            item.setPos(pos)


class CropItem(QtGui.QUndoCommand):
    def __init__(self, item, crop):
        super().__init__('Crop item')
        self.item = item
        self.crop = crop

    def redo(self):
        self.old_crop = self.item.crop
        self.item.crop = self.crop

    def undo(self):
        self.item.crop = self.old_crop


class ChangeText(QtGui.QUndoCommand):

    def __init__(self, item, new_html, old_html):
        super().__init__('Change text')
        self.item = item
        self.new_html = new_html
        self.old_html = old_html

    def redo(self):
        self.item.setHtml(self.new_html)

    def undo(self):
        self.item.setHtml(self.old_html)


class ChangeOpacity(QtGui.QUndoCommand):
    """Change opacity on images."""

    def __init__(self, items, opacity, ignore_first_redo=False):
        super().__init__('Change Opacity')
        self.ignore_first_redo = ignore_first_redo
        self.items = list(filter(lambda item: item.is_image, items))
        self.opacity = opacity
        self.old_opacities = [item.opacity() for item in items]

    def redo(self):
        if self.ignore_first_redo:
            self.ignore_first_redo = False
            return

        for item in self.items:
            item.setOpacity(self.opacity)

    def undo(self):
        for item, opacity in zip(self.items, self.old_opacities):
            item.setOpacity(opacity)


class ToggleGrayscale(QtGui.QUndoCommand):
    """Toggle grayscale mode on images."""

    def __init__(self, items, grayscale):
        super().__init__('Toggle Grayscale')
        self.items = list(filter(lambda item: item.is_image, items))
        self.grayscale = grayscale
        self.old_grayscales = [item.grayscale for item in items]

    def redo(self):
        for item in self.items:
            item.grayscale = self.grayscale


class RenameItem(QtGui.QUndoCommand):
    """Rename an item's filename on disk or its custom label."""

    def __init__(self, item, new_name, old_name, is_file=False, hierarchy_overlay=None):
        super().__init__(f'Rename {"file" if is_file else "item"}')
        self.item = item
        self.new_name = new_name
        self.old_name = old_name
        self.is_file = is_file
        self.hierarchy_overlay = hierarchy_overlay

    def redo(self):
        self._apply(self.new_name)

    def undo(self):
        self._apply(self.old_name)

    def _apply(self, name):
        import os
        if self.is_file:
            # We assume the file rename happened successfully before this command was pushed
            # or we handle it here. To keep it simple and safe for dirty-tracking:
            self.item.filename = name
        else:
            if self.hierarchy_overlay:
                if name:
                    self.hierarchy_overlay._custom_labels[id(self.item)] = name
                else:
                    self.hierarchy_overlay._custom_labels.pop(id(self.item), None)
        
class SetItemsZValue(QtGui.QUndoCommand):
    """Sets the Z-value of a list of items for layering."""

    def __init__(self, items, new_values):
        super().__init__('Change Z-order')
        self.items = items
        self.new_values = new_values
        self.old_values = [item.zValue() for item in items]

    def redo(self):
        for item, value in zip(self.items, self.new_values):
            item.setZValue(value)

    def undo(self):
        for item, value in zip(self.items, self.old_values):
            item.setZValue(value)
