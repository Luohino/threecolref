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
import os
import os.path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from threecolref.actions import ActionsMixin
from threecolref.actions.actions import bee_actions
from threecolref import commands
from threecolref.collaboration import protocol
from threecolref.collaboration.manager import CollaborationManager
from threecolref.config import CommandlineArgs, BeeSettings, KeyboardSettings
from threecolref import constants
from threecolref import fileio
from threecolref.fileio.errors import IMG_LOADING_ERROR_MSG
# from threecolref.fileio.export import exporter_registry, ImagesToDirectoryExporter  # Deferred
# from threecolref import widgets  # Deferred
from threecolref.items import BeePixmapItem, BeeTextItem
from threecolref.main_controls import MainControlsMixin
from threecolref.scene import BeeGraphicsScene
from threecolref.utils import get_file_extension_from_format, qcolor_to_hex


commandline_args = CommandlineArgs()
logger = logging.getLogger(__name__)


class BeeGraphicsView(MainControlsMixin,
                      QtWidgets.QGraphicsView,
                      ActionsMixin):

    PAN_MODE = 1
    ZOOM_MODE = 2
    SAMPLE_COLOR_MODE = 3

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.host_window = parent
        self.settings = BeeSettings()
        self.keyboard_settings = KeyboardSettings()

        self.setBackgroundBrush(
            QtGui.QBrush(QtGui.QColor(*constants.COLORS['Scene:Canvas'])))
        
        # Enables mouseMoveEvent to fire even when no button is pressed
        self.setMouseTracking(True)
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)

        self.undo_stack = QtGui.QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        self.undo_stack.canRedoChanged.connect(self.on_can_redo_changed)
        self.undo_stack.canUndoChanged.connect(self.on_can_undo_changed)
        self.undo_stack.cleanChanged.connect(self.on_undo_clean_changed)
        
        # Autosave timer
        self.autosave_enabled = self.settings.valueOrDefault('autosave_enabled')
        self.autosave_timer = QtCore.QTimer()
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self._on_autosave_timeout)
        self.autosave_delay = 2000  # 2 seconds
        self.autosave_in_progress = False
        # Only trigger autosave when user makes changes (not during save)
        self.undo_stack.cleanChanged.connect(self._on_undo_clean_changed_for_autosave)

        self.filename = None
        self.previous_transform = None
        self.active_mode = None

        # Debounce timer for expensive scene rect recalculation
        self._recalc_timer = QtCore.QTimer(self)
        self._recalc_timer.setSingleShot(True)
        self._recalc_timer.setInterval(50)
        self._recalc_timer.timeout.connect(self.recalc_scene_rect)

        self.scene = BeeGraphicsScene(self.undo_stack)
        self.scene.changed.connect(self.on_scene_changed)
        self.scene.selectionChanged.connect(self.on_selection_changed)
        self.scene.cursor_changed.connect(self.on_cursor_changed)
        self.scene.cursor_cleared.connect(self.on_cursor_cleared)
        self.setScene(self.scene)

        # Install event filter on viewport so we can reset the cursor when
        # the mouse re-enters the canvas after an OS window resize operation.
        self.viewport().installEventFilter(self)

        from threecolref.widgets.welcome_overlay import WelcomeOverlay
        self.welcome_overlay = WelcomeOverlay(self, view=self)
        self._hierarchy_overlay = None

        from threecolref.widgets.text_toolbar import TextFormatToolbar
        self._text_toolbar = TextFormatToolbar(self)
        self._doodle_toolbar = None

        # Context menu and actions
        self.build_menu_and_actions()
        self.control_target = self
        self.init_main_controls(main_window=parent)
        self.init_watermark()

        # Collaboration
        self.collab = CollaborationManager(parent=self)

        from threecolref.collaboration.cursor_overlay import RemoteCursorOverlay
        self.cursor_overlay = RemoteCursorOverlay(self)
        from threecolref.collaboration.status_widget import CollaborationStatusWidget
        self.collab_status = CollaborationStatusWidget(self)
        self._setup_collab_signals()

        # Phase 2: High-Capacity Batching
        self._remote_item_queue = []
        self._sync_timer = QtCore.QTimer(self)
        self._sync_timer.setInterval(1)  # High frequency but yields to UI
        self._sync_timer.timeout.connect(self._process_remote_queue)

        # Load files given via command line
        if commandline_args.filenames:
            fn = commandline_args.filenames[0]
            if os.path.splitext(fn)[1] in ('.bee', constants.EXTENSION):
                self.open_from_file(fn)
            else:
                self.do_insert_images(commandline_args.filenames)

        self.update_window_title()
        self._is_joining = False

    @property
    def hierarchy_overlay(self):
        if self._hierarchy_overlay is None:
            from threecolref.widgets.hierarchy import HierarchyOverlay
            self._hierarchy_overlay = HierarchyOverlay(self)
            self._hierarchy_overlay.hide()
        return self._hierarchy_overlay

    @property
    def filename(self):
        return self._filename

    @filename.setter
    def filename(self, value):
        self._filename = value
        self.update_window_title()
        if value:
            self.settings.update_recent_files(value)
            self.update_menu_and_actions()

    @property
    def doodle_toolbar(self):
        if self._doodle_toolbar is None:
            from threecolref.widgets.doodle_toolbar import DoodleToolbar
            self._doodle_toolbar = DoodleToolbar(self)
            self._doodle_toolbar.tool_changed.connect(self._on_doodle_tool_changed)
            self._doodle_toolbar.color_changed.connect(self._on_doodle_color_changed)
            self._doodle_toolbar.width_changed.connect(self._on_doodle_width_changed)
            self._doodle_toolbar.undo_clicked.connect(self._on_doodle_undo)
            self._doodle_toolbar.redo_clicked.connect(self._on_doodle_redo)
            self._doodle_toolbar.clear_clicked.connect(self._on_doodle_clear)
            self._doodle_toolbar.closed.connect(self._on_doodle_toolbar_closed)
        return self._doodle_toolbar

    def _on_doodle_tool_changed(self, tool):
        # Exit movewin mode if active
        if getattr(self, 'movewin_active', False):
            self.exit_movewin_mode()
        
        width = int(self.settings.valueOrDefault('Items/doodle_width') or 4)
        if tool == 'select':
            self.scene.active_mode = None
            self.viewport().unsetCursor()
        elif tool == 'eraser':
            self.scene.active_mode = self.scene.ERASE_MODE
            cursor = self._create_circular_cursor(width, QtGui.QColor('#FFFFFF'))
            self.viewport().setCursor(cursor)
        else:
            # Pencil or shapes
            self.scene.active_mode = self.scene.DRAW_MODE
            self.scene.active_tool = tool
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    def _on_doodle_color_changed(self, color_hex):
        self.scene.settings.setValue('Items/doodle_color', color_hex)

    def _on_doodle_width_changed(self, width):
        self.scene.settings.setValue('Items/doodle_width', width)
        # Update cursor if in eraser mode
        if self.scene.active_mode == self.scene.ERASE_MODE:
            self.viewport().setCursor(self._create_circular_cursor(width, QtGui.QColor('#FFFFFF')))

    def _on_doodle_undo(self):
        self.undo_stack.undo()

    def _on_doodle_redo(self):
        self.undo_stack.redo()

    def _on_doodle_clear(self):
        msg = "Are you sure you want to clear all doodles?"
        if QtWidgets.QMessageBox.question(self, "Clear All", msg) == QtWidgets.QMessageBox.StandardButton.Yes:
            self.scene.clear_doodles()

    def _create_circular_cursor(self, width, color):
        """Creates a circular cursor matching the stroke width."""
        # Scale width based on view zoom if needed, but for UI cursors, 
        # usually 1:1 screen space is best unless we want to match scene space.
        # Let's keep it simple: pixel size 12-64
        size = max(12, min(width, 128))
        pixmap = QtGui.QPixmap(size + 2, size + 2)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QtGui.QPainter()
        if not painter.begin(pixmap):
            return QtGui.QCursor(Qt.CursorShape.CrossCursor)
            
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pen = QtGui.QPen(color, 1)
        painter.setPen(pen)
        painter.drawEllipse(1, 1, size, size)
        painter.end()
        
        return QtGui.QCursor(pixmap, size // 2 + 1, size // 2 + 1)

    def _on_doodle_toolbar_closed(self):
        if self.scene:
            self.scene.active_mode = None
        viewport = self.viewport()
        if viewport and not getattr(self, 'movewin_active', False):
            viewport.unsetCursor()

    def cancel_active_modes(self):
        self.scene.cancel_active_modes()
        self.cancel_sample_color_mode()
        self.active_mode = None

    def cancel_sample_color_mode(self):
        logger.debug('Cancel sample color mode')
        self.active_mode = None
        self.viewport().unsetCursor()
        if hasattr(self, 'sample_color_widget'):
            self.sample_color_widget.hide()
            del self.sample_color_widget
        if self.scene.has_multi_selection():
            self.scene.multi_select_item.bring_to_front()

    def update_window_title(self):
        clean = self.undo_stack.isClean()
        if clean and not self.filename:
            title = constants.APPNAME
        else:
            name = os.path.basename(self.filename or '[Untitled]')
            clean = '' if clean else '*'
            title = f'{name}{clean} - {constants.APPNAME}'
        self.host_window.setWindowTitle(title)

    def _schedule_recalc_scene_rect(self):
        """Debounced scene rect recalculation — fires once after activity stops."""
        self._recalc_timer.start()

    def on_scene_changed(self, region):
        if self.scene.active_mode in (self.scene.DRAW_MODE, self.scene.ERASE_MODE):
            # NO-OP during drawing to save CPU. Geometry updates are handled by the items.
            return

        if not self.scene.items():
            logger.debug('No items in scene')
            self.setTransform(QtGui.QTransform())
            self.welcome_overlay.setFocus()
            self.clearFocus()
            # Size the overlay to cover the entire view
            self.welcome_overlay.setGeometry(self.rect())
            self.welcome_overlay.raise_()
            self.welcome_overlay.update_visibility()
            self.welcome_overlay.update()
            self.welcome_overlay.show()
            self.actiongroup_set_enabled('active_when_items_in_scene', False)
        else:
            self.setFocus()
            self.welcome_overlay.hide()
            self.actiongroup_set_enabled('active_when_items_in_scene', True)
        self._schedule_recalc_scene_rect()


    def on_can_redo_changed(self, can_redo):
        self.actiongroup_set_enabled('active_when_can_redo', can_redo)

    def on_can_undo_changed(self, can_undo):
        self.actiongroup_set_enabled('active_when_can_undo', can_undo)

    def on_undo_clean_changed(self, clean):
        self.update_window_title()

    def on_context_menu(self, point):
        self._update_collab_actions()
        self.context_menu.exec(self.mapToGlobal(point))

    def _update_collab_actions(self):
        """Update collaboration actions visibility/enabled state based on current session."""
        from threecolref.actions.actions import bee_actions
        is_active = self.collab.is_active
        
        # If active, disable Share and Join, but enable Stop
        if 'share_session' in bee_actions:
            bee_actions['share_session'].qaction.setEnabled(not is_active)
            bee_actions['share_session'].qaction.setVisible(not is_active)
            
        if 'join_session' in bee_actions:
            bee_actions['join_session'].qaction.setEnabled(not is_active)
            bee_actions['join_session'].qaction.setVisible(not is_active)
            
        if 'stop_collaboration' in bee_actions:
            bee_actions['stop_collaboration'].qaction.setEnabled(is_active)
            bee_actions['stop_collaboration'].qaction.setVisible(is_active)

    def get_supported_image_formats(self, cls):
        formats = []

        for f in cls.supportedImageFormats():
            string = f'*.{f.data().decode()}'
            formats.extend((string, string.upper()))
        return ' '.join(formats)

    def get_view_center(self):
        return QtCore.QPoint(round(self.size().width() / 2),
                             round(self.size().height() / 2))

    def clear_scene(self):
        logging.debug('Clearing scene...')
        self.cancel_active_modes()
        self.scene.clear()
        self.undo_stack.clear()
        self.filename = None
        self.setTransform(QtGui.QTransform())

    def reset_previous_transform(self, toggle_item=None):
        if (self.previous_transform
                and self.previous_transform['toggle_item'] != toggle_item):
            self.previous_transform = None

    def fit_rect(self, rect, toggle_item=None):
        if toggle_item and self.previous_transform:
            logger.debug('Fit view: Reset to previous')
            self.setTransform(self.previous_transform['transform'])
            self.centerOn(self.previous_transform['center'])
            self.previous_transform = None
            return
        if toggle_item:
            self.previous_transform = {
                'toggle_item': toggle_item,
                'transform': QtGui.QTransform(self.transform()),
                'center': self.mapToScene(self.get_view_center()),
            }
        else:
            self.previous_transform = None

        logger.debug(f'Fit view: {rect}')
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.recalc_scene_rect()
        # It seems to be more reliable when we fit a second time
        # Sometimes a changing scene rect can mess up the fitting
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        logger.trace('Fit view done')

    def do_save_sync(self, filename, create_new):
        """Synchronous save — blocks until the file is written to disk.
        Used by closeEvent so the scene isn't destroyed mid-save.
        Returns True on success, False on failure.
        """
        import os
        if not filename.lower().endswith(constants.EXTENSION):
            filename = f'{filename}{constants.EXTENSION}'
        try:
            from threecolref.fileio.sql import SQLiteIO
            logger.debug(f'Synchronous save to {filename} (create_new={create_new})')
            io = SQLiteIO(filename, self.scene, create_new=create_new)
            io.write()
            io._close_connection()
            if os.path.exists(filename):
                logger.debug(f'Sync save OK — {os.path.getsize(filename)} bytes')
            self.filename = filename
            self.undo_stack.setClean()
            if not self.autosave_enabled:
                self.autosave_enabled = True
                self.settings.setValue('autosave_enabled', True)
            return True
        except Exception as e:
            logger.error(f'Synchronous save failed: {e}', exc_info=True)
            return False

    def get_confirmation_unsaved_changes(self):
        """Asks the user if they want to discard unsaved changes. Returns
        ``True`` if changes can be discarded, ``False`` otherwise.
        """
        
        if self.undo_stack.isClean():
            return True
        
        # If autosave is already enabled AND we have a file, skip dialog (it saves automatically)
        if self.autosave_enabled and self.filename:
            logger.debug('Skipping unsaved changes dialog - autosave is active')
            return True

        if not self.settings.valueOrDefault('Save/confirm_close_unsaved'):
            return True

        # Check for remembered choice
        remembered = self.settings.valueOrDefault('Save/remember_unsaved_choice')
        last_choice = self.settings.valueOrDefault('Save/last_unsaved_choice')
        
        if remembered and last_choice != 'ask':
            if last_choice == 'save':
                return self._save_for_close()
            elif last_choice == 'discard':
                return True

        from threecolref import widgets
        dialog = widgets.UnsavedChangesDialog(self)
        dialog.exec()
        choice, remember = dialog.get_result()
        
        if remember:
            self.settings.setValue('Save/remember_unsaved_choice', True)
            self.settings.setValue('Save/last_unsaved_choice', choice)
        
        if choice == 'save':
            return self._save_for_close()
        elif choice == 'discard':
            return True
        else:
            return False

    def _save_for_close(self):
        """Synchronous save used when closing. Shows Save As dialog if needed.
        Returns True if saved, False if canceled/failed.
        """
        if self.filename:
            return self.do_save_sync(self.filename, create_new=False)
        else:
            # No filename yet — need Save As dialog
            directory = None
            filename, f = QtWidgets.QFileDialog.getSaveFileName(
                parent=self,
                caption='Save file',
                directory=directory,
                filter=f'{constants.FILE_TYPE_NAME} (*{constants.EXTENSION})')
            if filename:
                return self.do_save_sync(filename, create_new=True)
            return False

    def on_action_new_scene(self):
        confirm = self.get_confirmation_unsaved_changes()
        if confirm:
            self.clear_scene()

    def on_action_fit_scene(self):
        self.fit_rect(self.scene.itemsBoundingRect())

    def on_action_fit_selection(self):
        self.fit_rect(self.scene.itemsBoundingRect(selection_only=True))

    def on_action_fullscreen(self, checked):
        if checked:
            self.host_window.showFullScreen()
        else:
            self.host_window.showNormal()

    def on_action_always_on_top(self, checked):
        import sys
        logger.info(f'Always On Top toggle: {checked}')

        def _apply():
            try:
                # 1. Update flags without forcing frameless
                flags = self.host_window.windowFlags()
                if checked:
                    flags |= Qt.WindowType.WindowStaysOnTopHint
                else:
                    flags &= ~Qt.WindowType.WindowStaysOnTopHint
                
                self.host_window.setWindowFlags(flags)
                self.host_window.show()

                # 2. Native call for Windows as requested
                if sys.platform.startswith('win'):
                    import ctypes
                    hwnd = int(self.host_window.winId())
                    z_order = -1 if checked else -2 # HWND_TOPMOST / HWND_NOTOPMOST
                    ctypes.windll.user32.SetWindowPos(hwnd, z_order, 0, 0, 0, 0, 0x0001 | 0x0002)
                
                logger.info(f'Always On Top: {checked}')
            except Exception as e:
                logger.error(f'Error: {e}')

        # Small delay to ensure any layout/show events settle
        QtCore.QTimer.singleShot(250, _apply)

    def on_action_show_scrollbars(self, checked):
        if checked:
            self.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def on_action_show_menubar(self, checked):
        if checked:
            self.host_window.setMenuBar(self.create_menubar())
        else:
            self.host_window.setMenuBar(None)

    def on_action_show_titlebar(self, checked):
        self.host_window.setWindowFlag(
            Qt.WindowType.FramelessWindowHint, on=not checked)
        self.host_window.destroy()
        self.host_window.create()
        self.host_window.show()

    def on_action_hierarchy(self, checked):
        if checked:
            self.hierarchy_overlay.show()
        else:
            self.hierarchy_overlay.hide()

    def on_action_move_window(self):
        if self.welcome_overlay.isHidden():
            self.on_action_movewin_mode()
        else:
            self.welcome_overlay.on_action_movewin_mode()

    def on_action_undo(self):
        logger.debug('Undo: %s' % self.undo_stack.undoText())
        self.cancel_active_modes()
        self.undo_stack.undo()

    def on_action_redo(self):
        logger.debug('Redo: %s' % self.undo_stack.redoText())
        self.cancel_active_modes()
        self.undo_stack.redo()

    def on_action_select_all(self):
        self.scene.select_all_items()

    def on_action_deselect_all(self):
        self.scene.deselect_all_items()

    def on_action_delete_items(self):
        logger.debug('Deleting items...')
        self.cancel_active_modes()
        self.undo_stack.push(
            commands.DeleteItems(
                self.scene, self.scene.selectedItems(user_only=True)))

    def on_action_cut(self):
        logger.debug('Cutting items...')
        self.on_action_copy()
        self.undo_stack.push(
            commands.DeleteItems(
                self.scene, self.scene.selectedItems(user_only=True)))

    def on_action_raise_to_top(self):
        self.scene.raise_to_top()

    def on_action_lower_to_bottom(self):
        self.scene.lower_to_bottom()

    def on_action_normalize_height(self):
        self.scene.normalize_height()

    def on_action_normalize_width(self):
        self.scene.normalize_width()

    def on_action_normalize_size(self):
        self.scene.normalize_size()

    def on_action_arrange_horizontal(self):
        self.scene.arrange()

    def on_action_arrange_vertical(self):
        self.scene.arrange(vertical=True)

    def on_action_arrange_optimal(self):
        self.scene.arrange_optimal()

    def on_action_arrange_square(self):
        self.scene.arrange_square()

    def on_action_change_opacity(self):
        images = list(filter(
            lambda item: item.is_image,
            self.scene.selectedItems(user_only=True)))
        from threecolref import widgets
        widgets.ChangeOpacityDialog(self, images, self.undo_stack)

    def on_action_grayscale(self, checked):
        images = list(filter(
            lambda item: item.is_image,
            self.scene.selectedItems(user_only=True)))
        if images:
            self.undo_stack.push(
                commands.ToggleGrayscale(images, checked))

    def on_action_crop(self):
        self.scene.crop_items()

    def on_action_flip_horizontally(self):
        self.scene.flip_items(vertical=False)

    def on_action_flip_vertically(self):
        self.scene.flip_items(vertical=True)

    def on_action_reset_scale(self):
        self.cancel_active_modes()
        self.undo_stack.push(commands.ResetScale(
            self.scene.selectedItems(user_only=True)))

    def on_action_reset_rotation(self):
        self.cancel_active_modes()
        self.undo_stack.push(commands.ResetRotation(
            self.scene.selectedItems(user_only=True)))

    def on_action_reset_flip(self):
        self.cancel_active_modes()
        self.undo_stack.push(commands.ResetFlip(
            self.scene.selectedItems(user_only=True)))

    def on_action_reset_crop(self):
        self.cancel_active_modes()
        self.undo_stack.push(commands.ResetCrop(
            self.scene.selectedItems(user_only=True)))

    def on_action_reset_transforms(self):
        self.cancel_active_modes()
        self.undo_stack.push(commands.ResetTransforms(
            self.scene.selectedItems(user_only=True)))

    def on_action_show_color_gamut(self):
        from threecolref import widgets
        widgets.color_gamut.GamutDialog(self, self.scene.selectedItems()[0])

    def on_action_sample_color(self):
        self.cancel_active_modes()
        logger.debug('Entering sample color mode')
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self.active_mode = self.SAMPLE_COLOR_MODE

        if self.scene.has_multi_selection():
            # We don't want to sample the multi select item, so
            # temporarily send it to the back:
            self.scene.multi_select_item.lower_behind_selection()

        pos = self.mapFromGlobal(self.cursor().pos())
        from threecolref import widgets
        self.sample_color_widget = widgets.SampleColorWidget(
            self,
            pos,
            self.scene.sample_color_at(self.mapToScene(pos)))

    def on_items_loaded(self, value):
        logger.debug('On items loaded: add queued items')
        self.scene.add_queued_items()

    def on_loading_finished(self, filename, errors, autosave_was_enabled=False):
        logger.debug(f'Loading finished: restoring autosave={autosave_was_enabled}')
        if errors:
            QtWidgets.QMessageBox.warning(
                self,
                'Problem loading file',
                ('<p>Problem loading file %s</p>'
                 '<p>Not accessible or not a proper bee file</p>') % filename)
        else:
            self.filename = filename
            self.scene.add_queued_items()
            self.on_action_fit_scene()
        
        # Restore autosave setting after file load
        self.autosave_enabled = autosave_was_enabled
        if self.autosave_enabled:
            logger.debug('Autosave re-enabled after file load')

    def on_action_open_recent_file(self, filename):
        confirm = self.get_confirmation_unsaved_changes()
        if confirm:
            self.open_from_file(filename)

    def open_from_file(self, filename):
        logger.info(f'Opening file {filename}')
        self.clear_scene()
        
        # Disable autosave during file load to prevent conflicts
        autosave_was_enabled = self.autosave_enabled
        self.autosave_enabled = False
        self.autosave_timer.stop()
        logger.debug(f'Disabled autosave during file load')
        
        self.worker = fileio.ThreadedIO(
            fileio.load_bee, filename, self.scene)
        self.worker.progress.connect(self.on_items_loaded)
        self.worker.finished.connect(lambda f, e: self.on_loading_finished(f, e, autosave_was_enabled))
        from threecolref import widgets
        self.progress = widgets.BeeProgressDialog(
            f'Loading {filename}',
            worker=self.worker,
            parent=self,
            title=constants.APPNAME)
        self.worker.start()

    def on_action_open(self):
        confirm = self.get_confirmation_unsaved_changes()
        if not confirm:
            return

        self.cancel_active_modes()
        filename, f = QtWidgets.QFileDialog.getOpenFileName(
            parent=self,
            caption='Open file',
            filter=f'{constants.FILE_TYPE_NAME} (*{constants.EXTENSION} *.bee)')
        if filename:
            filename = os.path.normpath(filename)
            self.open_from_file(filename)
            self.filename = filename

    def on_saving_finished(self, filename, errors):
        if errors:
            QtWidgets.QMessageBox.warning(
                self,
                'Problem saving file',
                ('<p>Problem saving file %s</p>'
                 '<p>File/directory not accessible</p>') % filename)
        else:
            self.filename = filename
            self.undo_stack.setClean()
            # Auto-enable autosave when file is successfully saved
            if not self.autosave_enabled:
                logger.debug('File saved successfully - auto-enabling autosave')
                self.autosave_enabled = True
                self.settings.setValue('autosave_enabled', True)
                logger.debug(f'Autosave auto-enabled after save of {filename}')

    def do_save(self, filename, create_new):
        if not filename.lower().endswith(constants.EXTENSION):
            filename = f'{filename}{constants.EXTENSION}'
            
        # Capture thumbnail of the scene on the main thread
        thumbnail_data = None
        try:
            rect = self.scene.itemsBoundingRect()
            if not rect.isEmpty():
                # Target size for the card thumbnail
                thumb_size = QtCore.QSize(280, 190)
                image = QtGui.QImage(thumb_size, QtGui.QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.transparent)
                
                painter = QtGui.QPainter(image)
                painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
                # Render scene rect into the thumb image
                self.scene.render(painter, target=QtCore.QRectF(image.rect()), source=rect)
                painter.end()
                
                # Save to bytes
                buffer = QtCore.QBuffer()
                buffer.open(QtCore.QBuffer.OpenModeFlag.WriteOnly)
                image.save(buffer, "PNG")
                thumbnail_data = buffer.data().data() # Get bytes
        except Exception:
            logger.exception("Failed to capture scene thumbnail")

        self.worker = fileio.ThreadedIO(
            fileio.save_bee, filename, self.scene, create_new=create_new, thumbnail=thumbnail_data)
        self.worker.finished.connect(self.on_saving_finished)
        from threecolref import widgets
        self.progress = widgets.BeeProgressDialog(
            f'Saving {filename}',
            worker=self.worker,
            parent=self,
            title=constants.APPNAME)
        self.worker.start()

    def on_action_save_as(self):
        """Open Save As dialog. Returns True if file was saved, False if canceled."""
        self.cancel_active_modes()
        directory = os.path.dirname(self.filename) if self.filename else None
        filename, f = QtWidgets.QFileDialog.getSaveFileName(
            parent=self,
            caption='Save file',
            directory=directory,
            filter=f'{constants.FILE_TYPE_NAME} (*{constants.EXTENSION})')
        if filename:
            self.do_save(filename, create_new=True)
            return True
        return False

    def on_action_save(self):
        """Save file. Returns True if saved, False if canceled."""
        self.cancel_active_modes()
        if not self.filename:
            return self.on_action_save_as()
        else:
            self.do_save(self.filename, create_new=False)
            return True

    def on_action_export_scene(self):
        directory = os.path.dirname(self.filename) if self.filename else None
        filename, formatstr = QtWidgets.QFileDialog.getSaveFileName(
            parent=self,
            caption='Export Scene to Image',
            directory=directory,
            filter=';;'.join(('Image Files (*.png *.jpg *.jpeg *.svg)',
                              'PNG (*.png)',
                              'JPEG (*.jpg *.jpeg)',
                              'SVG (*.svg)')))

        if not filename:
            return

        name, ext = os.path.splitext(filename)
        if not ext:
            ext = get_file_extension_from_format(formatstr)
            filename = f'{filename}.{ext}'
        logger.debug(f'Got export filename {filename}')

        from threecolref.fileio.export import exporter_registry
        exporter_cls = exporter_registry[ext]
        exporter = exporter_cls(self.scene)
        if not exporter.get_user_input(self):
            return

        self.worker = fileio.ThreadedIO(exporter.export, filename)
        self.worker.finished.connect(self.on_export_finished)
        from threecolref import widgets
        self.progress = widgets.BeeProgressDialog(
            f'Exporting scene…',
            worker=self.worker,
            parent=self,
            title=constants.APPNAME)
        self.worker.start()

    def on_action_copy_scene_image(self):
        """Render the entire scene and copy it to the system clipboard as an image."""
        from threecolref.fileio.export import SceneToPixmapExporter
        try:
            exporter = SceneToPixmapExporter(self.scene)
            exporter.size = exporter.default_size
            image = exporter.render_to_image()
            pixmap = QtGui.QPixmap.fromImage(image)
            QtWidgets.QApplication.clipboard().setPixmap(pixmap)
            logger.info('Scene copied to clipboard')
            # Brief confirmation toast
            QtWidgets.QToolTip.showText(
                QtGui.QCursor.pos(),
                '📋 Scene copied to clipboard!',
                None, QtCore.QRect(), 2000)
        except Exception as e:
            logger.error(f'Failed to copy scene to clipboard: {e}')
            QtWidgets.QMessageBox.warning(
                self, 'Copy Failed',
                f'Could not copy scene to clipboard:\n{e}')


    def on_export_finished(self, filename, errors):
        if errors:
            err_msg = '</br>'.join(str(errors))
            QtWidgets.QMessageBox.warning(
                self,
                'Problem writing file',
                f'<p>Problem writing file {filename}</p><p>{err_msg}</p>')

    def on_action_export_images(self):
        directory = os.path.dirname(self.filename) if self.filename else None
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            parent=self,
            caption='Export Images',
            directory=directory)

        if not directory:
            return

        logger.debug(f'Got export directory {directory}')
        from threecolref.fileio.export import ImagesToDirectoryExporter
        self.exporter = ImagesToDirectoryExporter(self.scene, directory)
        self.worker = fileio.ThreadedIO(self.exporter.export)
        self.worker.user_input_required.connect(
            self.on_export_images_file_exists)
        self.worker.finished.connect(self.on_export_finished)
        from threecolref import widgets
        self.progress = widgets.BeeProgressDialog(
            f'Exporting images…',
            worker=self.worker,
            parent=self,
            title=constants.APPNAME)
        self.worker.start()

    def on_export_images_file_exists(self, filename):
        from threecolref import widgets
        dlg = widgets.ExportImagesFileExistsDialog(self, filename)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.exporter.handle_existing = dlg.get_answer()
            directory = self.exporter.dirname
            self.progress = widgets.BeeProgressDialog(
                f'Exporting images…',
                worker=self.worker,
                parent=self,
                title=constants.APPNAME)
            self.worker.start()

    def on_action_export_item(self):
        """Export the single selected image or video to a file."""
        items = self.scene.selectedItems(user_only=True)
        if len(items) != 1:
            return
        item = items[0]

        directory = os.path.dirname(self.filename) if self.filename else None

        if getattr(item, 'is_video', False):
            # Video: copy the source file
            src = item.filename
            if not src or not os.path.isfile(src):
                from threecolref import widgets
                widgets.BeeNotification(self, 'Source video file not found')
                return
            ext = os.path.splitext(src)[1] or '.mp4'
            default_name = os.path.basename(src) if src else f'video{ext}'
            filename, _ = QtWidgets.QFileDialog.getSaveFileName(
                parent=self,
                caption='Export Video',
                directory=os.path.join(directory, default_name) if directory else default_name,
                filter=f'Video (*{ext});;All Files (*.*)')
            if filename:
                import shutil
                try:
                    shutil.copy2(src, filename)
                    logger.info(f'Exported video to {filename}')
                except Exception as e:
                    logger.error(f'Failed to export video: {e}')
                    QtWidgets.QMessageBox.warning(
                        self, 'Export failed', f'Could not export video: {e}')
        else:
            # Image: save the pixmap
            default_name = os.path.splitext(os.path.basename(
                item.filename or 'image'))[0]
            filename, formatstr = QtWidgets.QFileDialog.getSaveFileName(
                parent=self,
                caption='Export Image',
                directory=os.path.join(directory, default_name) if directory else default_name,
                filter=';;'.join(('PNG (*.png)',
                                  'JPEG (*.jpg *.jpeg)',
                                  'All Files (*.*)')))
            if filename:
                name, ext = os.path.splitext(filename)
                if not ext:
                    ext = get_file_extension_from_format(formatstr)
                    filename = f'{filename}.{ext}'
                try:
                    data, _ = item.pixmap_to_bytes(
                        apply_grayscale=True, apply_crop=True)
                    with open(filename, 'wb') as f:
                        f.write(data)
                    logger.info(f'Exported image to {filename}')
                except Exception as e:
                    logger.error(f'Failed to export image: {e}')
                    QtWidgets.QMessageBox.warning(
                        self, 'Export failed', f'Could not export image: {e}')

    def on_action_quit(self):
        self.host_window.close()

    def on_action_settings(self):
        from threecolref.widgets.settings import SettingsDialog
        SettingsDialog(self)

    def on_action_keyboard_settings(self):
        from threecolref.widgets.controls import ControlsDialog
        ControlsDialog(self)

    def on_action_help(self):
        from threecolref.widgets import HelpDialog
        HelpDialog(self)

    def on_action_about(self):
        from threecolref.widgets import AboutDialog
        dialog = AboutDialog(self)
        dialog.exec()
    
    def on_action_toggle_autosave(self, enabled):
        """Toggle autosave on/off."""
        self.autosave_enabled = enabled
        logger.debug(f'Autosave toggled: {enabled}')
        if not enabled:
            self.autosave_timer.stop()
        self.settings.setValue('autosave_enabled', enabled)
    
    def _on_undo_clean_changed_for_autosave(self, is_clean):
        """Called when undo stack clean state changes. Schedules autosave if enabled."""
        if not self.autosave_enabled or not self.filename or self.autosave_in_progress:
            return
        
        # Only schedule save when changes are made (not clean), not when they're undone (clean)
        if not is_clean:
            # Reset the timer - autosave 2 seconds after last change
            self.autosave_timer.stop()
            self.autosave_timer.start(self.autosave_delay)
        else:
            # Stop autosave timer if we're back to clean state
            self.autosave_timer.stop()
    
    def _on_autosave_timeout(self):
        """Perform silent autosave in background without showing progress dialog."""
        logger.debug(f'Autosave timeout triggered: filename={bool(self.filename)}, isClean={self.undo_stack.isClean()}, inProgress={self.autosave_in_progress}')
        if not self.filename:
            logger.debug('Autosave skipped: no filename')
            return
        if self.undo_stack.isClean():
            logger.debug('Autosave skipped: undo stack is clean')
            return
        if self.autosave_in_progress:
            logger.debug('Autosave skipped: save already in progress')
            return
        
        self.autosave_in_progress = True
        logger.debug(f'STARTING autosave of {self.filename}...')
        try:
            # Perform save silently without progress dialog
            import os
            if not self.filename.lower().endswith(constants.EXTENSION):
                filename = f'{self.filename}{constants.EXTENSION}'
            else:
                filename = self.filename
            
            logger.debug(f'SQLiteIO writing to {filename}')
            # Save directly using SQLiteIO without ThreadedIO to avoid progress dialog
            from threecolref.fileio.sql import SQLiteIO
            io = SQLiteIO(filename, self.scene, create_new=False)
            io.write()
            # CRITICAL: Close the connection to force the file to be flushed to disk
            io._close_connection()
            
            # Verify file exists and has content
            if os.path.exists(filename):
                file_size = os.path.getsize(filename)
                logger.debug(f'Autosave: file written successfully, size={file_size} bytes')
            else:
                logger.error(f'Autosave: file {filename} does not exist after write!')
            
            # IMPORTANT: Only mark as clean AFTER we've verified the file is written
            self.undo_stack.setClean()
            logger.debug(f'Autosave COMPLETED and marked clean for {filename}')
        except Exception as e:
            logger.error(f'Autosave failed: {e}', exc_info=True)
        finally:
            self.autosave_in_progress = False

    def on_action_debuglog(self):
        from threecolref.widgets import DebugLogDialog
        DebugLogDialog(self)

    # ------------------------------------------------------------------
    # Collaboration actions
    # ------------------------------------------------------------------

    def _setup_collab_signals(self):
        """Wire collaboration manager signals to local handlers."""
        self.collab.remote_item_moved.connect(self._apply_remote_move)
        self.collab.remote_item_removed.connect(self._apply_remote_remove)
        self.collab.remote_cursor_moved.connect(self._apply_remote_cursor)
        self.collab.remote_item_added.connect(self._apply_remote_item_added)
        self.collab.error_occurred.connect(self._on_collab_error)
        self.collab.remote_user_left.connect(self._apply_remote_user_left)
        self.collab.status_changed.connect(self._on_collab_status_changed)
        self.collab.user_count_changed.connect(self.collab_status.set_user_count)
        self.collab.remote_full_sync_request.connect(self._on_full_sync_request)
        self.collab.remote_full_sync_response.connect(self._on_full_sync_response)
        self.collab.remote_doodle_start.connect(self._apply_remote_doodle_start)
        self.collab.remote_doodle_point.connect(self._apply_remote_doodle_point)
        self.collab.remote_doodle_end.connect(self._apply_remote_doodle_end)
        self.collab.remote_item_transformed.connect(self._apply_remote_transform)
        self.collab.remote_sync_start.connect(self._apply_remote_sync_start)
        self.collab.remote_sync_end.connect(self._apply_remote_sync_end)


    def on_action_share_session(self):
        try:
            code = self.collab.start_cloud_sharing()
            
            # CRITICAL: Pre-assign collab_ids to all existing scene items AFTER
            # starting sharing (because start_sharing() clears the cache).
            # Items loaded from file have collab_id=None, which
            # means movement broadcasts send None as item_id and peers can't match them.
            for item in self.scene.items():
                if hasattr(item, 'ensure_collab_id'):
                    cid = item.ensure_collab_id()
                    self.collab.register_item(cid, item)
                    
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, 'Share Session',
                f'Could not start sharing: {e}')
            return

        from threecolref.widgets.ios_dialogs import BeeIosSessionCodeDialog
        BeeIosSessionCodeDialog.show_session_code(self, code)

    def on_action_join_session(self):
        if getattr(self, '_is_joining', False):
            return
            
        from threecolref.widgets.ios_dialogs import BeeIosInputDialog
        code, ok = BeeIosInputDialog.get_text(
            self, 'Join Session',
            'Enter session code:')
        if ok and code.strip():
            try:
                logger.info(f'[collab] User initiated join for code: {code.strip()}')
                self._is_joining = True
                if hasattr(self, 'welcome_overlay'):
                    # Prioritize overlay and show loading
                    self.welcome_overlay.show()
                    self.welcome_overlay.raise_()
                    self.welcome_overlay.show_loading('Joining session...')
                
                # Proactive local UI state reset
                self.collab_status.hide()
                
                # Start join timeout (20s)
                if not hasattr(self, '_join_timeout_timer'):
                    self._join_timeout_timer = QtCore.QTimer(self)
                    self._join_timeout_timer.setSingleShot(True)
                    self._join_timeout_timer.timeout.connect(self._on_join_timeout)
                self._join_timeout_timer.start(20000)
                
                self.collab.join_session(code.strip())
            except Exception as e:
                logger.error(f'[collab] Failed to start join process: {e}', exc_info=True)
                self._on_collab_error(str(e))

    def _on_join_timeout(self):
        if getattr(self, '_is_joining', False):
            logger.warning('[collab] Join attempt timed out after 20s')
            self._on_collab_error('Connection timed out. Please check the code or your internet connection.')

    def on_action_stop_collaboration(self):
        self.collab.stop()

    def _on_collab_error(self, msg):
        logger.error(f'[collab] Collaboration error received: {msg}')
        self._is_joining = False
        if hasattr(self, '_join_timeout_timer'):
            self._join_timeout_timer.stop()
            
        if hasattr(self, 'welcome_overlay'):
            self.welcome_overlay.hide_loading()
            self.welcome_overlay.hide()
            
        # Clean up partial state
        self.collab.stop()
        
        QtWidgets.QMessageBox.warning(
            self, 'Collaboration Error', msg)

    # --- Applying remote events ---

    def _collab_item_by_id(self, item_id):
        """Find a scene item by its collab_id using O(1) manager cache."""
        return self.collab.get_item(item_id)

    def _apply_remote_transform(self, data):
        """Apply a remote scale, rotate, or text-change to an item."""
        logger.debug(f"[collab] Incoming transformation: {data}")
        item_ids = data.get('item_ids', [])
        transform_type = data.get('transform_type', '')
        
        self.collab.begin_remote_apply()
        try:
            for iid in item_ids:
                item = self._collab_item_by_id(iid)
                if not item:
                    continue
                    
                if transform_type == 'move':
                    x, y = data.get('x', item.pos().x()), data.get('y', item.pos().y())
                    item.setPos(x, y)
                elif transform_type == 'scale':
                    s = data.get('scale')
                    x, y = data.get('x', item.pos().x()), data.get('y', item.pos().y())
                    if s is not None:
                        item.setScale(s)
                        item.setPos(x, y)
                elif transform_type == 'rotate':
                    r = data.get('rotation')
                    x, y = data.get('x', item.pos().x()), data.get('y', item.pos().y())
                    if r is not None:
                        item.setRotation(r)
                        item.setPos(x, y)
                elif transform_type == 'text_changed':
                    text = data.get('text', '')
                    if hasattr(item, 'setPlainText'):
                        item.document().blockSignals(True)
                        item.setPlainText(text)
                        item.document().blockSignals(False)
            
            # FIGMA-STYLE UX: Force a repaint and recalculate scene bounds
            # so the host/peer sees the movement immediately.
            self.scene.update()
            if hasattr(self, 'recalc_scene_rect'):
                self.recalc_scene_rect()
                
        finally:
            self.collab.end_remote_apply()

    def _apply_remote_move(self, data):
        item_ids = data.get('item_ids', [])
        dx, dy = data.get('dx', 0), data.get('dy', 0)
        self.collab.begin_remote_apply()
        try:
            for iid in item_ids:
                item = self._collab_item_by_id(iid)
                if item:
                    item.moveBy(dx, dy)
        finally:
            self.collab.end_remote_apply()

    def _apply_remote_remove(self, data):
        item_ids = data.get('item_ids', [])
        self.collab.begin_remote_apply()
        try:
            for iid in item_ids:
                item = self._collab_item_by_id(iid)
                if item:
                    self.scene.removeItem(item)
                    self.collab.unregister_item(iid)
        finally:
            self.collab.end_remote_apply()

    def _apply_remote_item_added(self, data):
        """Queue a remote item for reconstruction."""
        self._remote_item_queue.append(data)
        if not self._sync_timer.isActive():
            self._sync_timer.start()

    def _process_remote_queue(self):
        """Process a batch of remote items from the queue."""
        if not self._remote_item_queue:
            self._sync_timer.stop()
            # If we were in a sync, hide the overlay now that processing is done
            if getattr(self, '_is_receiving_sync', False):
                self._is_receiving_sync = False
                self.on_action_fit_scene()
                if hasattr(self, 'welcome_overlay'):
                    # Force one last GUI update before hiding
                    QtWidgets.QApplication.processEvents()
                    self.welcome_overlay.hide_loading()
                    self.welcome_overlay.hide()
                
                # Reveal the status pill now that the loading screen is gone
                if self.collab.is_active:
                    self.collab_status.show()
                    self.collab_status.update()
            return

        # Process up to 5 items per batch to keep UI responsive
        batch_size = 5
        batch = self._remote_item_queue[:batch_size]
        self._remote_item_queue = self._remote_item_queue[batch_size:]

        import base64
        self.collab.begin_remote_apply()
        try:
            for data in batch:
                item_data = data.get('data', {})
                item_type = data.get('item_type', 'pixmap')
                item_id = data.get('item_id')
                parent_id = item_data.get('parent_id')

                try:
                    # Parenting recovery helper
                    def restore_parenting(item, pid):
                        if not pid: return
                        parent = self._collab_item_by_id(pid)
                        if parent:
                            was_blocked = self.collab.applying_remote
                            # Temporarily block applying_remote to avoid loop during mapFromScene
                            scene_pos = item.scenePos()
                            item.setParentItem(parent)
                            item.setPos(parent.mapFromScene(scene_pos))
                        else:
                            logger.debug(f'[collab] Parent {pid} not found yet for item {item_id}')

                    # Check if item already exists to avoid duplicates during real-time sync (like shapes)
                    existing = self._collab_item_by_id(item_id)
                    if existing:
                        if hasattr(existing, 'update_from_data'):
                            existing.update_from_data(**item_data)
                        else:
                            # Fallback if mixin missing
                            existing.setPos(item_data.get('x', 0), item_data.get('y', 0))
                            existing.setZValue(item_data.get('z', 0))
                            existing.setScale(item_data.get('scale', 1))
                            existing.setRotation(item_data.get('rotation', 0))
                        
                        # Ensure parenting matches
                        if parent_id and (not existing.parentItem() or getattr(existing.parentItem(), 'collab_id', None) != parent_id):
                            restore_parenting(existing, parent_id)
                        continue

                    if item_type == 'pixmap':
                        if 'image_bytes' in item_data:
                            img_bytes = item_data['image_bytes']
                        else:
                            img_bytes = base64.b64decode(item_data.get('image_b64', ''))
                            
                        pixmap = QtGui.QPixmap()
                        pixmap.loadFromData(img_bytes)
                        if pixmap.isNull():
                            logger.warning(f'[collab] Failed to load pixmap for item {item_id}')
                            continue
                        img = pixmap.toImage()
                        item = BeePixmapItem(img, item_data.get('filename'))
                        item.collab_id = item_id
                        item.update_from_data(**item_data)
                        self.scene.addItem(item)
                        self.collab.register_item(item_id, item)
                    elif item_type == 'text':
                        item = BeeTextItem()
                        item.collab_id = item_id
                        item.update_from_data(**item_data)
                        self.scene.addItem(item)
                        self.collab.register_item(item_id, item)
                    elif item_type == 'doodle':
                        from threecolref.items import BeeDoodleItem
                        item = BeeDoodleItem.create_from_data(data=item_data)
                        item.collab_id = item_id
                        item.update_from_data(**item_data)
                        self.scene.addItem(item)
                        self.collab.register_item(item_id, item)
                        # REMOVED: item.bring_to_front() (fixes reverse Z-order)
                    elif item_type == 'shape':
                        from threecolref.items import BeeShapeItem
                        item = BeeShapeItem.create_from_data(data=item_data)
                        item.collab_id = item_id
                        item.update_from_data(**item_data)
                        self.scene.addItem(item)
                        self.collab.register_item(item_id, item)
                    elif item_type == 'video':
                        from threecolref.items import BeeVideoItem
                        item = BeeVideoItem(item_data.get('filename'))
                        item.collab_id = item_id
                        # Use received thumbnail indefinitely if probe fails/offline
                        if 'image_bytes' in item_data:
                            px = QtGui.QPixmap()
                            px.loadFromData(item_data['image_bytes'])
                            if not px.isNull():
                                item.setPixmap(px)
                        
                        item.update_from_data(**item_data)
                        self.scene.addItem(item)
                        self.collab.register_item(item_id, item)
                    
                    if parent_id and item and not item.parentItem():
                        restore_parenting(item, parent_id)

                except Exception as e:
                    logger.error(f'[collab] Critical error reconstructing {item_type} item {item_id}: {e}', exc_info=True)

            # Robust overlay management: Hide welcome overlay if ANY items are added
            # BUT only if we aren't in a formal SYNC delivery (which handles its own hiding)
            if not getattr(self, '_is_receiving_sync', False):
                if hasattr(self, 'welcome_overlay') and self.scene.items():
                    self.welcome_overlay.hide()
                    
        finally:
            self.collab.end_remote_apply()

        # If queue is now empty and we were in a sync, we might need a fit
        if not self._remote_item_queue:
            self.on_action_fit_scene()


    def _apply_remote_doodle_start(self, data):
        """A remote user started drawing."""
        item_id = data.get('item_id')
        color = data.get('color', '#FF0000')
        width = data.get('width', 2)
        x, y = data.get('x', 0), data.get('y', 0)
        item_type = data.get('item_type', 'doodle')
        parent_id = data.get('parent_id')

        self.collab.begin_remote_apply()
        try:
            from threecolref.items import BeeDoodleItem, BeeShapeItem
            if item_type == 'shape':
                # Reconstruct as shape if sent as such (e.g. from mouseRelease retry or full sync)
                # But doodle_start msg usually implies real-time stroke.
                item = BeeShapeItem(shape_type=data.get('shape_type', 'rect'), color_hex=color, width=width)
            elif item_type in ('rect', 'circle', 'line', 'arrow'):
                item = BeeShapeItem(shape_type=item_type, color_hex=color, width=width)
            else:
                item = BeeDoodleItem(color_hex=color, width=width)
            
            item.setPos(x, y)
            if hasattr(item, 'add_point'):
                item.add_point(0, 0)
            item.collab_id = item_id
            self.scene.addItem(item)
            self.collab.register_item(item_id, item)
            
            if parent_id:
                parent = self._collab_item_by_id(parent_id)
                if parent:
                    # Drawings are relative to parent
                    item.setParentItem(parent)
                    item.setPos(x, y) # Doodles are sent in parent local coords if parent exists
        finally:
            self.collab.end_remote_apply()

    def _apply_remote_doodle_point(self, data):
        """A remote user added a point to their drawing."""
        item_id = data.get('item_id')
        x, y = data.get('x', 0), data.get('y', 0)

        item = self._collab_item_by_id(item_id)
        if item and hasattr(item, 'add_point'):
            self.collab.begin_remote_apply()
            try:
                item.add_point(x, y)
            finally:
                self.collab.end_remote_apply()

    def _apply_remote_doodle_end(self, data):
        """A remote user finished drawing a stroke."""
        pass

    def _apply_remote_cursor(self, data):
        """Update remote cursor overlay."""
        self.cursor_overlay.update_cursor(data)

    def _apply_remote_user_left(self, uid):
        self.cursor_overlay.remove_cursor(uid)

    def _on_collab_status_changed(self, status):
        logger.debug(f'[collab] Status changed: {status} (is_joining={getattr(self, "_is_joining", False)})')
        # Bulletproof: Don't show the pill if we are still in a loading state
        # this prevents the "Connected" pill from popping over the "Joining..." overlay
        overlay_active = hasattr(self, 'welcome_overlay') and self.welcome_overlay.isVisible()
        
        if status != 'disconnected' and (overlay_active or getattr(self, '_is_joining', False)):
            # Store status but don't show the pill yet
            self.collab_status._status = status
            self.collab_status.hide()
        else:
            self.collab_status.set_status(status)
            
        if status == 'disconnected':
            self.cursor_overlay.stop()
            # If we are purposefully joining another session, don't hide the loading overlay
            if not getattr(self, '_is_joining', False):
                self.welcome_overlay.hide_loading()
                # If we were in an active session (session_code set) but didn't
                # initiate the stop ourselves, the host must have dropped us.
                # Fully reset state so the pill/code/user-count all clear.
                if self.collab.session_code:
                    logger.info('[collab] Host dropped session — fully resetting collaboration state')
                    QtCore.QTimer.singleShot(100, self.collab.stop)
        else:
            self.cursor_overlay.start()
            # Reset joining flag once we are connected to the new session (or hosting)
            if status in ('connected', 'hosting'):
                self._is_joining = False
                if hasattr(self, '_join_timeout_timer'):
                    self._join_timeout_timer.stop()
            # We don't hide_loading on 'connected' anymore; 
            # we wait for the full sync to finish.

    def _on_full_sync_request(self, data):
        """Host: a new peer asked for the full scene — serialize and send in batches."""
        if not self.collab.is_hosting or not self.collab.is_active:
            return
        
        logger.info('[collab] Host starting batched full sync delivery...')
        self.collab.broadcast_sync_start()
        
        # Capture all relevant scene items
        items_to_sync = [item for item in self.scene.items() 
                         if hasattr(item, 'ensure_collab_id') and hasattr(item, 'TYPE')]
        
        item_count = len(items_to_sync)
        current_idx = 0
        batch_size = 10 # Faster batches for better performance

        def send_next_batch():
            nonlocal current_idx
            if not self.collab.is_hosting or not self.collab.is_active:
                return

            end_idx = min(current_idx + batch_size, item_count)
            for i in range(current_idx, end_idx):
                item = items_to_sync[i]
                cid = item.ensure_collab_id()
                self.collab.register_item(cid, item)
                
                try:
                    item_type = getattr(item, 'TYPE', 'unknown')
                    item_data = {}
                    
                    if item_type == 'pixmap':
                        data_bytes, _ = item.pixmap_to_bytes(apply_grayscale=True, apply_crop=True)
                        item_data = {
                            'image_bytes': data_bytes,
                            'filename': getattr(item, 'filename', None),
                            'x': item.pos().x(), 'y': item.pos().y(),
                            'scale': item.scale(), 'rotation': item.rotation(),
                            'z': item.zValue(),
                        }
                    elif item_type == 'text':
                        item_data = {
                            'text': item.toPlainText(),
                            'x': item.pos().x(), 'y': item.pos().y(),
                            'scale': item.scale(), 'rotation': item.rotation(),
                            'z': item.zValue(),
                        }
                    elif item_type == 'video':
                        pixmap = item.pixmap()
                        data_bytes = QtCore.QByteArray()
                        if pixmap and not pixmap.isNull():
                            buf = QtCore.QBuffer(data_bytes)
                            buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
                            pixmap.save(buf, "PNG")
                        
                        item_data = {
                            'filename': getattr(item, 'filename', ''),
                            'image_bytes': data_bytes.data(),
                            'x': item.pos().x(), 'y': item.pos().y(),
                            'scale': item.scale(), 'rotation': item.rotation(),
                            'z': item.zValue(),
                        }
                    elif item_type in ('doodle', 'shape'):
                        item_data = item.get_extra_save_data() | {
                            'x': item.pos().x(), 'y': item.pos().y(),
                            'z': item.zValue(),
                        }
                        if item_type == 'shape':
                            item_data.update({
                                'scale': item.scale(),
                                'rotation': item.rotation(),
                            })
                    else:
                        continue

                    # Send item through client
                    msg = protocol.make_item_added_msg(
                        self.collab._client.user_id, cid, item_type, item_data)
                    self.collab._client.emit(protocol.ITEM_ADDED, msg)
                except Exception as e:
                    logger.warning(f'[collab] Failed to sync item {cid}: {e}')
            
            current_idx = end_idx
            if current_idx < item_count:
                # Stagger delivery to prevent socket disconnects
                QtCore.QTimer.singleShot(5, send_next_batch)
            else:
                self.collab.broadcast_sync_end()
                logger.info(f'[collab] Host finished batched sync: {item_count} items sent')

        send_next_batch()

    def _on_full_sync_response(self, data):
        """Joiner: received full scene snapshot — rebuild scene step-by-step."""
        items = data.get('items', [])
        if not items:
            if hasattr(self, 'welcome_overlay'):
                self.welcome_overlay.hide_loading()
                self.welcome_overlay.hide()
            
            # Reveal status pill if session is active but scene was empty
            if self.collab.is_active:
                self.collab_status.show()
            return

        logger.info(f'[collab] Queuing full sync: {len(items)} items')
        self._is_receiving_sync = True
        self.collab.begin_remote_apply()
        self.scene.clear()
        
        for item_data in items:
            self._apply_remote_item_added(item_data)
        
        self.collab.end_remote_apply()

    def _apply_remote_sync_start(self, data):
        """Joiner: host is starting a chunked sync delivery."""
        logger.info('[collab] Receiving chunked sync...')
        self._is_receiving_sync = True
        self.collab.begin_remote_apply()
        self.scene.clear()

    def _apply_remote_sync_end(self, data):
        """Joiner: host finished chunked sync delivery."""
        logger.info('[collab] Chunked sync finished')
        # We don't hide the overlay here because items might still be in the queue.
        # _process_remote_queue will handle hiding when the queue is drained.
        self.collab.end_remote_apply()


    def on_action_facing_problem(self):
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl('https://github.com/Luohino/threecolref/issues/new'))

    def on_insert_images_finished(self, new_scene, filename, errors, autosave_was_enabled=False):
        """Callback for when loading of images is finished.

        :param new_scene: True if the scene was empty before, else False
        :param filename: Not used, for compatibility only
        :param errors: List of filenames that couldn't be loaded
        :param autosave_was_enabled: Whether autosave was enabled before import
        """

        logger.debug(f'Insert images finished: new_scene={new_scene}, filename={filename}, errors={len(errors) if errors else 0}, autosave_was_enabled={autosave_was_enabled}')
        if errors:
            errornames = [
                f'<li>{fn}</li>' for fn in errors]
            errornames = '<ul>%s</ul>' % '\n'.join(errornames)
            num = len(errors)
            msg = f'{num} image(s) could not be opened.<br/>'
            QtWidgets.QMessageBox.warning(
                self,
                'Problem loading images',
                msg + IMG_LOADING_ERROR_MSG + errornames)
        self.scene.add_queued_items()
        logger.debug(f'After add_queued_items, undo_stack.isClean()={self.undo_stack.isClean()}')
        self.scene.arrange_default()
        self.undo_stack.endMacro()
        logger.debug(f'After endMacro, undo_stack.isClean()={self.undo_stack.isClean()}')
        
        # Re-enable autosave and trigger it immediately after import
        logger.debug(f'Insert images finished: re-enabling autosave={autosave_was_enabled}')
        self.autosave_enabled = autosave_was_enabled
        logger.debug(f'Set autosave_enabled={self.autosave_enabled}, filename={bool(self.filename)}')
        if self.autosave_enabled and self.filename:
            # Trigger autosave immediately after import to save the new items
            logger.debug(f'Triggering autosave after image import - will save in 100ms')
            self.autosave_timer.stop()
            self.autosave_timer.start(100)  # Save almost immediately
        else:
            logger.debug(f'Autosave NOT triggered: enabled={self.autosave_enabled}, has_filename={bool(self.filename)}')
        if new_scene:
            self.on_action_fit_scene()

    def do_insert_images(self, filenames, pos=None):
        if not pos:
            pos = self.get_view_center()
        self.scene.deselect_all_items()
        self.undo_stack.beginMacro('Insert Images')
        
        # Disable autosave temporarily during import
        autosave_was_enabled = self.autosave_enabled
        logger.debug(f'Insert images: autosave was {autosave_was_enabled}, disabling')
        self.autosave_enabled = False
        self.autosave_timer.stop()
        
        self.worker = fileio.ThreadedIO(
            fileio.load_images,
            filenames,
            self.mapToScene(pos),
            self.scene)
        self.worker.progress.connect(self.on_items_loaded)
        # Create lambda to properly map signal args to callback params:
        # Signal emits: (filename, errors)
        # Callback expects: (new_scene, filename, errors, autosave_was_enabled)
        new_scene = not self.scene.items()
        self.worker.finished.connect(
            lambda filename, errors: self.on_insert_images_finished(
                new_scene, filename, errors, autosave_was_enabled))
        from threecolref import widgets
        self.progress = widgets.BeeProgressDialog(
            'Fetching & loading images…',
            worker=self.worker,
            parent=self,
            title=constants.APPNAME)
        self.worker.start()

    def do_insert_videos(self, urls, pos=None):
        from threecolref.items import BeeVideoItem
        import cv2
        if not pos:
            pos = self.get_view_center()
        
        scene_pos = self.mapToScene(pos)
        self.scene.deselect_all_items()
        self.undo_stack.beginMacro('Insert Videos')
        
        from PyQt6.QtWidgets import QApplication
        items = []
        for i, url in enumerate(urls):
            path = url.toLocalFile() if url.isLocalFile() else url.toString()
            logger.info(f'Inserting video from {path}')
            item = BeeVideoItem(path)
            item.set_pos_center(scene_pos)
            items.append(item)
            self.scene.addItem(item)
            item.setSelected(True)
            # Yield to the event loop every 10 items to prevent GUI freeze
            if i % 10 == 9:
                QApplication.processEvents()
            
        self.undo_stack.push(commands.InsertItems(self.scene, items, ignore_first_redo=True))
        self.undo_stack.endMacro()
        
        # Only arrange if all items have valid non-zero dimensions
        # (arrange_default crashes with rpack if any item has zero width/height)
        if all(item.boundingRect().width() > 0 and item.boundingRect().height() > 0
               for item in items):
            self.scene.arrange_default()
        
        if len(self.scene.items()) == len(urls):
            self.on_action_fit_scene()

    def on_action_insert_images(self):
        self.cancel_active_modes()
        formats = self.get_supported_image_formats(QtGui.QImageReader)
        logger.debug(f'Supported image types for reading: {formats}')
        filenames, f = QtWidgets.QFileDialog.getOpenFileNames(
            parent=self,
            caption='Select one or more images to open',
            filter=f'Images ({formats})')
        self.do_insert_images(filenames)

    def on_action_insert_text(self):
        logger.info('=== on_action_insert_text called ===')
        self.cancel_active_modes()
        try:
            item = BeeTextItem()
            logger.info(f'BeeTextItem created: {item}')
            pos = self.mapToScene(self.mapFromGlobal(self.cursor().pos()))
            logger.info(f'Insert position: {pos}')
            scale = self.get_scale()
            logger.info(f'View scale: {scale}')
            item.setScale(1 / scale)
            self.undo_stack.push(commands.InsertItems(self.scene, [item], pos))
            logger.info('InsertItems pushed to undo stack')
        except Exception as e:
            logger.error(f'Error in on_action_insert_text: {e}', exc_info=True)

    def on_action_copy(self):
        logger.debug('Copying to clipboard...')
        self.cancel_active_modes()
        clipboard = QtWidgets.QApplication.clipboard()
        items = self.scene.selectedItems(user_only=True)

        # At the moment, we can only copy one image to the global
        # clipboard. (Later, we might create an image of the whole
        # selection for external copying.)
        items[0].copy_to_clipboard(clipboard)

        # However, we can copy all items to the internal clipboard:
        self.scene.copy_selection_to_internal_clipboard()

        # We set a marker for ourselves in the global clipboard so
        # that we know to look up the internal clipboard when pasting:
        clipboard.mimeData().setData(
            'threecolref/items', QtCore.QByteArray.number(len(items)))

    def on_action_paste(self):
        self.cancel_active_modes()
        logger.debug('Pasting from clipboard...')
        clipboard = QtWidgets.QApplication.clipboard()
        pos = self.mapToScene(self.mapFromGlobal(self.cursor().pos()))

        # See if we need to look up the internal clipboard:
        data = clipboard.mimeData().data('threecolref/items')
        logger.debug(f'Custom data in clipboard: {data}')
        if data and self.scene.internal_clipboard:
            # Checking that internal clipboard exists since the user
            # may have opened a new scene since copying.
            self.scene.paste_from_internal_clipboard(pos)
            return

        img = clipboard.image()
        if not img.isNull():
            item = BeePixmapItem(img)
            self.undo_stack.push(commands.InsertItems(self.scene, [item], pos))
            if len(self.scene.items()) == 1:
                # This is the first image in the scene
                self.on_action_fit_scene()
            return
        text = clipboard.text()
        if text:
            item = BeeTextItem(text)
            item.setScale(1 / self.get_scale())
            self.undo_stack.push(commands.InsertItems(self.scene, [item], pos))
            return

        msg = 'No image data or text in clipboard or image too big'
        logger.info(msg)
        from threecolref import widgets
        widgets.BeeNotification(self, msg)

    def on_action_open_settings_dir(self):
        dirname = os.path.dirname(self.settings.fileName())
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(dirname))

    def on_selection_changed(self):
        try:
            logger.debug('Currently selected items: %s',
                         len(self.scene.selectedItems(user_only=True)))
            self.actiongroup_set_enabled('active_when_selection',
                                         self.scene.has_selection())
            self.actiongroup_set_enabled('active_when_single_selection',
                                         self.scene.has_single_selection())
            self.actiongroup_set_enabled('active_when_single_image',
                                         self.scene.has_single_image_selection())

            if self.scene.has_selection():
                item = self.scene.selectedItems(user_only=True)[0]
                grayscale = getattr(item, 'grayscale', False)
                bee_actions['grayscale'].qaction.setChecked(grayscale)
            self.viewport().repaint()
        except RuntimeError:
            # The underlying C++ scene object might have been deleted during shutdown
            pass

    def on_cursor_changed(self, cursor):
        # Only block cursor change when the VIEW itself has an active mode
        # (pan, zoom, sample color). Never block cursor for scene-level item
        # interactions (move/rubberband) since that prevents hover resize cursors.
        if self.active_mode is None:
            self.viewport().setCursor(cursor)

    def on_cursor_cleared(self):
        if self.active_mode is None:
            self.viewport().unsetCursor()

    def eventFilter(self, obj, event):
        """Intercept viewport Enter events to clear the OS resize cursor.
        
        When the user resizes the application window and then moves back into
        the canvas, the OS window-resize cursor stays visible until Qt refreshes
        it. Catching QEvent.Enter on the viewport and calling unsetCursor() forces
        Qt to re-evaluate hover events and restore the correct canvas cursor.
        """
        if obj is self.viewport() and event.type() == QtCore.QEvent.Type.Enter:
            # SAFETY: Clear any stuck global override cursors (e.g. from frameless resize)
            try:
                while QtWidgets.QApplication.overrideCursor() is not None:
                    QtWidgets.QApplication.restoreOverrideCursor()
            except Exception:
                pass
                
            # FORCE POKE: Manually toggle the cursor to force the OS to drop any 
            # stuck resize symbols from native window interactions.
            self.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)
            QtCore.QTimer.singleShot(10, self.viewport().unsetCursor)
            
            if self.active_mode is None:
                self.viewport().unsetCursor()
        return super().eventFilter(obj, event)

    def recalc_scene_rect(self):
        """Resize the scene rectangle so that it is always one view width
        wider than all items' bounding box at each side and one view
        width higher on top and bottom. This gives the impression of
        an infinite canvas."""

        if self.previous_transform:
            return
        logger.trace('Recalculating scene rectangle...')
        try:
            bounds = self.scene.itemsBoundingRect()
            topleft = self.mapFromScene(bounds.topLeft())
            topleft = self.mapToScene(QtCore.QPoint(
                topleft.x() - self.size().width(),
                topleft.y() - self.size().height()))
            bottomright = self.mapFromScene(bounds.bottomRight())
            bottomright = self.mapToScene(QtCore.QPoint(
                bottomright.x() + self.size().width(),
                bottomright.y() + self.size().height()))
            self.setSceneRect(QtCore.QRectF(topleft, bottomright))
        except OverflowError:
            logger.info('Maximum scene size reached')
        logger.trace('Done recalculating scene rectangle')

    def get_zoom_size(self, func):
        """Calculates the size of all items' bounding box in the view's
        coordinates.

        This helps ensure that we never zoom out too much (scene
        becomes so tiny that items become invisible) or zoom in too
        much (causing overflow errors).

        :param func: Function which takes the width and height as
            arguments and turns it into a number, for ex. ``min`` or ``max``.
        """

        bounds = self.scene.itemsBoundingRect()
        topleft = self.mapFromScene(bounds.topLeft())
        bottomright = self.mapFromScene(bounds.bottomRight())
        return func(bottomright.x() - topleft.x(),
                    bottomright.y() - topleft.y())

    def scale(self, sx, sy):
        super().scale(sx, sy)
        # Invalidate geometry for all selected items to refresh their screen-space
        # hit zones (boundingRect/shape) at the new zoom level.
        if self.scene:
            self.scene._updating_scene = True
            try:
                for item in self.scene.selectedItems():
                    if hasattr(item, 'prepareGeometryChange'):
                        item.prepareGeometryChange()
                if hasattr(self.scene, 'multi_select_item'):
                    self.scene.multi_select_item.prepareGeometryChange()
                self.scene.on_view_scale_change()
            finally:
                self.scene._updating_scene = False
                # Manually enforce one single layout reset after zoom
                if self.scene.has_multi_selection() and self.scene.multi_select_item.scene():
                    self.scene.multi_select_item.fit_selection_area(
                        self.scene.itemsBoundingRect(selection_only=True))
                        
        self._schedule_recalc_scene_rect()

    def get_scale(self):
        return self.transform().m11()

    def pan(self, delta):
        if not self.scene.items():
            logger.debug('No items in scene; ignore pan')
            return

        hscroll = self.horizontalScrollBar()
        hscroll.setValue(int(hscroll.value() + delta.x()))
        vscroll = self.verticalScrollBar()
        vscroll.setValue(int(vscroll.value() + delta.y()))

    def zoom(self, delta, anchor):
        if not self.scene.items():
            logger.debug('No items in scene; ignore zoom')
            return

        # We calculate where the anchor is before and after the zoom
        # and then move the view accordingly to keep the anchor fixed
        # We can't use QGraphicsView's AnchorUnderMouse since it
        # uses the current cursor position while we need the initial mouse
        # press position for zooming with Ctrl + Middle Drag
        anchor = QtCore.QPoint(round(anchor.x()),
                               round(anchor.y()))
        ref_point = self.mapToScene(anchor)
        if delta == 0:
            return
        factor = 1 + abs(delta / 1000)
        if delta > 0:
            if self.get_zoom_size(max) < 10000000:
                self.scale(factor, factor)
            else:
                logger.debug('Maximum zoom size reached')
                return
        else:
            if self.get_zoom_size(min) > 50:
                self.scale(1/factor, 1/factor)
            else:
                logger.debug('Minimum zoom size reached')
                return

        self.pan(self.mapFromScene(ref_point) - anchor)
        self.reset_previous_transform()

    def wheelEvent(self, event):
        action, inverted\
            = self.keyboard_settings.mousewheel_action_for_event(event)

        delta = event.angleDelta().y()
        if inverted:
            delta = delta * -1

        if action == 'zoom':
            self.zoom(delta, event.position())
            event.accept()
            return
        if action == 'pan_horizontal':
            self.pan(QtCore.QPointF(0, 0.5 * delta))
            event.accept()
            return
        if action == 'pan_vertical':
            self.pan(QtCore.QPointF(0.5 * delta, 0))
            event.accept()
            return

    def mousePressEvent(self, event):
        if self.mousePressEventMainControls(event):
            return

        if self.active_mode == self.SAMPLE_COLOR_MODE:
            if (event.button() == Qt.MouseButton.LeftButton):
                color = self.scene.sample_color_at(
                    self.mapToScene(event.pos()))
                if color:
                    name = qcolor_to_hex(color)
                    clipboard = QtWidgets.QApplication.clipboard()
                    clipboard.setText(name)
                    self.scene.internal_clipboard = []
                    msg = f'Copied color to clipboard: {name}'
                    logger.debug(msg)
                    from threecolref import widgets
                    widgets.BeeNotification(self, msg)
                else:
                    logger.debug('No color found')
            self.cancel_sample_color_mode()
            event.accept()
            return

        action, inverted = self.keyboard_settings.mouse_action_for_event(event)

        if action == 'zoom':
            self.active_mode = self.ZOOM_MODE
            self.event_start = event.position()
            self.event_anchor = event.position()
            self.event_inverted = inverted
            event.accept()
            return

        if action == 'pan':
            logger.trace('Begin pan')
            self.active_mode = self.PAN_MODE
            self.event_start = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            # ClosedHandCursor and OpenHandCursor don't work, but I
            # don't know if that's only on my system or a general
            # problem. It works with other cursors.
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.active_mode == self.PAN_MODE:
            self.reset_previous_transform()
            pos = event.position()
            self.pan(self.event_start - pos)
            self.event_start = pos
            event.accept()
            return

        if self.active_mode == self.ZOOM_MODE:
            self.reset_previous_transform()
            pos = event.position()
            delta = (self.event_start - pos).y()
            if self.event_inverted:
                delta *= -1
            self.event_start = pos
            self.zoom(delta * 20, self.event_anchor)
            event.accept()
            return

        if self.active_mode == self.SAMPLE_COLOR_MODE:
            self.sample_color_widget.update(
                event.position(),
                self.scene.sample_color_at(self.mapToScene(event.pos())))
            event.accept()
            return

        if self.mouseMoveEventMainControls(event):
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.active_mode == self.PAN_MODE:
            logger.trace('End pan')
            self.viewport().unsetCursor()
            self.active_mode = None
            event.accept()
            return
        if self.active_mode == self.ZOOM_MODE:
            self.active_mode = None
            event.accept()
            return
        if self.mouseReleaseEventMainControls(event):
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self._schedule_recalc_scene_rect()
        except Exception:
            pass
        
        # Overlays: welcome and cursors
        viewport = self.viewport()
        vw, vh = viewport.width(), viewport.height()
        
        try:
            if hasattr(self, 'welcome_overlay') and self.welcome_overlay is not None:
                self.welcome_overlay.setGeometry(self.rect())
                self.welcome_overlay.update_visibility()
        except Exception:
            pass
        
        try:
            if hasattr(self, 'cursor_overlay') and self.cursor_overlay is not None:
                self.cursor_overlay.setGeometry(0, 0, vw, vh)
        except Exception:
            pass

        # UI Components: collab status, toolbars
        try:
            if hasattr(self, 'collab_status') and self.collab_status is not None:
                # Bottom-right corner offset
                right_margin = 20
                bottom_margin = 20
                cw = self.collab_status.width()
                ch = self.collab_status.height()
                self.collab_status.move(self.width() - cw - right_margin, self.height() - ch - bottom_margin)
        except Exception:
            pass
        try:
            if hasattr(self, '_hierarchy_overlay') and self._hierarchy_overlay is not None:
                if hasattr(self._hierarchy_overlay, 'update_position'):
                    self._hierarchy_overlay.update_position()
        except Exception:
            pass
        
        if hasattr(self, '_text_toolbar') and self._text_toolbar.isVisible():
            self._text_toolbar._position_above_item()
        if hasattr(self, '_doodle_toolbar') and self._doodle_toolbar and self._doodle_toolbar.isVisible():
            self._doodle_toolbar.position_in_view()

        try:
            self.update_watermark_pos()
        except Exception:
            pass

    def init_watermark(self):
        # Watermark removed per user request
        pass

    def update_watermark_pos(self):
        # Watermark removed per user request
        pass

    def showEvent(self, event):
        super().showEvent(event)
        if not self.scene.items():
            self.welcome_overlay.setGeometry(self.rect())
            self.welcome_overlay.raise_()
            self.welcome_overlay.update_visibility()
            self.welcome_overlay.update()
            self.welcome_overlay.show()

    def keyPressEvent(self, event):
        if self.keyPressEventMainControls(event):
            return

        ctrl_shift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        
        # Doodle Mode Toggle
        if event.key() == Qt.Key.Key_D and event.modifiers() == ctrl_shift:
            if self.scene.active_mode in (self.scene.DRAW_MODE, self.scene.ERASE_MODE):
                self.scene.active_mode = None
                self.doodle_toolbar.hide()
                from threecolref import widgets
                widgets.BeeNotification(self, 'Exited Draw Mode')
                self.viewport().unsetCursor()
            else:
                self.scene.active_mode = self.scene.DRAW_MODE
                try:
                    self.doodle_toolbar.position_in_view()
                    self.doodle_toolbar.pencil_btn.setChecked(True)
                except Exception as e:
                    logger.error(f'Error showing doodle toolbar: {e}', exc_info=True)
                from threecolref import widgets
                widgets.BeeNotification(self, 'Entered Draw Mode (Doodle!)')
                self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return

        # Switch to Pencil
        if event.key() == Qt.Key.Key_P and event.modifiers() == ctrl_shift:
            if self.scene.active_mode in (self.scene.DRAW_MODE, self.scene.ERASE_MODE):
                self.scene.active_mode = self.scene.DRAW_MODE
                self.doodle_toolbar.pencil_btn.setChecked(True)
                self.viewport().setCursor(Qt.CursorShape.CrossCursor)
                event.accept()
                return

        # Switch to Eraser
        if event.key() == Qt.Key.Key_E and event.modifiers() == ctrl_shift:
            if self.scene.active_mode in (self.scene.DRAW_MODE, self.scene.ERASE_MODE):
                self.scene.active_mode = self.scene.ERASE_MODE
                self.doodle_toolbar.eraser_btn.setChecked(True)
                self.viewport().setCursor(Qt.CursorShape.ForbiddenCursor)
                event.accept()
                return

        # Escape to exit modes
        if self.scene.active_mode in (self.scene.DRAW_MODE, self.scene.ERASE_MODE) and event.key() == Qt.Key.Key_Escape:
            self.scene.active_mode = None
            self.doodle_toolbar.hide()
            self.viewport().unsetCursor()
            event.accept()
            return

        if self.active_mode == self.SAMPLE_COLOR_MODE:
            self.cancel_sample_color_mode()
            event.accept()
            return

        super().keyPressEvent(event)



class BeeMainWidget(QtWidgets.QFrame):
    """Container for integrated title bar and graphics view."""

    def __init__(self, app, main_window):
        super().__init__(main_window)
        self.app = app
        self.main_window = main_window

        # Apply a dark border so frameless windows don't blend together
        self.setObjectName("BeeMainWidget")
        self.setStyleSheet("#BeeMainWidget { border: 1px solid #000000; }")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title bar at top (in layout flow so view starts below it)
        from threecolref.widgets import BeeTitleBar
        self.view = BeeGraphicsView(app, main_window)
        self.title_bar = BeeTitleBar(self, self.view)
        layout.addWidget(self.title_bar)

        # Graphics view fills remaining space
        layout.addWidget(self.view, 1)

        # Keep pin button in sync with "Always On Top" action
        from threecolref.actions.actions import bee_actions
        bee_actions['always_on_top'].qaction.toggled.connect(
            self.title_bar.controls.update_states
        )
        self.title_bar.controls.update_states()

    def mouseDoubleClickEvent(self, event):
        if (hasattr(self.main_window, '_is_compact') and self.main_window._is_compact and
                event.button() == QtCore.Qt.MouseButton.LeftButton):
            self.main_window._restore_from_compact()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
