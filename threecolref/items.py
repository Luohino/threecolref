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

"""Classes for items that are added to the scene by the user (images,
text).
"""

from collections import defaultdict
from functools import cached_property
import logging
import os.path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem


from threecolref import commands
from threecolref.config import BeeSettings
from threecolref.constants import COLORS
from threecolref.selection import SelectableMixin


logger = logging.getLogger(__name__)

item_registry = {}


def register_item(cls):
    item_registry[cls.TYPE] = cls
    return cls


def sort_by_filename(items):
    """Order items by filename.

    Items with a filename (ordered by filename) first, then items
    without a filename but with a save_id follow (ordered by
    save_id), then remaining items in the order that they have
    been inserted into the scene.
    """

    items_by_filename = []
    items_by_save_id = []
    items_remaining = []

    for item in items:
        if getattr(item, 'filename', None):
            items_by_filename.append(item)
        elif getattr(item, 'save_id', None):
            items_by_save_id.append(item)
        else:
            items_remaining.append(item)

    items_by_filename.sort(key=lambda x: x.filename)
    items_by_save_id.sort(key=lambda x: x.save_id)
    return items_by_filename + items_by_save_id + items_remaining


class BeeItemMixin(SelectableMixin):
    """Base for all items added by the user."""

    def set_pos_center(self, pos):
        """Sets the position using the item's center as the origin point."""

        self.setPos(pos - self.center_scene_coords)

    def has_selection_outline(self):
        return self.isSelected()

    def has_selection_handles(self):
        return (self.isSelected()
                and self.scene()
                and self.scene().has_single_selection())

    def selection_action_items(self):
        """The items affected by selection actions like scaling and rotating.
        """
        return [self]

    def on_selected_change(self, value):
        if (value and self.scene()
                and not self.scene().has_selection()
                and not self.scene().active_mode is None):
            self.bring_to_front()

    def update_from_data(self, **kwargs):
        self.save_id = kwargs.get('save_id', self.save_id)
        self.setPos(kwargs.get('x', self.pos().x()),
                    kwargs.get('y', self.pos().y()))
        self.setZValue(kwargs.get('z', self.zValue()))
        self.setScale(kwargs.get('scale', self.scale()))
        self.setRotation(kwargs.get('rotation', self.rotation()))
        if kwargs.get('flip', 1) != self.flip():
            self.do_flip()


@register_item
class BeePixmapItem(BeeItemMixin, QtWidgets.QGraphicsPixmapItem):
    """Class for images added by the user."""

    TYPE = 'pixmap'
    CROP_HANDLE_SIZE = 15

    def __init__(self, image, filename=None, **kwargs):
        super().__init__(QtGui.QPixmap.fromImage(image))
        self.save_id = None
        self.filename = filename
        self.reset_crop()
        logger.debug(f'Initialized {self}')
        self.is_image = True
        self.crop_mode = False
        self.init_selectable()
        self.settings = BeeSettings()
        self.grayscale = False

    @classmethod
    def create_from_data(self, **kwargs):
        item = kwargs.pop('item')
        data = kwargs.pop('data', {})
        item.filename = item.filename or data.get('filename')
        if 'crop' in data:
            item.crop = QtCore.QRectF(*data['crop'])
        item.setOpacity(data.get('opacity', 1))
        item.grayscale = data.get('grayscale', False)
        return item

    def __str__(self):
        size = self.pixmap().size()
        return (f'Image "{self.filename}" {size.width()} x {size.height()}')

    @property
    def crop(self):
        return self._crop

    @crop.setter
    def crop(self, value):
        logger.debug(f'Setting crop for {self} to {value}')
        self.prepareGeometryChange()
        self._crop = value
        self.update()

    @property
    def grayscale(self):
        return self._grayscale

    @grayscale.setter
    def grayscale(self, value):
        logger.debug('Setting grayscale for {self} to {value}')
        self._grayscale = value
        if value is True:
            # Using the grayscale image format to convert to grayscale
            # loses an image's tranparency. So the straightworward
            # following method gives us an ugly black replacement:
            # img = img.convertToFormat(QtGui.QImage.Format.Format_Grayscale8)

            # Instead, we will fill the background with the current
            # canvas colour, so the issue is only visible if the image
            # overlaps other images. The way we do it here only works
            # as long as the canvas colour is itself grayscale,
            # though.
            img = QtGui.QImage(
                self.pixmap().size(), QtGui.QImage.Format.Format_Grayscale8)
            img.fill(QtGui.QColor(*COLORS['Scene:Canvas']))
            painter = QtGui.QPainter(img)
            painter.drawPixmap(0, 0, self.pixmap())
            painter.end()
            self._grayscale_pixmap = QtGui.QPixmap.fromImage(img)

            # Alternative methods that have their own issues:
            #
            # 1. Use setAlphaChannel of the resulting grayscale
            # image. How do we get the original alpha channel? Using
            # the whole original image also takes color values into
            # account, not just their alpha values.
            #
            # 2. QtWidgets.QGraphicsColorizeEffect() with black colour
            # on the GraphicsItem. This applys to everything the paint
            # method does, so the selection outline/handles will also
            # be gray. setGraphicsEffect is only available on some
            # widgets, so we can't apply it selectively.
            #
            # 3. Going through every pixel and doing it manually — bad
            # performance.
        else:
            self._grayscale_pixmap = None

        self.update()

    def sample_color_at(self, pos):
        ipos = self.mapFromScene(pos)
        if self.grayscale:
            pm = self._grayscale_pixmap
        else:
            pm = self.pixmap()
        img = pm.toImage()

        color = img.pixelColor(int(ipos.x()), int(ipos.y()))
        if color.alpha():
            return color

    def bounding_rect_unselected(self):
        if self.crop_mode:
            return QtWidgets.QGraphicsPixmapItem.boundingRect(self)
        else:
            return self.crop

    def get_extra_save_data(self):
        return {'filename': self.filename,
                'opacity': self.opacity(),
                'grayscale': self.grayscale,
                'crop': [self.crop.topLeft().x(),
                         self.crop.topLeft().y(),
                         self.crop.width(),
                         self.crop.height()]}

    def get_filename_for_export(self, imgformat, save_id_default=None):
        save_id = self.save_id or save_id_default
        assert save_id is not None

        if self.filename:
            basename = os.path.splitext(os.path.basename(self.filename))[0]
            return f'{save_id:04}-{basename}.{imgformat}'
        else:
            return f'{save_id:04}.{imgformat}'

    def get_imgformat(self, img):
        """Determines the format for storing this image."""

        formt = self.settings.valueOrDefault('Items/image_storage_format')

        if formt == 'best':
            # Images with alpha channel and small images are stored as png
            if (img.hasAlphaChannel()
                    or (img.height() < 500 and img.width() < 500)):
                formt = 'png'
            else:
                formt = 'jpg'

        logger.debug(f'Found format {formt} for {self}')
        return formt

    def pixmap_to_bytes(self, apply_grayscale=False, apply_crop=False):
        """Convert the pixmap data to PNG bytestring."""
        barray = QtCore.QByteArray()
        buffer = QtCore.QBuffer(barray)
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        if apply_grayscale and self.grayscale:
            pm = self._grayscale_pixmap
        else:
            pm = self.pixmap()

        if apply_crop:
            pm = pm.copy(self.crop.toRect())

        img = pm.toImage()
        imgformat = self.get_imgformat(img)
        img.save(buffer, imgformat.upper(), quality=90)
        return (barray.data(), imgformat)

    def setPixmap(self, pixmap):
        super().setPixmap(pixmap)
        self.reset_crop()

    def pixmap_from_bytes(self, data):
        """Set image pimap from a bytestring."""
        pixmap = QtGui.QPixmap()
        pixmap.loadFromData(data)
        self.setPixmap(pixmap)

    def create_copy(self):
        item = BeePixmapItem(QtGui.QImage(), self.filename)
        item.setPixmap(self.pixmap())
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        item.setOpacity(self.opacity())
        item.grayscale = self.grayscale
        if self.flip() == -1:
            item.do_flip()
        item.crop = self.crop
        return item

    @cached_property
    def color_gamut(self):
        logger.debug(f'Calculating color gamut for {self}')
        gamut = defaultdict(int)
        img = self.pixmap().toImage()
        # Don't evaluate every pixel for larger images:
        step = max(1, int(max(img.width(), img.height()) / 1000))
        logger.debug(f'Considering every {step}. row/column')

        # Not actually faster than solution below :(
        # ptr = img.bits()
        # size = img.sizeInBytes()
        # pixelsize = int(img.sizeInBytes() / img.width() / img.height())
        # ptr.setsize(size)
        # for pixel in batched(ptr, n=pixelsize):
        #     r, g, b, alpha = tuple(map(ord, pixel))
        #     if 5 < alpha and 5 < r < 250 and 5 < g < 250 and 5 < b < 250:
        #         # Only consider pixels that aren't close to
        #         # transparent, white or black
        #         rgb = QtGui.QColor(r, g, b)
        #         gamut[rgb.hue(), rgb.saturation()] += 1

        for i in range(0, img.width(), step):
            for j in range(0, img.height(), step):
                rgb = img.pixelColor(i, j)
                rgbtuple = (rgb.red(), rgb.blue(), rgb.green())
                if (5 < rgb.alpha()
                        and min(rgbtuple) < 250 and max(rgbtuple) > 5):
                    # Only consider pixels that aren't close to
                    # transparent, white or black
                    gamut[rgb.hue(), rgb.saturation()] += 1

        logger.debug(f'Got {len(gamut)} color gamut values')
        return gamut

    def copy_to_clipboard(self, clipboard):
        clipboard.setPixmap(self.pixmap())

    def reset_crop(self):
        self.crop = QtCore.QRectF(
            0, 0, self.pixmap().size().width(), self.pixmap().size().height())

    @property
    def crop_handle_size(self):
        return self.fixed_length_for_viewport(self.CROP_HANDLE_SIZE)

    def crop_handle_topleft(self):
        topleft = self.crop_temp.topLeft()
        return QtCore.QRectF(
            topleft.x(),
            topleft.y(),
            self.crop_handle_size,
            self.crop_handle_size)

    def crop_handle_bottomleft(self):
        bottomleft = self.crop_temp.bottomLeft()
        return QtCore.QRectF(
            bottomleft.x(),
            bottomleft.y() - self.crop_handle_size,
            self.crop_handle_size,
            self.crop_handle_size)

    def crop_handle_bottomright(self):
        bottomright = self.crop_temp.bottomRight()
        return QtCore.QRectF(
            bottomright.x() - self.crop_handle_size,
            bottomright.y() - self.crop_handle_size,
            self.crop_handle_size,
            self.crop_handle_size)

    def crop_handle_topright(self):
        topright = self.crop_temp.topRight()
        return QtCore.QRectF(
            topright.x() - self.crop_handle_size,
            topright.y(),
            self.crop_handle_size,
            self.crop_handle_size)

    def crop_handles(self):
        return (self.crop_handle_topleft,
                self.crop_handle_bottomleft,
                self.crop_handle_bottomright,
                self.crop_handle_topright)

    def crop_edge_top(self):
        topleft = self.crop_temp.topLeft()
        return QtCore.QRectF(
            topleft.x() + self.crop_handle_size,
            topleft.y(),
            self.crop_temp.width() - 2 * self.crop_handle_size,
            self.crop_handle_size)

    def crop_edge_left(self):
        topleft = self.crop_temp.topLeft()
        return QtCore.QRectF(
            topleft.x(),
            topleft.y() + self.crop_handle_size,
            self.crop_handle_size,
            self.crop_temp.height() - 2 * self.crop_handle_size)

    def crop_edge_bottom(self):
        bottomleft = self.crop_temp.bottomLeft()
        return QtCore.QRectF(
            bottomleft.x() + self.crop_handle_size,
            bottomleft.y() - self.crop_handle_size,
            self.crop_temp.width() - 2 * self.crop_handle_size,
            self.crop_handle_size)

    def crop_edge_right(self):
        topright = self.crop_temp.topRight()
        return QtCore.QRectF(
            topright.x() - self.crop_handle_size,
            topright.y() + self.crop_handle_size,
            self.crop_handle_size,
            self.crop_temp.height() - 2 * self.crop_handle_size)

    def crop_edges(self):
        return (self.crop_edge_top,
                self.crop_edge_left,
                self.crop_edge_bottom,
                self.crop_edge_right)

    def get_crop_handle_cursor(self, handle):
        """Gets the crop cursor for the given handle."""

        is_topleft_or_bottomright = handle in (
            self.crop_handle_topleft, self.crop_handle_bottomright)
        return self.get_diag_cursor(is_topleft_or_bottomright)

    def get_crop_edge_cursor(self, edge):
        """Gets the crop edge cursor for the given edge."""

        top_or_bottom = edge in (
            self.crop_edge_top, self.crop_edge_bottom)
        sideways = (45 < self.rotation() < 135
                    or 225 < self.rotation() < 315)

        if top_or_bottom is sideways:
            return Qt.CursorShape.SizeHorCursor
        else:
            return Qt.CursorShape.SizeVerCursor

    def draw_crop_rect(self, painter, rect):
        """Paint a dotted rectangle for the cropping UI."""
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255))
        pen.setWidth(2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawRect(rect)
        pen.setColor(QtGui.QColor(0, 0, 0))
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawRect(rect)

    def paint(self, painter, option, widget):
        if abs(painter.combinedTransform().m11()) < 2:
            # We want image smoothing, but only for images where we
            # are not zoomed in a lot. This is to ensure that for
            # example icons and pixel sprites can be viewed correctly.
            painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform)

        if self.crop_mode:
            self.paint_debug(painter, option, widget)

            # Darken image outside of cropped area
            painter.drawPixmap(0, 0, self.pixmap())
            path = QtWidgets.QGraphicsPixmapItem.shape(self)
            path.addRect(self.crop_temp)
            color = QtGui.QColor(0, 0, 0)
            color.setAlpha(100)
            painter.setBrush(QtGui.QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path)
            painter.setBrush(QtGui.QBrush())

            for handle in self.crop_handles():
                self.draw_crop_rect(painter, handle())
            self.draw_crop_rect(painter, self.crop_temp)
        else:
            pm = self._grayscale_pixmap if self.grayscale else self.pixmap()
            painter.drawPixmap(self.crop, pm, self.crop)
            self.paint_selectable(painter, option, widget)

    def enter_crop_mode(self):
        logger.debug(f'Entering crop mode on {self}')
        self.prepareGeometryChange()
        self.crop_mode = True
        self.crop_temp = QtCore.QRectF(self.crop)
        self.crop_mode_move = None
        self.crop_mode_event_start = None
        self.grabKeyboard()
        self.update()
        self.scene().crop_item = self

    def exit_crop_mode(self, confirm):
        logger.debug(f'Exiting crop mode with {confirm} on {self}')
        if confirm and self.crop != self.crop_temp:
            self.scene().undo_stack.push(
                commands.CropItem(self, self.crop_temp))
        self.prepareGeometryChange()
        self.crop_mode = False
        self.crop_temp = None
        self.crop_mode_move = None
        self.crop_mode_event_start = None
        self.ungrabKeyboard()
        self.update()
        self.scene().crop_item = None

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.exit_crop_mode(confirm=True)
        elif event.key() == Qt.Key.Key_Escape:
            self.exit_crop_mode(confirm=False)
        else:
            super().keyPressEvent(event)

    def hoverMoveEvent(self, event):
        if not self.crop_mode:
            return super().hoverMoveEvent(event)

        for handle in self.crop_handles():
            if handle().contains(event.pos()):
                self.set_cursor(self.get_crop_handle_cursor(handle))
                return
        for edge in self.crop_edges():
            if edge().contains(event.pos()):
                self.set_cursor(self.get_crop_edge_cursor(edge))
                return
        self.unset_cursor()

    def mousePressEvent(self, event):
        if not self.crop_mode:
            return super().mousePressEvent(event)

        event.accept()
        for handle in self.crop_handles():
            # Click into a handle?
            if handle().contains(event.pos()):
                self.crop_mode_event_start = event.pos()
                self.crop_mode_move = handle
                return
        for edge in self.crop_edges():
            # Click into an edge handle?
            if edge().contains(event.pos()):
                self.crop_mode_event_start = event.pos()
                self.crop_mode_move = edge
                return
        # Click not in handle, end cropping mode:
        self.exit_crop_mode(
            confirm=self.crop_temp.contains(event.pos()))

    def ensure_point_within_crop_bounds(self, point, handle):
        """Returns the point, or the nearest point within the pixmap."""

        if handle == self.crop_handle_topleft:
            topleft = QtCore.QPointF(0, 0)
            bottomright = self.crop_temp.bottomRight()
        if handle == self.crop_handle_bottomleft:
            topleft = QtCore.QPointF(0, self.crop_temp.top())
            bottomright = QtCore.QPointF(
                self.crop_temp.right(), self.pixmap().size().height())
        if handle == self.crop_handle_bottomright:
            topleft = self.crop_temp.topLeft()
            bottomright = QtCore.QPointF(
                self.pixmap().size().width(), self.pixmap().size().height())
        if handle == self.crop_handle_topright:
            topleft = QtCore.QPointF(self.crop_temp.left(), 0)
            bottomright = QtCore.QPointF(
                self.pixmap().size().width(), self.crop_temp.bottom())
        if handle == self.crop_edge_top:
            topleft = QtCore.QPointF(0, 0)
            bottomright = QtCore.QPointF(
                self.pixmap().size().width(), self.crop_temp.bottom())
        if handle == self.crop_edge_bottom:
            topleft = QtCore.QPointF(0, self.crop_temp.top())
            bottomright = QtCore.QPointF(
                self.pixmap().size().width(), self.pixmap().size().height())
        if handle == self.crop_edge_left:
            topleft = QtCore.QPointF(0, 0)
            bottomright = QtCore.QPointF(
                self.crop_temp.right(), self.pixmap().size().height())
        if handle == self.crop_edge_right:
            topleft = QtCore.QPointF(self.crop_temp.left(), 0)
            bottomright = QtCore.QPointF(
                self.pixmap().size().width(), self.pixmap().size().height())

        point.setX(min(bottomright.x(), max(topleft.x(), point.x())))
        point.setY(min(bottomright.y(), max(topleft.y(), point.y())))

        return point

    def mouseMoveEvent(self, event):
        if self.crop_mode and self.crop_mode_event_start:
            diff = event.pos() - self.crop_mode_event_start
            if self.crop_mode_move == self.crop_handle_topleft:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topLeft() + diff, self.crop_mode_move)
                self.crop_temp.setTopLeft(new)
            if self.crop_mode_move == self.crop_handle_bottomleft:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.bottomLeft() + diff, self.crop_mode_move)
                self.crop_temp.setBottomLeft(new)
            if self.crop_mode_move == self.crop_handle_bottomright:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.bottomRight() + diff, self.crop_mode_move)
                self.crop_temp.setBottomRight(new)
            if self.crop_mode_move == self.crop_handle_topright:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topRight() + diff, self.crop_mode_move)
                self.crop_temp.setTopRight(new)
            if self.crop_mode_move == self.crop_edge_top:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topLeft() + diff, self.crop_mode_move)
                self.crop_temp.setTop(new.y())
            if self.crop_mode_move == self.crop_edge_left:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topLeft() + diff, self.crop_mode_move)
                self.crop_temp.setLeft(new.x())
            if self.crop_mode_move == self.crop_edge_bottom:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.bottomLeft() + diff, self.crop_mode_move)
                self.crop_temp.setBottom(new.y())
            if self.crop_mode_move == self.crop_edge_right:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topRight() + diff, self.crop_mode_move)
                self.crop_temp.setRight(new.x())
            self.update()
            self.crop_mode_event_start = event.pos()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.crop_mode:
            self.crop_mode_move = None
            self.crop_mode_event_start = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)


@register_item
class BeeTextItem(BeeItemMixin, QtWidgets.QGraphicsTextItem):
    """Class for rich text added by the user."""

    TYPE = 'text'

    def __init__(self, text=None, html=None, **kwargs):
        super().__init__()
        self.save_id = None
        logger.debug(f'Initialized {self}')
        self.is_image = False
        self.init_selectable()
        self.is_editable = True
        self.edit_mode = False
        self.setDefaultTextColor(QtGui.QColor(*COLORS['Scene:Text']))
        # Load HTML if available, otherwise plain text
        if html:
            self.setHtml(html)
        else:
            self.setPlainText(text or 'Text')

    @classmethod
    def create_from_data(cls, **kwargs):
        data = kwargs.get('data', {})
        item = cls(**data)
        return item

    def __str__(self):
        txt = self.toPlainText()[:40]
        return (f'Text "{txt}"')

    def get_extra_save_data(self):
        return {'text': self.toPlainText(), 'html': self.toHtml()}

    def contains(self, point):
        return self.boundingRect().contains(point)

    def paint(self, painter, option, widget):
        painter.setPen(Qt.PenStyle.NoPen)
        color = QtGui.QColor(0, 0, 0)
        color.setAlpha(40)
        brush = QtGui.QBrush(color)
        painter.setBrush(brush)
        painter.drawRect(QtWidgets.QGraphicsTextItem.boundingRect(self))
        option.state = QtWidgets.QStyle.StateFlag.State_Enabled
        super().paint(painter, option, widget)
        self.paint_selectable(painter, option, widget)

    def create_copy(self):
        item = BeeTextItem(html=self.toHtml())
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        if self.flip() == -1:
            item.do_flip()
        return item

    def enter_edit_mode(self):
        logger.debug(f'Entering edit mode on {self}')
        self.edit_mode = True
        self.old_html = self.toHtml()
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextEditorInteraction)
        self.scene().edit_item = self
        # Show format toolbar
        view = self.scene().views()[0] if self.scene().views() else None
        if view and hasattr(view, '_text_toolbar'):
            view._text_toolbar.show_for_item(self)

    def exit_edit_mode(self, commit=True):
        logger.debug(f'Exiting edit mode on {self}')
        self.edit_mode = False
        # reset selection:
        self.setTextCursor(QtGui.QTextCursor(self.document()))
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.scene().edit_item = None
        # Hide format toolbar
        view = self.scene().views()[0] if self.scene().views() else None
        if view and hasattr(view, '_text_toolbar'):
            view._text_toolbar.hide_from_item()
        if commit:
            self.scene().undo_stack.push(
                commands.ChangeText(self, self.toHtml(), self.old_html))
            if not self.toPlainText().strip():
                logger.debug('Removing empty text item')
                self.scene().undo_stack.push(
                    commands.DeleteItems(self.scene(), [self]))
        else:
            self.setHtml(self.old_html)

    def has_selection_handles(self):
        return super().has_selection_handles() and not self.edit_mode

    def keyPressEvent(self, event):
        # Shift+Enter for newline, bare Enter confirms
        if (event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return)
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            self.exit_edit_mode()
            event.accept()
            return
        if (event.key() == Qt.Key.Key_Escape
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            self.exit_edit_mode(commit=False)
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_to_clipboard(self, clipboard):
        clipboard.setText(self.toPlainText())


@register_item
class BeeErrorItem(BeeItemMixin, QtWidgets.QGraphicsTextItem):
    """Class for displaying error messages when an item can't be loaded
    from a bee file.

    This item will be displayed instead of the original item. It won't
    save to bee files. The original item will be preserved in the bee
    file, unless this item gets deleted by the user, or a new bee file
    is saved.
    """

    TYPE = 'error'

    def __init__(self, text=None, **kwargs):
        super().__init__(text or "Text")
        self.original_save_id = None
        logger.debug(f'Initialized {self}')
        self.is_image = False
        self.init_selectable()
        self.is_editable = False
        self.setDefaultTextColor(QtGui.QColor(*COLORS['Scene:Text']))

    @classmethod
    def create_from_data(cls, **kwargs):
        data = kwargs.get('data', {})
        item = cls(**data)
        return item

    def __str__(self):
        txt = self.toPlainText()[:40]
        return (f'Error "{txt}"')

    def contains(self, point):
        return self.boundingRect().contains(point)

    def paint(self, painter, option, widget):
        painter.setPen(Qt.PenStyle.NoPen)
        color = QtGui.QColor(200, 0, 0)
        brush = QtGui.QBrush(color)
        painter.setBrush(brush)
        painter.drawRect(QtWidgets.QGraphicsTextItem.boundingRect(self))
        option.state = QtWidgets.QStyle.StateFlag.State_Enabled
        super().paint(painter, option, widget)
        self.paint_selectable(painter, option, widget)

    def update_from_data(self, **kwargs):
        self.original_save_id = kwargs.get('save_id', self.original_save_id)
        self.setPos(kwargs.get('x', self.pos().x()),
                    kwargs.get('y', self.pos().y()))
        self.setZValue(kwargs.get('z', self.zValue()))
        self.setScale(kwargs.get('scale', self.scale()))
        self.setRotation(kwargs.get('rotation', self.rotation()))

    def create_copy(self):
        item = BeeErrorItem(self.toPlainText())
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        return item

    def flip(self, *args, **kwargs):
        """Returns the flip value (1 or -1)"""
        # Never display error messages flipped
        return 1

    def do_flip(self, *args, **kwargs):
        """Flips the item."""
        # Never flip error messages
        pass

# Hard cap: max playback rate for videos on canvas (reference board, not NLE)
_VIDEO_MAX_FPS = 12

class ThumbnailQueue(QtCore.QThread):
    """
    Singleton sequential thumbnail extractor and metadata prober.
    
    Processes videos one-by-one to avoid disk contention and GUI freezes.
    Now also performs the initial 'probe' (W, H, FPS) to keep the main thread
    completely free during mass-drop operations.
    """
    result_ready = QtCore.pyqtSignal(object, QtGui.QImage, dict)  # token, image, metadata

    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.start()
        return cls._instance

    def __init__(self):
        super().__init__()
        import queue
        self._queue = queue.Queue()
        self._cancelled = set()

    def request(self, filename, token):
        """Enqueue a thumbnail extraction. Returns the token for cancellation."""
        self._queue.put((filename, token))
        return token

    def cancel(self, token):
        """Mark a token as cancelled — its result will be silently dropped."""
        self._cancelled.add(token)

    def run(self):
        import cv2
        import urllib.request
        from urllib.parse import urlparse, parse_qs
        while True:
            filename, token = self._queue.get()
            if token in self._cancelled:
                self._cancelled.discard(token)
                self._queue.task_done()
                continue
            try:
                # 1. Specialized YouTube/Vimeo/Web Handling
                is_yt_thumbnail = 'i.ytimg.com' in filename
                if 'youtube.com' in filename or 'youtu.be' in filename or is_yt_thumbnail:
                    video_id = None
                    if 'youtu.be/' in filename:
                        video_id = filename.split('/')[-1].split('?')[0]
                    elif is_yt_thumbnail:
                        # e.g. https://i.ytimg.com/vi/bhPHwVsrTo0/mqdefault.jpg
                        # or https://i.ytimg.com/an_webp/bhPHwVsrTo0/...
                        parts = filename.split('/')
                        if 'vi' in parts:
                            video_id = parts[parts.index('vi') + 1]
                        elif 'an_webp' in parts:
                            video_id = parts[parts.index('an_webp') + 1]
                    else:
                        try:
                            parsed = urlparse(filename)
                            video_id = parse_qs(parsed.query).get('v', [None])[0]
                        except Exception:
                            pass
                    
                    if video_id:
                        # Reconstruct YouTube URL if we only had the thumbnail
                        if is_yt_thumbnail:
                            filename = f"https://www.youtube.com/watch?v={video_id}"
                            
                        thumb_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                        headers = {'User-Agent': 'Mozilla/5.0'}
                        data = None
                        try:
                            req = urllib.request.Request(thumb_url, headers=headers)
                            data = urllib.request.urlopen(req, timeout=10).read()
                        except Exception:
                            # Fallback to hqdefault
                            try:
                                thumb_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                                req = urllib.request.Request(thumb_url, headers=headers)
                                data = urllib.request.urlopen(req, timeout=10).read()
                            except Exception:
                                pass
                        
                        if data:
                            qimg = QtGui.QImage.fromData(data)
                            if not qimg.isNull():
                                metadata = {'fps': 30, 'w': qimg.width(), 'h': qimg.height(), 
                                            'is_web': True, 'new_url': filename}
                                self.result_ready.emit(token, qimg, metadata)
                                continue

                # 2. Generic Video Probing
                cap = cv2.VideoCapture(filename)
                if not cap.isOpened():
                    # If local file fails, or it's a non-video URL, skip
                    continue
                
                # Probe metadata
                fps = cap.get(cv2.CAP_PROP_FPS)
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                is_web = filename.startswith(('http://', 'https://'))
                metadata = {'fps': fps, 'w': w, 'h': h, 'is_web': is_web}

                # Extract thumbnail
                total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                if total > 10:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * 0.1))
                ret, frame = cap.read()
                cap.release()
                
                if ret and token not in self._cancelled:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb.shape
                    qimg = QtGui.QImage(rgb.data, w, h, ch * w,
                                        QtGui.QImage.Format.Format_RGB888).copy()
                    self.result_ready.emit(token, qimg, metadata)
            except Exception as e:
                logger.error(f"ThumbnailQueue error for {filename}: {e}")
            finally:
                self._cancelled.discard(token)
                self._queue.task_done()




class LiveDecoderThread(QtCore.QThread):
    """Live frame decoder — only started on double-click."""
    frame_ready = QtCore.pyqtSignal(QtGui.QImage)
    MAX_FPS = 24  # Canvas live playback cap

    def __init__(self, filename, fps, parent=None):
        super().__init__(parent)
        self.filename = filename
        self.interval = 1.0 / min(fps if fps > 0 else 30, self.MAX_FPS)
        self.running = True
        self.paused = False
        self._frame_pending = False

    def on_frame_consumed(self):
        self._frame_pending = False

    def run(self):
        import cv2, time
        cap = cv2.VideoCapture(self.filename)
        if not cap.isOpened():
            return
        while self.running:
            if self.paused:
                time.sleep(0.05)
                continue
            if self._frame_pending:
                time.sleep(0.008)
                continue
            t0 = time.time()
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QtGui.QImage(rgb.data, w, h, ch * w,
                                QtGui.QImage.Format.Format_RGB888).copy()
            self._frame_pending = True
            self.frame_ready.emit(qimg)
            elapsed = time.time() - t0
            wait = self.interval - elapsed
            if wait > 0:
                time.sleep(wait)
        cap.release()

    def stop(self):
        self.running = False
        self.wait()


@register_item
class BeeVideoItem(BeeItemMixin, QtWidgets.QGraphicsPixmapItem):
    """
    Video item using Figma-style thumbnail-first architecture.
    
    On canvas: static thumbnail (zero CPU/GPU).
    On double-click: live playback starts.
    On double-click again (or Escape): stops live playback.
    """

    TYPE = 'video'

    def __init__(self, filename=None, **kwargs):
        super().__init__()
        self.save_id = None
        self.filename = filename
        logger.debug(f'Initialized {self}')
        self.is_image = False
        self.is_video = True
        self._live = False
        self._live_thread = None
        self._thumb_token = None
        self._thumbnail_pixmap = None
        self._fps = 30  # Default until probe finishes
        self._is_web = filename.startswith(('http://', 'https://')) if filename else False

        # 1. Instant placeholder — use a safe default 640x360 until the probe returns
        # This makes the drop operation 100% instant regardless of file count.
        w, h = 640, 360
        placeholder = QtGui.QPixmap(w, h)
        placeholder.fill(QtGui.QColor(25, 25, 25))
        self._draw_play_overlay(placeholder)
        self.setPixmap(placeholder)

        # 2. Queue metadata probe + thumbnail extraction via global singleton
        token = id(self)
        self._thumb_token = token
        queue = ThumbnailQueue.instance()
        queue.result_ready.connect(self._on_queue_result)
        queue.request(filename, token)

        self.init_selectable()

    def __del__(self):
        """Cancel queued thumbnail when item is garbage collected."""
        if self._thumb_token is not None:
            try:
                # Use class check to avoid issues during interpreter shutdown
                if ThumbnailQueue._instance:
                    ThumbnailQueue.instance().cancel(self._thumb_token)
            except Exception:
                pass

    def _draw_play_overlay(self, pixmap):
        """Draw a subtle play triangle on a pixmap in-place."""
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = pixmap.width(), pixmap.height()
        cx, cy = w // 2, h // 2
        r = min(w, h) // 8
        # Semi-transparent circle
        painter.setBrush(QtGui.QColor(255, 255, 255, 60))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawEllipse(QtCore.QPoint(cx, cy), r, r)
        # Play triangle
        tri = QtGui.QPolygon([
            QtCore.QPoint(cx - r // 3, cy - r // 2),
            QtCore.QPoint(cx - r // 3, cy + r // 2),
            QtCore.QPoint(cx + r // 2, cy),
        ])
        painter.setBrush(QtGui.QColor(255, 255, 255, 180))
        painter.drawPolygon(tri)
        painter.end()

    def _on_queue_result(self, token, qimg, metadata):
        """Receive thumbnail from the global queue — only update if token matches."""
        if token != self._thumb_token:
            return
        self._thumb_token = None  # Mark as consumed
        
        # Update probed metadata
        self._fps = metadata.get('fps', 30)
        self._is_web = metadata.get('is_web', self._is_web)
        if 'new_url' in metadata:
            self.filename = metadata['new_url']
            
        if self._fps <= 0:
            self._fps = 30
        
        # If dimensions changed from placeholder, notify the scene
        new_w, new_h = metadata.get('w', 640), metadata.get('h', 360)
        if new_w != self.pixmap().width() or new_h != self.pixmap().height():
            self.prepareGeometryChange()

        px = QtGui.QPixmap.fromImage(qimg)
        self._draw_play_overlay(px)
        self._thumbnail_pixmap = px
        # Only set if not currently playing live
        if not self._live:
            self.setPixmap(px)

    def _on_thumbnail_ready(self, qimg):
        """Legacy — kept for backward compat but not called in new path."""
        px = QtGui.QPixmap.fromImage(qimg)
        self._draw_play_overlay(px)
        self.setPixmap(px)

    def _start_live(self):
        """Begin live playback. For web videos, open in browser."""
        if self._live or not self.filename:
            return
        
        if self._is_web:
            logger.info(f"Opening web video link: {self.filename}")
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.filename))
            return

        logger.info(f"Starting live playback for {self}")
        self._live = True
        self._live_thread = LiveDecoderThread(self.filename, self._fps)
        self._live_thread.frame_ready.connect(self._on_live_frame)
        self._live_thread.start()

    def _stop_live(self):
        """Stop live playback and restore thumbnail."""
        if not self._live:
            return
        logger.info(f"Stopping live playback for {self}")
        self._live = False
        if self._live_thread:
            self._live_thread.stop()
            self._live_thread = None
        
        # Restore thumbnail instantly from cache if we have it
        if self._thumbnail_pixmap:
            self.setPixmap(self._thumbnail_pixmap)
        elif self.filename and self._thumb_token:
            ThumbnailQueue.instance().request(self.filename, self._thumb_token)

    def _on_live_frame(self, qimg):
        if not self._live:
            return
        self.setPixmap(QtGui.QPixmap.fromImage(qimg))
        if self._live_thread:
            self._live_thread.on_frame_consumed()

    def mouseDoubleClickEvent(self, event):
        """Toggle live playback on double-click."""
        if self._live:
            self._stop_live()
        else:
            self._start_live()
        event.accept()

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemSceneHasChanged:
            if self.scene() is None:
                self._stop_live()
        return super().itemChange(change, value)

    def _update_pixmap(self, qimg):
        self.setPixmap(QtGui.QPixmap.fromImage(qimg))

    @classmethod
    def create_from_data(cls, **kwargs):
        data = kwargs.get('data', {})
        item = cls(**data)
        return item

    def __str__(self):
        return f'Video "{self.filename}"'

    def get_extra_save_data(self):
        return {'filename': self.filename}
    
    def video_to_bytes(self):
        """Load video file and return (bytes, extension) for storage."""
        if not self.filename or not os.path.exists(self.filename):
            return None, None
        try:
            with open(self.filename, 'rb') as f:
                video_bytes = f.read()
            # Get file extension
            _, ext = os.path.splitext(self.filename)
            return video_bytes, ext
        except Exception as e:
            logger.error(f'Failed to read video file {self.filename}: {e}')
            return None, None
    
    def get_filename_for_export(self, ext):
        """Return a filename for the video in the storage archive."""
        if not ext:
            ext = os.path.splitext(self.filename)[1] if self.filename else '.mp4'
        # Create a unique name based on the original filename
        base = os.path.splitext(os.path.basename(self.filename))[0]
        return f'videos/{base}{ext}'
    
    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        self.paint_selectable(painter, option, widget)

    def create_copy(self):
        item = BeeVideoItem(self.filename)
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        if self.flip() == -1:
            item.do_flip()
        return item

