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
# Balanced: 15px inside, 15px outside for high-response border hits (30px total gutter).
INTERACT_INSIDE_MARGIN = 15


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
        
        # FIGMA-STYLE SYNC: Bypass anchor preservation if this change is coming 
        # from a remote peer. Remote updates use absolute scene coordinates; 
        # forcing an anchor reposition here causes "drift" or "jumping".
        is_remote = False
        try:
            if hasattr(self, 'scene') and self.scene():
                for view in self.scene().views():
                    if hasattr(view, 'collab') and view.collab.applying_remote:
                        is_remote = True
                        break
        except Exception:
            pass

        if is_remote:
            func(self, *args, **kwargs)
            return

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
        # FIGMA-STYLE LAYERING: Parented items (doodles) can go behind parent image
        if self.parentItem():
            flag = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent
            self.setFlag(flag, value < 0)

    def bring_to_front(self):
        if self.parentItem():
            siblings = self.parentItem().childItems()
            sib_z = [s.zValue() for s in siblings]
            z_step = 0.001
            if self.scene():
                z_step = self.scene().Z_STEP
            self.setZValue(max(0.001, max(sib_z) if sib_z else 0.001) + z_step)
        else:
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
        """Must be overridden by subclasses to return raw geometry without calling super().boundingRect()."""
        raise NotImplementedError("Subclasses must implement bounding_rect_unselected using raw data.")

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
        
        # Guard against redundant cursor updates which can cause RecursionError
        # during high-frequency events like HoverMove
        if not hasattr(self, '_current_cursor_shape'):
            self._current_cursor_shape = None
            
        new_shape = cursor.shape() if isinstance(cursor, QtGui.QCursor) else cursor
        if self._current_cursor_shape == new_shape:
            return
            
        self._current_cursor_shape = new_shape
        if self.scene():
            self.scene().cursor_changed.emit(cursor)

    def unset_cursor(self):
        # Can't use unsetCursor on the item itself because of bug
        # https://bugreports.qt.io/browse/QTBUG-4190
        if getattr(self, '_current_cursor_shape', None) is None:
            return
        self._current_cursor_shape = None
        if self.scene():
            self.scene().cursor_cleared.emit()

    def sample_color_at(self, pos):
        return None


class SelectableMixin(BaseItemMixin):
    """Common code for selectable items: Selection outline, handles etc."""

    SELECT_LINE_WIDTH = 2  # cleaner, thinner line
    SELECT_HANDLE_SIZE = 8  # sharp, subtle scaling handles
    SELECT_RESIZE_SIZE = 10  # High-response hit zone (30px total gutter)
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

        if self.scene() and self.scene().views():
            scale = self.scene().views()[0].get_scale()
            self._view_scale = scale

        # It can happen that the item is already removed from
        # the scene but its boundingRect is still needed. Keep the
        # last known scaling factor for that case
        val = value / getattr(self, '_view_scale', 1) / self.scale()
        # No clamping allowed! Clamping causes the on-screen hit zone to explode when 
        # zoomed in and shrink when zoomed out. Mathematical val scaling perfectly preserves 
        # exactly the desired screen-pixel dimension at any zoom.
        return val

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

        # Rotation handle removed for PureRef-style Ctrl+Drag interaction
        pass

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
        """Clickable area for all 4 edges, always centered exactly on the border line."""
        r = self.bounding_rect_unselected()
        strip = self.select_resize_size
        m = strip / 2  # half-strip overhang on each side for the endpoint caps
        b = strip / 2  # Always center the strip on the border (half inside, half outside)
        return [
            # Top edge: strip centered on top border
            {'rect': QtCore.QRectF(r.left() - m, r.top() - b, r.width() + 2*m, strip), 'pt': self.edge_midpoints[0]},
            # Bottom edge: strip centered on bottom border
            {'rect': QtCore.QRectF(r.left() - m, r.bottom() - b, r.width() + 2*m, strip), 'pt': self.edge_midpoints[1]},
            # Left edge: strip centered on left border
            {'rect': QtCore.QRectF(r.left() - b, r.top() - m, strip, r.height() + 2*m), 'pt': self.edge_midpoints[2]},
            # Right edge: strip centered on right border
            {'rect': QtCore.QRectF(r.right() - b, r.top() - m, strip, r.height() + 2*m), 'pt': self.edge_midpoints[3]},
        ]

    @property
    def corners_scene_coords(self):
        """The corners of the item mapped to scene coordinates."""

        return [self.mapToScene(corner) for corner in self.corners]

    def get_scale_bounds(self, corner, margin=0):
        """The interactable shape of the scale handles, always centered on the corner point."""
        path = QtGui.QPainterPath()
        size = self.select_resize_size + 2 * margin
        # Center the rect on the corner point — no bias shift needed.
        # This means equal coverage inside and outside each corner.
        path.addRect(QtCore.QRectF(
            corner.x() - size / 2,
            corner.y() - size / 2,
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
        if hasattr(self, '_in_bounding_rect'):
            return self.bounding_rect_unselected()
        
        self._in_bounding_rect = True
        try:
            if not self.has_selection_outline():
                return self.bounding_rect_unselected()

            # Only extend for the resize gutter. The old rotation handle
            # margin (SELECT_ROTATE_OFFSET + SELECT_ROTATE_HANDLE_SIZE = 45px)
            # was removed since we now use Ctrl+drag-anywhere for rotation.
            # This prevents hover events from firing 60px from the visible border.
            margin = self.select_resize_size / 2
            return self.bounding_rect_unselected().marginsAdded(
                QtCore.QMarginsF(margin, margin, margin, margin))
        finally:
            del self._in_bounding_rect

    def shape(self):
        if hasattr(self, '_in_shape'):
            path = QtGui.QPainterPath()
            path.addRect(self.bounding_rect_unselected())
            return path
            
        self._in_shape = True
        try:
            path = QtGui.QPainterPath()
            if self.has_selection_handles():
                margin = self.select_resize_size / 2
                rect = self.bounding_rect_unselected().marginsAdded(
                    QtCore.QMarginsF(margin, margin, margin, margin))
                path.addRect(rect)
                # Note: get_edge_scale_path() is no longer needed here as the 
                # fully expanded margin rect perfectly covers all edge interactions.
            else:
                rect = self.bounding_rect_unselected()
                path.addRect(rect)
            return path
        finally:
            del self._in_shape

    def hoverMoveEvent(self, event):
        if not self.isSelected():
            self.unset_cursor()
            return

        pos = event.pos()

        # In a multi-selection, individual items don't show transform cursors.
        if not self.has_selection_handles() and not isinstance(self, MultiSelectItem):
            self.set_cursor(Qt.CursorShape.ArrowCursor)
            return
        
        # PureRef style: Show rotation cursor if Ctrl is held
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.set_cursor(Qt.CursorShape.PointingHandCursor)
            return

        # --- DIRECT DISTANCE-FROM-BORDER APPROACH ---
        # Instead of complex path intersection, just check distance from each edge.
        # This is mathematically guaranteed to work for any resize size value.
        r = self.bounding_rect_unselected()
        half = self.select_resize_size / 2

        near_left   = abs(pos.x() - r.left())   <= half
        near_right  = abs(pos.x() - r.right())  <= half
        near_top    = abs(pos.y() - r.top())     <= half
        near_bottom = abs(pos.y() - r.bottom())  <= half

        within_x = r.left() - half <= pos.x() <= r.right() + half
        within_y = r.top() - half  <= pos.y() <= r.bottom() + half

        if not (near_left or near_right or near_top or near_bottom):
            # Not near any border → inside the item → Arrow
            self.set_cursor(Qt.CursorShape.ArrowCursor)
            return

        # Find the closest reference point to get the correct directional cursor
        if near_top and near_left:
            ref_pt = r.topLeft()
        elif near_top and near_right:
            ref_pt = r.topRight()
        elif near_bottom and near_left:
            ref_pt = r.bottomLeft()
        elif near_bottom and near_right:
            ref_pt = r.bottomRight()
        elif near_top and within_x:
            ref_pt = QtCore.QPointF(r.center().x(), r.top())
        elif near_bottom and within_x:
            ref_pt = QtCore.QPointF(r.center().x(), r.bottom())
        elif near_left and within_y:
            ref_pt = QtCore.QPointF(r.left(), r.center().y())
        elif near_right and within_y:
            ref_pt = QtCore.QPointF(r.right(), r.center().y())
        else:
            self.set_cursor(Qt.CursorShape.ArrowCursor)
            return

        self.set_cursor(self.get_corner_scale_cursor(ref_pt))

    def hoverLeaveEvent(self, event):
        self.unset_cursor()

    def mousePressEvent(self, event):
        self.event_start = event.scenePos()
        self.scene().views()[0].reset_previous_transform(toggle_item=self)
        if not self.isSelected():
            # User has just selected this item with this click; don't
            # activate any transformations yet.
            super().mousePressEvent(event)
            return

        # STABILITY: If we are clicking a selected item but NOT in a transform
        # zone, force Arrow cursor to prevent the brief "Hand" icon flicker.
        in_zone = self.is_in_transform_zone(event.pos())
        if not in_zone:
            # PureRef style: holding Ctrl allows rotation ANYWHERE on the item
            if (event.button() == Qt.MouseButton.LeftButton 
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
                pass # Allow process to continue to mode selection below
            else:
                self.set_cursor(Qt.CursorShape.ArrowCursor)
                super().mousePressEvent(event)
                return

        if (event.button() == Qt.MouseButton.LeftButton
                and self.has_selection_handles()):
            pos = event.pos()
            
            # PureRef style: Ctrl+Drag ANYWHERE on/near the selection triggers rotation
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self.active_mode = self.ROTATE_MODE
                self.event_anchor = self.center_scene_coords
                self.rotate_start_angle = self.get_rotate_angle(event.scenePos())
                for item in self.selection_action_items():
                    item.rotate_orig_degrees = item.rotation()
                event.accept()
                return

            # Priority 1: The 8 circular handles - generous 40px hit zones
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

            # Priority 2: Continuous Border Scaling (edges and corners)
            edge_hit = self.get_edge_scale_path().contains(pos)
            if edge_hit:
                edge_pt = self.get_closest_transform_point(pos)
                self.active_mode = self.SCALE_MODE
                self.event_direction = self.get_direction_from_center(event.scenePos())
                self.event_anchor = self.mapToScene(self.get_scale_anchor(edge_pt))
                for item in self.selection_action_items():
                    item.scale_orig_factor = item.scale()
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
            scene = self.scene()
            if scene:
                scene._updating_scene = True
            try:
                for item in self.selection_action_items():
                    item.setScale(item.scale_orig_factor * factor,
                                  item.mapFromScene(self.event_anchor))
            finally:
                if scene:
                    scene._updating_scene = False
                    if scene.has_multi_selection() and scene.multi_select_item.scene():
                        scene.multi_select_item.fit_selection_area(scene.itemsBoundingRect(selection_only=True))
            # Live collab: broadcast scale during drag (throttled ~30fps)
            scene = self.scene()
            if scene:
                mgr = scene._get_collab_manager() if hasattr(scene, '_get_collab_manager') else None
                if mgr and mgr.is_active and not mgr.applying_remote:
                    import time as _t
                    now = _t.monotonic() * 1000
                    if not hasattr(self, '_last_scale_bc'):
                        self._last_scale_bc = 0
                    if now - self._last_scale_bc >= 33:
                        self._last_scale_bc = now
                        for item in self.selection_action_items():
                            if hasattr(item, 'ensure_collab_id'):
                                mgr.broadcast_item_transformed(
                                    [item.ensure_collab_id()], 'scale',
                                    scale=item.scale(),
                                    x=item.pos().x(), y=item.pos().y())
            # Explicit update to avoid ghosting artifacts
            if self.scene():
                self.scene().update()
            event.accept()
            return
        if self.active_mode == self.ROTATE_MODE:
            snap = (event.modifiers() == Qt.KeyboardModifier.ControlModifier
                    or event.modifiers() == Qt.KeyboardModifier.ShiftModifier)
            delta = self.get_rotate_delta(event.scenePos(), snap)
            scene = self.scene()
            if scene:
                scene._updating_scene = True
            try:
                for item in self.selection_action_items():
                    item.setRotation(
                        item.rotate_orig_degrees + delta * item.flip(),
                        item.mapFromScene(self.event_anchor))
            finally:
                if scene:
                    scene._updating_scene = False
                    if scene.has_multi_selection() and scene.multi_select_item.scene():
                        scene.multi_select_item.fit_selection_area(scene.itemsBoundingRect(selection_only=True))
            # Live collab: broadcast rotation during drag (throttled ~30fps)
            scene = self.scene()
            if scene:
                mgr = scene._get_collab_manager() if hasattr(scene, '_get_collab_manager') else None
                if mgr and mgr.is_active and not mgr.applying_remote:
                    import time as _t
                    now = _t.monotonic() * 1000
                    if not hasattr(self, '_last_rotate_bc'):
                        self._last_rotate_bc = 0
                    if now - self._last_rotate_bc >= 33:
                        self._last_rotate_bc = now
                        for item in self.selection_action_items():
                            if hasattr(item, 'ensure_collab_id'):
                                mgr.broadcast_item_transformed(
                                    [item.ensure_collab_id()], 'rotate',
                                    rotation=item.rotation(),
                                    x=item.pos().x(), y=item.pos().y())
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
                # Broadcast final scale (ignore_first_redo skips _broadcast in redo)
                scene = self.scene()
                if scene:
                    mgr = scene._get_collab_manager() if hasattr(scene, '_get_collab_manager') else None
                    if mgr and mgr.is_active and not mgr.applying_remote:
                        for item in self.selection_action_items():
                            if hasattr(item, 'ensure_collab_id'):
                                mgr.broadcast_item_transformed(
                                    [item.ensure_collab_id()], 'scale',
                                    scale=item.scale(),
                                    x=item.pos().x(), y=item.pos().y())
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
                # Broadcast final rotation (ignore_first_redo skips _broadcast in redo)
                scene = self.scene()
                if scene:
                    mgr = scene._get_collab_manager() if hasattr(scene, '_get_collab_manager') else None
                    if mgr and mgr.is_active and not mgr.applying_remote:
                        for item in self.selection_action_items():
                            if hasattr(item, 'ensure_collab_id'):
                                mgr.broadcast_item_transformed(
                                    [item.ensure_collab_id()], 'rotate',
                                    rotation=item.rotation(),
                                    x=item.pos().x(), y=item.pos().y())
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
        self._fitting = False
        self.init_selectable()
        self.setBrush(QtGui.QBrush(Qt.GlobalColor.transparent))
        self.setPen(QtGui.QPen(Qt.PenStyle.NoPen))  # Border is drawn by paint_selectable

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
            return list(self.scene().selectedItems(user_only=True))
        return []

    def lower_behind_selection(self):
        items = self.selection_action_items()
        if items:
            min_z = min(item.zValue() for item in items)
            self.setZValue(min_z - self.scene().Z_STEP)

    def fit_selection_area(self, rect):
        """Updates itself to fit the given selection area."""
        if self._fitting:
            return
        self._fitting = True
        try:
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
        finally:
            self._fitting = False

    def mousePressEvent(self, event):
        in_zone = self.is_in_transform_zone(event.pos())
        # BORDER ZONE: If the user clicks on the transform border, handle it immediately.
        if in_zone:
            super().mousePressEvent(event)
            return

        # CTRL+CLICK on interior: normally rotate. But if user Ctrl+clicks on a
        # specific selected item, pass through to deselect that individual item.
        if (event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            item = self.scene().itemAt(event.scenePos(), QtGui.QTransform())
            if item and item != self and item.isSelected():
                event.ignore()
                return

        # INTERIOR CLICK / DRAG: call super() so Qt moves all selected items together.
        # This preserves the expected "click and drag inside group to move all" behavior.
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

    def bounding_rect_unselected(self):
        """Returns the base rectangle of the rubberband."""
        return self.rect()

    def __str__(self):
        return (f'RubberbandItem {self.width} x {self.height}')

    def fit(self, point1, point2):
        """Updates itself to fit the two given points."""

        self.setRect(utils.get_rect_from_points(point1, point2))
        logger.trace(f'Updated rubberband {self}')
