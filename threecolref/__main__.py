#!/usr/bin/env python3

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
import platform
import signal
import sys

from PyQt6 import QtCore, QtGui, QtWidgets

from threecolref import constants
# from threecolref.assets import BeeAssets  # Deferred
# from threecolref.utils import create_palette_from_dict  # Deferred
# from threecolref.view import BeeGraphicsView  # Deferred

import ctypes
from ctypes import wintypes

# --- Native Event Helper (Windows Only) ---
if sys.platform.startswith('win'):
    # Windows-specific constants for WM_NCHITTEST
    HTNOWHERE = 0
    HTCLIENT = 1
    HTCAPTION = 2
    HTLEFT = 10
    HTRIGHT = 11
    HTTOP = 12
    HTTOPLEFT = 13
    HTTOPRIGHT = 14
    HTBOTTOM = 15
    HTBOTTOMLEFT = 16
    HTBOTTOMRIGHT = 17
    WM_NCHITTEST = 0x0084

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT)
        ]

    def GET_X_LPARAM(lp):
        return ctypes.c_short(lp & 0xFFFF).value

    def GET_Y_LPARAM(lp):
        return ctypes.c_short((lp >> 16) & 0xFFFF).value
# --- End Native Event Helper ---


logger = logging.getLogger(__name__)


class threecolrefApplication(QtWidgets.QApplication):

    def event(self, event):
        if event.type() == QtCore.QEvent.Type.FileOpen:
            for widget in self.topLevelWidgets():
                if isinstance(widget, threecolrefMainWindow):
                    widget.view.open_from_file(event.file())
                    return True
            return False
        else:
            return super().event(event)


class threecolrefMainWindow(QtWidgets.QMainWindow):
    """Custom signal for window state changes (Qt6 removed windowStateChanged from QWidget)."""
    windowStateChanged = QtCore.pyqtSignal()

    COMPACT_SIZE = QtCore.QSize(200, 150)  # PureRef-style compact floating size

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._dragging_window = False
        self._drag_start_pos = None
        self._is_compact = False
        self._normal_geometry = None
        app.setOrganizationName(constants.APPNAME)
        app.setApplicationName(constants.APPNAME)
        from threecolref.assets import BeeAssets
        self.setWindowIcon(BeeAssets().logo)
        
        # Professional frameless window with native behavior (VS Code style)
        self.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint | 
                            QtCore.Qt.WindowType.Window |
                            QtCore.Qt.WindowType.WindowMinMaxButtonsHint)
        
        from threecolref.view import BeeMainWidget
        self.main_widget = BeeMainWidget(app, self)
        self.view = self.main_widget.view # Keep self.view reference for existing logic
        self._margin = 4  # Standard Windows resize border width (was 18, which caused overlap issues)
        
        default_window_size = QtCore.QSize(500, 300)
        geom = self.view.settings.value('MainWindow/geometry')
        if geom is None:
            self.resize(default_window_size)
        else:
            if not self.restoreGeometry(geom):
                self.resize(default_window_size)
        
        self.setCentralWidget(self.main_widget)
        self.show()

        # Frameless windows often don't receive border mouse events because child
        # widgets cover the full surface. Install event filters on both the app
        # AND the main widget to ensure we catch all mouse events reliably.
        self._resize_filter = _FramelessResizeEventFilter(self)
        self._app.installEventFilter(self._resize_filter)
        # Also install on main widget to catch events that might not bubble up
        self.main_widget.installEventFilter(self._resize_filter)

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.Type.WindowStateChange:
            self.windowStateChanged.emit()
        super().changeEvent(event)

    def toggle_compact(self):
        """PureRef-style: shrink to compact floating widget in center, or restore."""
        if self._is_compact:
            self._restore_from_compact()
        else:
            self._show_compact()

    def _show_compact(self):
        """Shrink window to compact size, centered on screen."""
        if self.isMaximized():
            self.showNormal()
        self._normal_geometry = self.geometry()
        self._is_compact = True
        screen = self.screen().availableGeometry()
        x = screen.center().x() - self.COMPACT_SIZE.width() // 2
        y = screen.center().y() - self.COMPACT_SIZE.height() // 2
        self.setGeometry(int(x), int(y), self.COMPACT_SIZE.width(), self.COMPACT_SIZE.height())
        self.setMinimumSize(self.COMPACT_SIZE)
        self.setMaximumSize(self.COMPACT_SIZE)

    def _restore_from_compact(self):
        """Restore from compact to normal size."""
        self._is_compact = False
        self.setMinimumSize(200, 150)
        self.setMaximumSize(16777215, 16777215)  # QWIDGETSIZE_MAX
        if self._normal_geometry:
            self.setGeometry(self._normal_geometry)
        self._normal_geometry = None

    def mouseDoubleClickEvent(self, event):
        """Double-click compact window to restore."""
        if self._is_compact and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._restore_from_compact()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _resize_edges_at_pos(self, pos: QtCore.QPoint):
        """Return QtCore.Qt.Edges for a position in window coordinates."""
        # Use a slightly generous tolerance so the resize zone is easy to hit
        m = self._margin
        w = self.width()
        h = self.height()

        # PyQt6 doesn't expose a Qt.Edges() constructor; build flags via Qt.Edge(0)
        edges = QtCore.Qt.Edge(0)
        
        # Check left edge FIRST (don't use elif - check independently)
        if pos.x() <= m:
            edges |= QtCore.Qt.Edge.LeftEdge
        # Check right edge independently
        if pos.x() >= w - m:
            edges |= QtCore.Qt.Edge.RightEdge
        
        # Check top edge
        if pos.y() <= m:
            edges |= QtCore.Qt.Edge.TopEdge
        # Check bottom edge independently  
        if pos.y() >= h - m:
            edges |= QtCore.Qt.Edge.BottomEdge
            
        return edges

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            edges = self._resize_edges_at_pos(event.position().toPoint())
            wh = self.windowHandle()
            if edges and wh is not None:
                wh.startSystemResize(edges)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        edges = self._resize_edges_at_pos(event.position().toPoint())
        if edges:
            # Corners
            if (edges & QtCore.Qt.Edge.LeftEdge and edges & QtCore.Qt.Edge.TopEdge) or (
                edges & QtCore.Qt.Edge.RightEdge and edges & QtCore.Qt.Edge.BottomEdge
            ):
                self.setCursor(QtCore.Qt.CursorShape.SizeFDiagCursor)
            elif (edges & QtCore.Qt.Edge.RightEdge and edges & QtCore.Qt.Edge.TopEdge) or (
                edges & QtCore.Qt.Edge.LeftEdge and edges & QtCore.Qt.Edge.BottomEdge
            ):
                self.setCursor(QtCore.Qt.CursorShape.SizeBDiagCursor)
            elif edges & (QtCore.Qt.Edge.LeftEdge | QtCore.Qt.Edge.RightEdge):
                self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(QtCore.Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)


    def resizeEvent(self, event):
        super().resizeEvent(event)

    def closeEvent(self, event):
        # If autosave is enabled and there are unsaved changes, save immediately before closing
        logger.debug(f'closeEvent: autosave_enabled={self.view.autosave_enabled}, filename={bool(self.view.filename)}, isClean={self.view.undo_stack.isClean()}')
        
        if self.view.autosave_enabled and self.view.filename:
            if not self.view.undo_stack.isClean():
                try:
                    logger.debug(f'CLOSEVENT AUTOSAVE: saving {self.view.filename} before exit')
                    # Directly save without checking if clean, force it
                    import os
                    filename = self.view.filename
                    if not filename.lower().endswith('.3col'):
                        filename = f'{filename}.3col'
                    from threecolref.fileio.sql import SQLiteIO
                    logger.debug(f'Creating SQLiteIO for {filename}...')
                    io = SQLiteIO(filename, self.view.scene, create_new=False)
                    logger.debug(f'Calling io.write()...')
                    io.write()
                    logger.debug(f'write() completed, closing connection...')
                    # CRITICAL: Close the connection to force the file to be flushed to disk
                    io._close_connection()
                    logger.debug(f'Connection closed')
                    
                    # Verify file was written
                    if os.path.exists(filename):
                        file_size = os.path.getsize(filename)
                        logger.debug(f'CLOSEVENT AUTOSAVE: file written successfully, size={file_size} bytes')
                    else:
                        logger.error(f'CLOSEVENT AUTOSAVE: file {filename} does not exist after write!')
                    
                    self.view.undo_stack.setClean()
                    logger.debug(f'CLOSEVENT AUTOSAVE COMPLETED for {filename}')
                except Exception as e:
                    logger.error(f'Failed to autosave on close: {e}', exc_info=True)
            else:
                logger.debug(f'closeEvent: undo stack is already clean, no autosave needed')
        else:
            logger.debug(f'closeEvent: autosave not applicable (enabled={self.view.autosave_enabled}, has_file={bool(self.view.filename)})')
        
        # Check for unsaved changes before closing
        if not self.view.get_confirmation_unsaved_changes():
            event.ignore()
            return

        # Remove global event filter before shutdown
        try:
            if hasattr(self, "_app") and hasattr(self, "_resize_filter"):
                self._app.removeEventFilter(self._resize_filter)
        except Exception:
            pass
        geom = self.saveGeometry()
        self.view.settings.setValue('MainWindow/geometry', geom)
        super().closeEvent(event)



class _FramelessResizeEventFilter(QtCore.QObject):
    """Enable native edge/corner resizing on a frameless window."""

    def __init__(self, main_window: threecolrefMainWindow):
        super().__init__(main_window)
        self._w = main_window
        self._resize_cursor_active = False

    def _cursor_for_edges(self, edges):
        Qt = QtCore.Qt
        if (edges & Qt.Edge.LeftEdge and edges & Qt.Edge.TopEdge) or (
            edges & Qt.Edge.RightEdge and edges & Qt.Edge.BottomEdge
        ):
            return Qt.CursorShape.SizeFDiagCursor
        if (edges & Qt.Edge.RightEdge and edges & Qt.Edge.TopEdge) or (
            edges & Qt.Edge.LeftEdge and edges & Qt.Edge.BottomEdge
        ):
            return Qt.CursorShape.SizeBDiagCursor
        if edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeHorCursor
        if edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeVerCursor
        return None

    def eventFilter(self, watched, event):
        try:
            # Handle both QWidget and QApplication events
            if isinstance(watched, QtWidgets.QWidget):
                if watched.window() is not self._w:
                    return False
            elif not isinstance(watched, QtWidgets.QApplication):
                return False

            et = event.type()
            Qt = QtCore.Qt

            if et == QtCore.QEvent.Type.MouseMove:
                # Don't show resize cursors when maximized
                if self._w.isMaximized():
                    if self._resize_cursor_active:
                        QtWidgets.QApplication.restoreOverrideCursor()
                        self._resize_cursor_active = False
                    return False

                # Always use global position for consistent edge detection
                if hasattr(event, 'globalPosition'):
                    global_pos = event.globalPosition().toPoint()
                else:
                    # Fallback for older Qt versions
                    global_pos = event.globalPos()
                
                win_pos = self._w.mapFromGlobal(global_pos)
                
                # Check if mouse is near any edge (with generous margin)
                w = self._w.width()
                h = self._w.height()
                m = self._w._margin
                
                # Always check edges, even slightly outside bounds for better UX
                edges = QtCore.Qt.Edge(0)
                if win_pos.x() <= m:
                    edges |= QtCore.Qt.Edge.LeftEdge
                if win_pos.x() >= w - m:
                    edges |= QtCore.Qt.Edge.RightEdge
                if win_pos.y() <= m:
                    edges |= QtCore.Qt.Edge.TopEdge
                if win_pos.y() >= h - m:
                    edges |= QtCore.Qt.Edge.BottomEdge
                
                cursor = self._cursor_for_edges(edges)
                if cursor is not None:
                    # Use override cursor so it takes priority over child widget cursors
                    if not self._resize_cursor_active:
                        QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(cursor))
                        self._resize_cursor_active = True
                    else:
                        QtWidgets.QApplication.changeOverrideCursor(QtGui.QCursor(cursor))
                else:
                    if self._resize_cursor_active:
                        QtWidgets.QApplication.restoreOverrideCursor()
                        self._resize_cursor_active = False
                
                return False

            if et == QtCore.QEvent.Type.Leave:
                if self._resize_cursor_active:
                    QtWidgets.QApplication.restoreOverrideCursor()
                    self._resize_cursor_active = False
                return False

            if et == QtCore.QEvent.Type.MouseButtonPress:
                if event.button() != Qt.MouseButton.LeftButton:
                    return False
                
                # Don't allow resize when maximized
                if self._w.isMaximized():
                    return False

                # Use global position for resize detection
                if hasattr(event, 'globalPosition'):
                    global_pos = event.globalPosition().toPoint()
                else:
                    global_pos = event.globalPos()
                    
                win_pos = self._w.mapFromGlobal(global_pos)
                edges = self._w._resize_edges_at_pos(win_pos)
                wh = self._w.windowHandle()
                if edges and wh is not None:
                    if self._resize_cursor_active:
                        QtWidgets.QApplication.restoreOverrideCursor()
                        self._resize_cursor_active = False
                    wh.startSystemResize(edges)
                    event.accept()
                    return True

        except Exception:
            # Never crash - just fail silently
            if self._resize_cursor_active:
                try:
                    QtWidgets.QApplication.restoreOverrideCursor()
                except Exception:
                    pass
                self._resize_cursor_active = False
            return False

        return False


def safe_timer(timeout, func, *args, **kwargs):
    """Create a timer that is safe against garbage collection and
    overlapping calls.
    See: http://ralsina.me/weblog/posts/BB974.html
    """
    def timer_event():
        try:
            func(*args, **kwargs)
        finally:
            QtCore.QTimer.singleShot(timeout, timer_event)
    QtCore.QTimer.singleShot(timeout, timer_event)


def handle_sigint(signum, frame):
    logger.info('Received interrupt. Exiting...')
    QtWidgets.QApplication.quit()


def handle_uncaught_exception(exc_type, exc, traceback):
    logger.critical('Unhandled exception',
                    exc_info=(exc_type, exc, traceback))
    QtWidgets.QApplication.quit()


sys.excepthook = handle_uncaught_exception


def main():
    from threecolref.config import CommandlineArgs, BeeSettings, logfile_name
    logger.info(f'Starting {constants.APPNAME} version {constants.VERSION}')
    logger.debug('System: %s', ' '.join(platform.uname()))
    logger.debug('Python: %s', platform.python_version())
    logger.debug('LD_LIBRARY_PATH: %s', os.environ.get('LD_LIBRARY_PATH'))
    settings = BeeSettings()
    logger.info(f'Using settings: {settings.fileName()}')
    logger.info(f'Logging to: {logfile_name()}')
    settings.on_startup()
    args = CommandlineArgs(with_check=True)  # Force checking
    assert not args.debug_raise_error, args.debug_raise_error

    QtCore.QCoreApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    os.environ["QT_DEBUG_PLUGINS"] = "1"
    app = threecolrefApplication(sys.argv)
    from threecolref.utils import create_palette_from_dict
    palette = create_palette_from_dict(constants.COLORS)
    app.setPalette(palette)
    
    # Imports for main window
    import threecolref.view  # Ensure view is available if needed, though MainWindow handles it
    bee = threecolrefMainWindow(app)  # NOQA:F841

    signal.signal(signal.SIGINT, handle_sigint)
    # Repeatedly run python-noop to give the interpreter time to
    # handle signals
    safe_timer(50, lambda: None)

    app.exec()
    del bee
    del app
    logger.debug('threecolref closed')
    QtCore.qInstallMessageHandler(None)


if __name__ == '__main__':
    main()  # pragma: no cover
