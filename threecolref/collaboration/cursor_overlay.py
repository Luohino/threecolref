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

"""Transparent overlay widget that renders remote users' cursors."""

import logging
import time

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)

# Each remote user gets a distinct colour (cycles if >len)
_CURSOR_COLORS = [
    QtGui.QColor(255, 107, 107),   # red
    QtGui.QColor(78, 205, 196),    # teal
    QtGui.QColor(255, 195, 18),    # yellow
    QtGui.QColor(156, 136, 255),   # purple
    QtGui.QColor(46, 213, 115),    # green
    QtGui.QColor(255, 165, 2),     # orange
    QtGui.QColor(116, 185, 255),   # blue
]

# Cursors older than this (ms) are considered stale and hidden.
_STALE_MS = 5000


class RemoteCursorOverlay(QtWidgets.QWidget):
    """Draws a small arrow + username label for every remote cursor."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self._cursors: dict[str, dict] = {}  # user_id -> {x, y, username, ts, color}
        self._color_idx = 0

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet('background: transparent;')

        # Timer to repaint & expire stale cursors
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start(50)  # ~20 fps repaint
        self.show()

    def stop(self):
        self._timer.stop()
        self._cursors.clear()
        self.hide()

    def update_cursor(self, data: dict):
        uid = data.get('user_id', '')
        if uid not in self._cursors:
            color = _CURSOR_COLORS[self._color_idx % len(_CURSOR_COLORS)]
            self._color_idx += 1
            self._cursors[uid] = {'color': color}
        c = self._cursors[uid]
        c['x'] = data.get('x', 0)
        c['y'] = data.get('y', 0)
        c['username'] = data.get('username', uid[:6])
        c['ts'] = time.monotonic() * 1000

    def remove_cursor(self, user_id: str):
        self._cursors.pop(user_id, None)

    def _tick(self):
        now = time.monotonic() * 1000
        stale = [uid for uid, c in self._cursors.items()
                 if now - c.get('ts', 0) > _STALE_MS]
        for uid in stale:
            del self._cursors[uid]
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        if not self._cursors:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        for uid, c in self._cursors.items():
            scene_pt = QtCore.QPointF(c['x'], c['y'])
            view_pt = self.view.mapFromScene(scene_pt)
            color: QtGui.QColor = c['color']
            username = c.get('username', '')

            # --- Arrow cursor ---
            arrow = QtGui.QPolygonF([
                QtCore.QPointF(view_pt.x(), view_pt.y()),
                QtCore.QPointF(view_pt.x(), view_pt.y() + 16),
                QtCore.QPointF(view_pt.x() + 5, view_pt.y() + 12),
                QtCore.QPointF(view_pt.x() + 10, view_pt.y() + 18),
                QtCore.QPointF(view_pt.x() + 13, view_pt.y() + 16),
                QtCore.QPointF(view_pt.x() + 8, view_pt.y() + 10),
                QtCore.QPointF(view_pt.x() + 12, view_pt.y() + 8),
            ])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPolygon(arrow)

            # --- Username label ---
            if username:
                font = QtGui.QFont('Segoe UI', 8)
                painter.setFont(font)
                fm = QtGui.QFontMetrics(font)
                tw = fm.horizontalAdvance(username) + 8
                th = fm.height() + 4
                label_x = view_pt.x() + 14
                label_y = view_pt.y() + 16

                bg = QtGui.QColor(color)
                bg.setAlpha(200)
                painter.setBrush(bg)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(
                    QtCore.QRectF(label_x, label_y, tw, th), 3, 3)

                painter.setPen(QtGui.QColor(255, 255, 255))
                painter.drawText(
                    QtCore.QRectF(label_x + 4, label_y + 2, tw, th),
                    Qt.AlignmentFlag.AlignLeft,
                    username)

        painter.end()
