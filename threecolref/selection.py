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

"""Classes that draw and handle selection stuff for items."""

import logging
import math

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGraphicsItem

from threecolref.assets import BeeAssets
from threecolref import commands
from threecolref.config import CommandlineArgs
from threecolref.constants import COLORS
from threecolref import utils


commandline_args = CommandlineArgs()
logger = logging.getLogger(__name__)
SELECT_COLOR = QtGui.QColor(*COLORS['Scene:Selection'])


# Hit test bias: how many pixels of the handle stay "inside" the bounding box.
# The rest is biased outwards to preserve the image center.
INTERACT_INSIDE_MARGIN = 19


def with_anchor(func):
    """Decorator that adds an anchor parameter to transform operations.

    The anchor is given in item coordinates.
    """

    def wrapper(self, *args, **kwargs):
        # We calculate where the anchor is before and after the transformation
        # and then move the item accordingly to keep the anchor fixed

        anchor = kwargs.pop('anchor', None)
        if not anchor:
            if args and isinstance(args[-1], QtCore.QPointF):
                anchor = args[-1]
                args = args[:-1]

        anchor = anchor or QtCore.QPointF(0, 0)
        prev = self.mapToScene(anchor)
        func(self, *args, **kwargs)
        diff = self.mapToScene(anchor) - prev
        self.setPos(self.pos() - diff)

    return wrapper


class BaseItemMixin:

    @with_anchor
    def setScale(self, value):
        if value <= 0:
            return

        logger.debug(f'Setting scale for {self} to {value}')
        self.prepareGeometryChange()
        super().setScale(value)

    def setZValue(self, value):
        logger.debug(f'Setting z-value for {self} to {value}')
        super().setZValue(value)
        if self.scene():
            self.scene().max_z = max(self.scene().max_z, value)
            self.scene().min_z = min(self.scene().min_z, value)

    def bring_to_front(self):
        self.setZValue(self.scene().max_z + self.scene().Z_STEP)

    @with_anchor
    def setRotation(self, value):
        logger.debug(f'Setting rotation for {self} to {value}')
        super().setRotation(value % 360)

    def flip(self):
        """Returns the flip value (1 or -1)"""
        # We use the transformation matrix only for flipping, so checking
        # the x scale is enough
        return self.transform().m11()

    @with_anchor
    def do_flip(self, vertical=False):
        """Flips the item."""
        self.setTransform(QtGui.QTransform.fromScale(-self.flip(), 1))
        if vertical:
            self.setRotation(self.rotation() + 180)

    def bounding_rect_unselected(self):
        return super().boundingRect()

    @property
    def width(self):
        return self.bounding_rect_unselected().width()

    @property
    def height(self):
        return self.bounding_rect_unselected().height()

    @property
    def center(self):
        return self.bounding_rect_unselected().center()

    @property
    def center_scene_coords(self):
        """The item's center in scene coordinates."""
        return self.mapToScene(self.center)

    def set_cursor(self, cursor):
        # Can't use setCursor on the item itself because of bug
        # https://bugreports.qt.io/browse/QTBUG-4190
        if self.scene():
            self.scene().cursor_changed.emit(cursor)

    def unset_cursor(self):
        # Can't use unsetCursor on the item itself because of bug
        # https://bugreports.qt.io/browse/QTBUG-4190
        if self.scene():
            self.scene().cursor_cleared.emit()

    def sample_color_at(self, pos):
        return None


class SelectableMixin(BaseItemMixin):
    """Common code for selectable items: Selection outline, handles etc."""

    SELECT_LINE_WIDTH = 4  # line width for the selection box
    SELECT_HANDLE_SIZE = 10  # subtle selection handles for scaling (pixels on screen)
    SELECT_RESIZE_SIZE = 20  # effortless "Goldilocks" hit zone (pixels on screen)
    SELECT_ROTATE_SIZE = 10  # hover area for rotating just outside corners
    SELECT_ROTATE_OFFSET = 30 # vertical distance of the rotation handle from top edge
    SELECT_ROTATE_HANDLE_SIZE = 15 # size of the modern rotation handle
    SELECT_FREE_CENTER = 15  # legacy; drag area is now whole image minus handles

    SCALE_MODE = 1
    ROTATE_MODE = 2

    def init_selectable(self):
        self.setAcceptHoverEvents(True)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

        self.viewport_scale = 1
        self.active_mode = None
        self.is_editable = False

    def fixed_length_for_viewport(self, value):
        """The interactable areas need to stay the same size on the
        screen so we need to adjust the values according to the scale
        factor sof the view and the item."""

        if self.scene():
            scale = self.scene().views()[0].get_scale()
            self._view_scale = scale

        # It can happen that the item is already removed from
        # the scene but its boundingRect is still needed. Keep the
        # last known scaling factor for that case
        return value / getattr(self, '_view_scale', 1) / self.scale()

    @property
    def select_resize_size(self):
        return self.fixed_length_for_viewport(self.SELECT_RESIZE_SIZE)

    @property
    def select_rotate_size(self):
        return self.fixed_length_for_viewport(self.SELECT_ROTATE_SIZE)

    def get_rotate_handle_pos(self):
        """Calculates the position of the modern rotation handle."""
        r = self.bounding_rect_unselected()
        offset = self.fixed_length_for_viewport(self.SELECT_ROTATE_OFFSET)
        return QtCore.QPointF(r.center().x(), r.top() - offset)

    def get_rotate_handle_bounds(self):
        """The hit test area for the modern rotation handle."""
        pos = self.get_rotate_handle_pos()
        r = self.fixed_length_for_viewport(self.SELECT_ROTATE_HANDLE_SIZE)
        path = QtGui.QPainterPath()
        path.addEllipse(pos, r, r)
        return path

    def select_handle_free_center(self) -> QtCore.QRectF:
        """Legacy - used for debug drawing. Drag is now allowed everywhere
         except scale/rotate/flip zones."""
        size = self.fixed_length_for_viewport(self.SELECT_FREE_CENTER)
        return QtCore.QRectF(
            self.center.x() - size/2,
            self.center.y() - size/2,
            size,
            size)
    def is_in_transform_zone(self, pos):
        """Checks whether the given position is within the interactable zones."""
        # Hit test for the 8 circular handles (Scaling)
        for pt in self.all_point_handles:
            if self.get_scale_bounds(pt, margin=self.select_resize_size/2).contains(pos):
                return True

        # Hit test for rotation handle (modern)
        if self.get_rotate_handle_bounds().contains(pos):
            return True

        # Hit test for the entire bounding border path (edges + corners)
        if self.get_edge_scale_path().contains(pos):
            return True

        return False

    def draw_debug_shape(self, painter, shape, r, g, b):
        color = QtGui.QColor(r, g, b, 50)
        if isinstance(shape, QtCore.QRectF):
            painter.fillRect(shape, color)
        else:
            painter.fillPath(shape, color)

    def paint_debug(self, painter, option, widget):
        if commandline_args.debug_shapes:
            self.draw_debug_shape(painter, self.shape(), 255, 0, 0)
        if commandline_args.debug_boundingrects:
            self.draw_debug_shape(painter, self.boundingRect(), 0, 255, 0)
        if (commandline_args.debug_handles and self.has_selection_handles()):
            for corner in self.corners:
                self.draw_debug_shape(
                    painter, self.get_scale_bounds(corner), 0, 0, 255)
                self.draw_debug_shape(
                    painter, self.get_rotate_bounds(corner), 0, 255, 255)
            for edge in self.get_edge_scale_bounds():
                self.draw_debug_shape(painter, edge['rect'], 0, 100, 255)
            self.draw_debug_shape(
                painter, self.select_handle_free_center(), 255, 0, 255)

    def paint_selectable(self, painter, option, widget):
        self.paint_debug(painter, option, widget)

        if not self.has_selection_outline():
            return

        rect = self.bounding_rect_unselected()
        pen = QtGui.QPen(SELECT_COLOR)
        pen.setWidth(self.SELECT_LINE_WIDTH)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QtGui.QBrush())

        # Draw the main selection rectangle (outline)
        painter.drawRect(rect)

        # Draw 8 circular handles: 4 corners + 4 edge midpoints (like reference)
        if self.has_selection_handles():
            painter.setBrush(QtGui.QBrush(SELECT_COLOR))
            painter.setPen(Qt.PenStyle.NoPen)
            r = self.fixed_length_for_viewport(self.SELECT_HANDLE_SIZE) / 2
            for pt in self.corners:
                painter.drawEllipse(pt, r, r)
            for pt in self.edge_midpoints:
                painter.drawEllipse(pt, r, r)

        # Draw modern rotation handle
        if self.has_selection_outline():
            painter.setPen(pen)
            r_box = self.bounding_rect_unselected()
            top_center = QtCore.QPointF(r_box.center().x(), r_box.top())
            handle_pos = self.get_rotate_handle_pos()
            
            # Draw connecting line
            painter.drawLine(top_center, handle_pos)
            
            # Draw handle circle
            painter.setBrush(QtGui.QBrush(SELECT_COLOR))
            painter.setPen(Qt.PenStyle.NoPen)
            hr = self.fixed_length_for_viewport(self.SELECT_ROTATE_HANDLE_SIZE) / 2
            painter.drawEllipse(handle_pos, hr, hr)
            
            # Draw SVG icon centered on handle
            svg_renderer = BeeAssets().icon_rotate_svg
            if svg_renderer.isValid():
                icon_r = hr * 0.7  # Scale icon to fit inside handle
                icon_rect = QtCore.QRectF(handle_pos.x() - icon_r, handle_pos.y() - icon_r, icon_r * 2, icon_r * 2)
                svg_renderer.render(painter, icon_rect)

    @property
    def corners(self):
        """The corners of the item. Used for scale and rotate handles."""
        return (self.bounding_rect_unselected().topLeft(),
                self.bounding_rect_unselected().topRight(),
                self.bounding_rect_unselected().bottomRight(),
                self.bounding_rect_unselected().bottomLeft())

    @property
    def edge_midpoints(self):
        """Midpoints of each edge - top, bottom, left, right = ROTATE handles."""
        r = self.bounding_rect_unselected()
        return (
            QtCore.QPointF(r.center().x(), r.top()),
            QtCore.QPointF(r.center().x(), r.bottom()),
            QtCore.QPointF(r.left(), r.center().y()),
            QtCore.QPointF(r.right(), r.center().y()),
        )

    @property
    def all_point_handles(self):
        """All 8 interactable dots: 4 corners + 4 midpoints."""
        return list(self.corners) + list(self.edge_midpoints)

    def get_edge_scale_path(self):
        """Clickable path for all 4 edges - ensures complete coverage."""
        path = QtGui.QPainterPath()
        for edge in self.get_edge_scale_bounds():
            path.addRect(edge['rect'])
        return path

    def get_edge_scale_bounds(self):
        """Clickable area for the 4 edges. Biased outwards to preserve interior space."""
        r = self.bounding_rect_unselected()
        strip = self.select_resize_size
        m = strip / 2
        b = self.fixed_length_for_viewport(INTERACT_INSIDE_MARGIN)
        return [
            # Top: shifted strip - b up
            {'rect': QtCore.QRectF(r.left() - m, r.top() - strip + b, r.width() + 2*m, strip), 'pt': self.edge_midpoints[0]},
            # Bottom: shifted strip - b down
            {'rect': QtCore.QRectF(r.left() - m, r.bottom() - b, r.width() + 2*m, strip), 'pt': self.edge_midpoints[1]},
            # Left: shifted strip - b left
            {'rect': QtCore.QRectF(r.left() - strip + b, r.top() - m, strip, r.height() + 2*m), 'pt': self.edge_midpoints[2]},
            # Right: shifted strip - b right
            {'rect': QtCore.QRectF(r.right() - b, r.top() - m, strip, r.height() + 2*m), 'pt': self.edge_midpoints[3]},
        ]

    @property
    def corners_scene_coords(self):
        """The corners of the item mapped to scene coordinates."""

        return [self.mapToScene(corner) for corner in self.corners]

    def get_scale_bounds(self, corner, margin=0):
        """The interactable shape of the scale handles. Biased outwards."""
        path = QtGui.QPainterPath()
        size = self.select_resize_size + 2 * margin
        
        # Offset to bias outwards: INTERACT_INSIDE_MARGIN px inside, the rest outside
        bias = self.fixed_length_for_viewport(INTERACT_INSIDE_MARGIN)
        dx = 0
        dy = 0
        if corner.x() < self.center.x(): dx = -size/2 + bias # Left
        elif corner.x() > self.center.x(): dx = size/2 - bias # Right
        
        if corner.y() < self.center.y(): dy = -size/2 + bias # Top
        elif corner.y() > self.center.y(): dy = size/2 - bias # Bottom
        
        path.addRect(QtCore.QRectF(
            corner.x() + dx - size/2,
            corner.y() + dy - size/2,
            size, size))
        return path

    def get_closest_transform_point(self, pos):
        """Find the corner or edge midpoint closest to the given position."""
        best_pt = None
        min_dist = float('inf')
        # Check corners and midpoints using Euclidean distance
        for pt in self.all_point_handles:
            dist = math.hypot(pos.x() - pt.x(), pos.y() - pt.y())
            if dist < min_dist:
                min_dist = dist
                best_pt = pt
        return best_pt

    def get_rotate_bounds(self, corner):
        """The interactable shape of the rotation area."""
        path = QtGui.QPainterPath()

        # The whole square containing the rotate area:
        d = self.get_corner_direction(corner)
        p1 = corner - d * self.select_resize_size / 2
        p2 = p1 + d * (self.select_resize_size + self.select_rotate_size)
        path.addRect(utils.get_rect_from_points(p1, p2))

        # Substract the scale area:
        return path - self.get_scale_bounds(corner, margin=0.001)

    def get_flip_bounds(self):
        """Legacy - returns empty list as flip handles were removed."""
        return []

    def boundingRect(self):
        if not self.has_selection_outline():
            return self.bounding_rect_unselected()

        # Add extra space for the interactive areas
        # We need to account for both the old hover areas and the new modern rotation handle which extends upwards
        rotate_margin = max(
            self.select_rotate_size, 
            self.fixed_length_for_viewport(self.SELECT_ROTATE_OFFSET + self.SELECT_ROTATE_HANDLE_SIZE)
        )
        margin = self.select_resize_size / 2 + rotate_margin
        return self.bounding_rect_unselected().marginsAdded(
            QtCore.QMarginsF(margin, margin, margin, margin))

    def shape(self):
        path = QtGui.QPainterPath()
        if self.has_selection_handles():
            margin = self.select_resize_size / 2
            rect = self.bounding_rect_unselected().marginsAdded(
                QtCore.QMarginsF(margin, margin, margin, margin))
            path.addRect(rect)
            for corner in self.corners:
                path.addPath(self.get_rotate_bounds(corner))
            path.addPath(self.get_edge_scale_path())
            path.addPath(self.get_rotate_handle_bounds())
        else:
            rect = self.bounding_rect_unselected()
            path.addRect(rect)
        return path

    def hoverMoveEvent(self, event):
        if not self.isSelected():
            self.unset_cursor()
            return

        pos = event.pos()
        
        # Priority 1: Modern Rotation Handle
        if self.get_rotate_handle_bounds().contains(pos):
            self.set_cursor(Qt.CursorShape.PointingHandCursor)
            return

        # Priority 2: The 8 circular handles - generous 40px hit zones
        closest_pt = None
        min_dist = float('inf')
        for pt in self.all_point_handles:
            if self.get_scale_bounds(pt, margin=self.select_resize_size/2).contains(pos):
                dist = math.hypot(pos.x() - pt.x(), pos.y() - pt.y())
                if dist < min_dist:
                    min_dist = dist
                    closest_pt = pt
        
        if closest_pt:
            self.set_cursor(self.get_corner_scale_cursor(closest_pt))
            return

        # Priority 3: Continuous Border Scaling (edges and corners)
        if self.get_edge_scale_path().contains(pos):
            edge_pt = self.get_closest_transform_point(pos)
            self.set_cursor(self.get_corner_scale_cursor(edge_pt))
            return

        self.unset_cursor()

    def hoverLeaveEvent(self, event):
        self.unset_cursor()

    def mousePressEvent(self, event):
        self.event_start = event.scenePos()
        self.scene().views()[0].reset_previous_transform(toggle_item=self)
        if not self.isSelected():
            # User has just selected this item with this click; don't
            # activate any transformations yet
            super().mousePressEvent(event)
            return

        if not self.is_in_transform_zone(event.pos()):
            super().mousePressEvent(event)
            return

        if (event.button() == Qt.MouseButton.LeftButton
                and self.has_selection_handles()):
            pos = event.pos()
            
            # Priority 1: Modern Rotation Handle
            if self.get_rotate_handle_bounds().contains(pos):
                self.active_mode = self.ROTATE_MODE
                self.event_anchor = self.center_scene_coords
                self.rotate_start_angle = self.get_rotate_angle(event.scenePos())
                for item in self.selection_action_items():
                    item.rotate_orig_degrees = item.rotation()
                event.accept()
                return

            # Priority 2: The 8 circular handles - generous 40px hit zones
            closest_pt = None
            min_dist = float('inf')
            for pt in self.all_point_handles:
                if self.get_scale_bounds(pt, margin=self.select_resize_size/2).contains(pos):
                    dist = math.hypot(pos.x() - pt.x(), pos.y() - pt.y())
                    if dist < min_dist:
                        min_dist = dist
                        closest_pt = pt
            
            if closest_pt:
                self.active_mode = self.SCALE_MODE
                self.event_direction = self.get_direction_from_center(event.scenePos())
                self.event_anchor = self.mapToScene(self.get_scale_anchor(closest_pt))
                for item in self.selection_action_items():
                    item.scale_orig_factor = item.scale()
                event.accept()
                return

            # Priority 3: Continuous Border Scaling (edges and corners)
            if self.get_edge_scale_path().contains(pos):
                edge_pt = self.get_closest_transform_point(pos)
                self.active_mode = self.SCALE_MODE
                self.event_direction = self.get_direction_from_center(event.scenePos())
                self.event_anchor = self.mapToScene(self.get_scale_anchor(edge_pt))
                for item in self.selection_action_items():
                    item.scale_orig_factor = item.scale()
                event.accept()
                return

            # PureRef style: Ctrl+Drag anywhere in transform zone triggers rotation
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self.active_mode = self.ROTATE_MODE
                self.event_anchor = self.center_scene_coords
                self.rotate_start_angle = self.get_rotate_angle(
                    event.scenePos())
                for item in self.selection_action_items():
                    item.rotate_orig_degrees = item.rotation()
                event.accept()
                return

        super().mousePressEvent(event)

    def get_scale_factor(self, event):
        """Get the scale factor based on movement relative to the anchor."""
        # Project current mouse vector onto the starting vector for 
        # a perfectly responsive, PureRef-identical scaling feel.
        v1 = self.event_start - self.event_anchor
        start_dist = math.hypot(v1.x(), v1.y())
        if start_dist < 1: 
            return 1.0
        
        v2 = event.scenePos() - self.event_anchor
        
        # projected_dist = (v2 dot v1) / |v1|
        dot_product = v2.x() * v1.x() + v2.y() * v1.y()
        projected_dist = dot_product / start_dist
        
        return projected_dist / start_dist

    def get_scale_anchor(self, corner):
        """Get the anchor around which the scale for this corner operates."""
        origin = self.bounding_rect_unselected().topLeft()
        return QtCore.QPointF(self.width - corner.x() + 2*origin.x(),
                              self.height - corner.y() + 2*origin.y())

    def get_corner_direction(self, corner):
        """Get the direction facing away from the center, e.g. the direction
        in which the scale for this corner increases."""
        return QtCore.QPointF(1 if corner.x() > self.center.x() else -1,
                              1 if corner.y() > self.center.y() else -1)

    def get_direction_from_center(self, pos):
        """The direction of a point in relation to the item's center."""
        diff = pos - self.center_scene_coords
        length = math.sqrt(QtCore.QPointF.dotProduct(diff, diff))
        return diff / length

    def get_rotate_angle(self, pos):
        """Get the angle of the given position towards the event anchor."""

        diff = pos - self.event_anchor
        return -math.degrees(math.atan2(diff.x(), diff.y()))

    def get_rotate_delta(self, pos, snap=False):
        """Get the rotate delta for the current mouse movement.

        If ``snap`` is True, snap to 15 degree units."""

        delta = self.get_rotate_angle(pos) - self.rotate_start_angle
        if snap:
            target = utils.round_to(self.rotate_orig_degrees + delta, 15)
            delta = target - self.rotate_orig_degrees

        return delta

    def get_corner_scale_cursor(self, corner):
        """Gets the scale cursor for the given corner or midpoint."""
        r = self.bounding_rect_unselected()
        eps = 1.0  # Tolerance in item-space
        
        # Check midpoints first (vertical/horizontal)
        if abs(corner.x() - r.center().x()) < eps: # Top or bottom midpoint
            rotation = self.rotation() % 180
            if 45 < rotation < 135:
                return Qt.CursorShape.SizeHorCursor
            return Qt.CursorShape.SizeVerCursor
        if abs(corner.y() - r.center().y()) < eps: # Left or right midpoint
            rotation = self.rotation() % 180
            if 45 < rotation < 135:
                return Qt.CursorShape.SizeVerCursor
            return Qt.CursorShape.SizeHorCursor

        # It's a corner (diagonal)
        is_topleft_or_bottomright = corner in (
            r.topLeft(),
            r.bottomRight())
        return self.get_diag_cursor(is_topleft_or_bottomright)

    def get_diag_cursor(self, is_topleft_or_bottomright):
        rotation = self.rotation() % 180
        flipped = self.flip() == -1

        if is_topleft_or_bottomright:
            if 22.5 < rotation < 67.5:
                return Qt.CursorShape.SizeVerCursor
            elif 67.5 < rotation < 112.5:
                return (Qt.CursorShape.SizeFDiagCursor if flipped
                        else Qt.CursorShape.SizeBDiagCursor)
            elif 112.5 < rotation < 157.5:
                return Qt.CursorShape.SizeHorCursor
            else:
                return (Qt.CursorShape.SizeBDiagCursor if flipped
                        else Qt.CursorShape.SizeFDiagCursor)
        else:
            if 22.5 < rotation < 67.5:
                return Qt.CursorShape.SizeHorCursor
            elif 67.5 < rotation < 112.5:
                return (Qt.CursorShape.SizeBDiagCursor if flipped
                        else Qt.CursorShape.SizeFDiagCursor)
            elif 112.5 < rotation < 157.5:
                return Qt.CursorShape.SizeVerCursor
            else:
                return (Qt.CursorShape.SizeFDiagCursor if flipped
                        else Qt.CursorShape.SizeBDiagCursor)

    def get_edge_flips_v(self, edge):
        """Returns ``True`` if the given edge invokes a horizontal flip,
        ``False`` if it invokes a vertical flip."""

        if 45 < self.rotation() < 135 or 225 < self.rotation() < 315:
            return not edge['flip_v']
        else:
            return edge['flip_v']

    def mouseMoveEvent(self, event):
        if (event.scenePos() - self.event_start).manhattanLength() > 5:
            self.scene().views()[0].reset_previous_transform()

        if self.active_mode == self.SCALE_MODE:
            factor = self.get_scale_factor(event)
            for item in self.selection_action_items():
                item.setScale(item.scale_orig_factor * factor,
                              item.mapFromScene(self.event_anchor))
            # Explicit update to avoid ghosting artifacts
            if self.scene():
                self.scene().update()
            event.accept()
            return
        if self.active_mode == self.ROTATE_MODE:
            snap = (event.modifiers() == Qt.KeyboardModifier.ControlModifier
                    or event.modifiers() == Qt.KeyboardModifier.ShiftModifier)
            delta = self.get_rotate_delta(event.scenePos(), snap)
            for item in self.selection_action_items():
                item.setRotation(
                    item.rotate_orig_degrees + delta * item.flip(),
                    item.mapFromScene(self.event_anchor))
            # Explicit update to avoid ghosting artifacts
            if self.scene():
                self.scene().update()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.active_mode == self.SCALE_MODE:
            if self.get_scale_factor(event) != 1:
                self.scene().undo_stack.push(
                    commands.ScaleItemsBy(
                        self.selection_action_items(),
                        self.get_scale_factor(event),
                        self.event_anchor,
                        ignore_first_redo=True))
            event.accept()
            self.active_mode = None
            return
        elif self.active_mode == self.ROTATE_MODE:
            snap = (event.modifiers() == Qt.KeyboardModifier.ControlModifier
                    or event.modifiers() == Qt.KeyboardModifier.ShiftModifier)
            self.scene().on_selection_change()
            if self.get_rotate_delta(event.scenePos(), snap) != 0:
                self.scene().undo_stack.push(
                    commands.RotateItemsBy(
                        self.selection_action_items(),
                        self.get_rotate_delta(event.scenePos(), snap),
                        self.event_anchor,
                        ignore_first_redo=True))
            event.accept()
            self.active_mode = None
            return
        self.active_mode = None
        super().mouseReleaseEvent(event)

    def on_view_scale_change(self):
        self.prepareGeometryChange()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedChange:
            self.prepareGeometryChange()
            if hasattr(self, 'on_selected_change'):
                self.on_selected_change(value)
        return super().itemChange(change, value)


class MultiSelectItem(SelectableMixin,
                      QtWidgets.QGraphicsRectItem):
    """The multi selection outline around all selected items."""

    def __init__(self):
        super().__init__()
        logger.debug(f'Initialized {self}')
        self.init_selectable()

    def __str__(self):
        return (f'MultiSelectItem {self.width} x {self.height}')

    def bounding_rect_unselected(self):
        """Returns the base rectangle of the selection. 
        SelectableMixin requires this for hit detection."""
        return self.rect()

    @property
    def width(self):
        return self.rect().width()

    @property
    def height(self):
        return self.rect().height()

    @property
    def center(self):
        return self.rect().center()

    def paint(self, painter, option, widget):
        self.paint_selectable(painter, option, widget)

    def has_selection_outline(self):
        return True

    def has_selection_handles(self):
        return True

    def selection_action_items(self):
        """The items affected by selection actions like scaling and rotating.
        """
        if self.scene():
            return list(self.scene().selectedItems())
        return []

    def lower_behind_selection(self):
        items = self.selection_action_items()
        if items:
            min_z = min(item.zValue() for item in items)
            self.setZValue(min_z - self.scene().Z_STEP)

    def fit_selection_area(self, rect):
        """Updates itself to fit the given selection area."""

        logger.trace(f'Fit selection area to {rect}')

        # Only update when values have changed, otherwise we end up in an
        # infinite event loop sceneChange -> itemChange -> sceneChange ...
        if self.width != rect.width() or self.height != rect.height():
            self.setRect(0, 0, rect.width(), rect.height())
        if self.pos() != rect.topLeft():
            self.setPos(rect.topLeft())
        if self.scale() != 1:
            self.setScale(1)
        if self.rotation() != 0:
            self.setRotation(0)
        if not self.isSelected():
            self.setSelected(True)
        if self.flip() == -1:
            self.setTransform(QtGui.QTransform.fromScale(1, 1))

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            # We still need to be able to select additional images
            # within/"under" the multi select rectangle, so let ctrl+click
            # events pass through
            event.ignore()
            return

        super().mousePressEvent(event)


class RubberbandItem(BaseItemMixin, QtWidgets.QGraphicsRectItem):
    """The outline for the rubber band selection."""

    def __init__(self):
        super().__init__()
        color = QtGui.QColor(SELECT_COLOR)
        color.setAlpha(40)
        self.setBrush(QtGui.QBrush(color))
        pen = QtGui.QPen(QtGui.QColor(0, 0, 0))
        pen.setWidth(1)
        pen.setCosmetic(True)
        self.setPen(pen)

    def __str__(self):
        return (f'RubberbandItem {self.width} x {self.height}')

    def fit(self, point1, point2):
        """Updates itself to fit the two given points."""

        self.setRect(utils.get_rect_from_points(point1, point2))
        logger.trace(f'Updated rubberband {self}')
