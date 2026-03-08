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

"""Small status pill shown in the bottom-right corner of the view when
a collaboration session is active."""

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt


class CollaborationStatusWidget(QtWidgets.QWidget):
    """Displays a coloured dot + brief text (e.g. '● 2 users')."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(26)
        # Removed WA_TransparentForMouseEvents to allow interaction
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet('background: transparent;')
        self._status = 'disconnected'
        self._user_count = 0
        self._hovered = False
        self.hide()

    def set_status(self, status: str):
        self._status = status
        if status == 'disconnected':
            self.hide()
        else:
            self.show()
        self._update_size()
        self.update()

    def set_user_count(self, count: int):
        self._user_count = count
        self._update_size()
        self.update()

    def _label_text(self):
        if self._status == 'hosting':
            return f'Hosting  ·  {self._user_count} user{"s" if self._user_count != 1 else ""}'
        elif self._status == 'connected':
            return f'Connected  ·  {self._user_count} user{"s" if self._user_count != 1 else ""}'
        return ''

    def _dot_color(self):
        if self._status == 'hosting':
            return QtGui.QColor(46, 213, 115)
        elif self._status == 'connected':
            return QtGui.QColor(116, 185, 255)
        return QtGui.QColor(180, 180, 180)

    def _update_size(self):
        fm = QtGui.QFontMetrics(QtGui.QFont('Segoe UI', 9))
        w = fm.horizontalAdvance(self._label_text()) + 28
        self.setFixedWidth(max(w, 60))
        # Position in bottom-right with margin
        if self.parentWidget():
            p = self.parentWidget()
            self.move(p.width() - self.width() - 20, p.height() - self.height() - 20)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            from threecolref.widgets.ios_dialogs import BeeIosUserListDialog
            # Ensure we have access to the manager
            manager = getattr(self.parent(), 'collab', None)
            if manager:
                BeeIosUserListDialog.show_user_list(self.window(), manager)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        if self._status == 'disconnected':
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        # Background pill
        alpha = 240 if self._hovered else 200
        brightness = 45 if self._hovered else 30
        bg = QtGui.QColor(brightness, brightness, brightness, alpha)
        painter.setBrush(bg)
        painter.setPen(Qt.PenStyle.NoPen)
        # Add a subtle border when hovered
        if self._hovered:
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 40), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1) if self._hovered else self.rect(), 13, 13)

        # Dot
        dot_color = self._dot_color()
        painter.setBrush(dot_color)
        painter.drawEllipse(8, 8, 10, 10)

        # Text
        painter.setPen(QtGui.QColor(220, 220, 220))
        painter.setFont(QtGui.QFont('Segoe UI', 9))
        painter.drawText(
            QtCore.QRect(22, 0, self.width() - 26, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._label_text())

        painter.end()
