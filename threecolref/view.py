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

        self.scene = BeeGraphicsScene(self.undo_stack)
        self.scene.changed.connect(self.on_scene_changed)
        self.scene.selectionChanged.connect(self.on_selection_changed)
        self.scene.cursor_changed.connect(self.on_cursor_changed)
        self.scene.cursor_cleared.connect(self.on_cursor_cleared)
        self.setScene(self.scene)

        from threecolref.widgets.welcome_overlay import WelcomeOverlay
        self.welcome_overlay = WelcomeOverlay(self)
        self._hierarchy_overlay = None

        from threecolref.widgets.text_toolbar import TextFormatToolbar
        self._text_toolbar = TextFormatToolbar(self)

        # Context menu and actions
        self.build_menu_and_actions()
        self.control_target = self
        self.init_main_controls(main_window=parent)
        self.init_watermark()

        # Load files given via command line
        if commandline_args.filenames:
            fn = commandline_args.filenames[0]
            if os.path.splitext(fn)[1] in ('.bee', constants.EXTENSION):
                self.open_from_file(fn)
            else:
                self.do_insert_images(commandline_args.filenames)

        self.update_window_title()

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

    def on_scene_changed(self, region):
        if not self.scene.items():
            logger.debug('No items in scene')
            self.setTransform(QtGui.QTransform())
            self.welcome_overlay.setFocus()
            self.clearFocus()
            self.welcome_overlay.show()
            self.actiongroup_set_enabled('active_when_items_in_scene', False)
        else:
            self.setFocus()
            self.welcome_overlay.hide()
            self.actiongroup_set_enabled('active_when_items_in_scene', True)
        self.recalc_scene_rect()


    def on_can_redo_changed(self, can_redo):
        self.actiongroup_set_enabled('active_when_can_redo', can_redo)

    def on_can_undo_changed(self, can_undo):
        self.actiongroup_set_enabled('active_when_can_undo', can_undo)

    def on_undo_clean_changed(self, clean):
        self.update_window_title()

    def on_context_menu(self, point):
        self.context_menu.exec(self.mapToGlobal(point))

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
            parent=self)
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
            parent=self)
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
            f'Exporting {filename}',
            worker=self.worker,
            parent=self)
        self.worker.start()

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
            f'Exporting to {directory}',
            worker=self.worker,
            parent=self)
        self.worker.start()

    def on_export_images_file_exists(self, filename):
        from threecolref import widgets
        dlg = widgets.ExportImagesFileExistsDialog(self, filename)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.exporter.handle_existing = dlg.get_answer()
            directory = self.exporter.dirname
            self.progress = widgets.BeeProgressDialog(
                f'Exporting to {directory}',
                worker=self.worker,
                parent=self)
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
        QtWidgets.QMessageBox.about(
            self,
            f'About {constants.APPNAME}',
            (f'<h2>{constants.APPNAME} {constants.VERSION}</h2>'
             f'<p>{constants.APPNAME_FULL}</p>'
             f'<p>{constants.COPYRIGHT}</p>'
             f'<p><a href="{constants.WEBSITE}">'
             f'Visit the {constants.APPNAME} website</a></p>'))
    
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
            parent=self)
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
        self.cancel_active_modes()
        item = BeeTextItem()
        pos = self.mapToScene(self.mapFromGlobal(self.cursor().pos()))
        item.setScale(1 / self.get_scale())
        self.undo_stack.push(commands.InsertItems(self.scene, [item], pos))

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

    def on_cursor_changed(self, cursor):
        if self.active_mode is None:
            self.viewport().setCursor(cursor)

    def on_cursor_cleared(self):
        if self.active_mode is None:
            self.viewport().unsetCursor()

    def recalc_scene_rect(self):
        """Resize the scene rectangle so that it is always one view width
        wider than all items' bounding box at each side and one view
        width higher on top and bottom. This gives the impression of
        an infinite canvas."""

        if self.previous_transform:
            return
        logger.trace('Recalculating scene rectangle...')
        try:
            topleft = self.mapFromScene(
                self.scene.itemsBoundingRect().topLeft())
            topleft = self.mapToScene(QtCore.QPoint(
                topleft.x() - self.size().width(),
                topleft.y() - self.size().height()))
            bottomright = self.mapFromScene(
                self.scene.itemsBoundingRect().bottomRight())
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

        topleft = self.mapFromScene(
            self.scene.itemsBoundingRect().topLeft())
        bottomright = self.mapFromScene(
            self.scene.itemsBoundingRect().bottomRight())
        return func(bottomright.x() - topleft.x(),
                    bottomright.y() - topleft.y())

    def scale(self, *args, **kwargs):
        super().scale(*args, **kwargs)
        self.scene.on_view_scale_change()
        self.recalc_scene_rect()

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
        self.recalc_scene_rect()
        if hasattr(self, 'welcome_overlay'):
            self.welcome_overlay.resize(self.size())
            # Re-center floating widget if visible
            if self.welcome_overlay.isVisible() and hasattr(self.welcome_overlay, 'floating_widget'):
                parent_rect = self.rect()
                widget_rect = self.welcome_overlay.floating_widget.geometry()
                x = (parent_rect.width() - widget_rect.width()) // 2
                y = (parent_rect.height() - widget_rect.height()) // 2
                self.welcome_overlay.floating_widget.move(x, y)
        if hasattr(self, '_hierarchy_overlay') and self._hierarchy_overlay is not None:
            self._hierarchy_overlay.update_position()
        self.update_watermark_pos()

    def init_watermark(self):
        # Watermark removed per user request
        pass

    def update_watermark_pos(self):
        # Watermark removed per user request
        pass

    def keyPressEvent(self, event):
        if self.keyPressEventMainControls(event):
            return
        if self.active_mode == self.SAMPLE_COLOR_MODE:
            self.cancel_sample_color_mode()
            event.accept()
            return
        super().keyPressEvent(event)

class BeeMainWidget(QtWidgets.QWidget):
    """Container for integrated title bar and graphics view."""

    def __init__(self, app, main_window):
        super().__init__(main_window)
        self.app = app
        self.main_window = main_window

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Graphics view takes full space
        self.view = BeeGraphicsView(app, main_window)
        layout.addWidget(self.view)

        # Title bar overlays on top (bubble-style, doesn't push UI when it expands)
        from threecolref.widgets import BeeTitleBar

        self.title_bar = BeeTitleBar(self, self.view)
        self.title_bar.setParent(self)
        self.title_bar.raise_()

        # Keep pin button in sync with "Always On Top" action
        from threecolref.actions.actions import bee_actions

        bee_actions['always_on_top'].qaction.toggled.connect(
            self.title_bar.controls.update_states
        )
        # Initialise pin state based on current action state
        self.title_bar.controls.update_states()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep title bar overlay at top, full width
        self.title_bar.setGeometry(0, 0, self.width(), self.title_bar.height())

    def mouseDoubleClickEvent(self, event):
        # Double-click compact window to restore (PureRef-style)
        if (hasattr(self.main_window, '_is_compact') and self.main_window._is_compact and
                event.button() == QtCore.Qt.MouseButton.LeftButton):
            self.main_window._restore_from_compact()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
