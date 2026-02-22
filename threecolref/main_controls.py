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

from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt, QUrl

from threecolref import commands
from threecolref.items import BeePixmapItem
from threecolref import fileio


logger = logging.getLogger(__name__)


class MainControlsMixin:
    """Basic controls shared by the main view and the welcome overlay:

    * Right-click menu
    * Dropping files
    * Moving the window without title bar
    """

    def init_main_controls(self, main_window):
        self.main_window = main_window
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            self.control_target.on_context_menu)
        self.setAcceptDrops(True)
        self.movewin_active = False

    def on_action_movewin_mode(self):
        if self.movewin_active:
            # Pressing the same shortcut again should end the action
            self.exit_movewin_mode()
        else:
            self.enter_movewin_mode()

    @property
    def viewport_or_self(self):
        if hasattr(self, 'viewport'):
            return self.viewport()
        return self

    def enter_movewin_mode(self):
        logger.debug('Entering movewin mode')
        self.setMouseTracking(True)
        self.movewin_active = True
        self.viewport_or_self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.event_start = QtCore.QPointF(self.cursor().pos())
        if hasattr(self, 'disable_mouse_events'):
            self.disable_mouse_events()

    def exit_movewin_mode(self):
        logger.debug('Exiting movewin mode')
        self.setMouseTracking(False)
        self.movewin_active = False
        self.viewport_or_self.unsetCursor()
        if hasattr(self, 'enable_mouse_events'):
            self.enable_mouse_events()

    def dragEnterEvent(self, event):
        mimedata = event.mimeData()
        logger.debug(f'Drag enter event: {mimedata.formats()}')
        if mimedata.hasUrls():
            event.acceptProposedAction()
        elif mimedata.hasImage():
            event.acceptProposedAction()
        else:
            msg = 'Attempted drop not an image or image too big'
            logger.info(msg)
            from threecolref import widgets
            widgets.BeeNotification(self.control_target, msg)

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        try:
            mimedata = event.mimeData()
            logger.debug(f'Handling file drop: {mimedata.formats()}')
            pos = QtCore.QPoint(round(event.position().x()),
                                round(event.position().y()))

            # 1. Direct image data from clipboard/drag (most reliable)
            if mimedata.hasImage():
                try:
                    img = QtGui.QImage(mimedata.imageData())
                    item = BeePixmapItem(img)
                    pos = self.control_target.mapToScene(pos)
                    self.control_target.undo_stack.push(
                        commands.InsertItems(self.control_target.scene, [item], pos))
                    return
                except Exception as e:
                    logger.error(f'Error handling image drag: {e}', exc_info=True)
                    return

            # 2. When a browser drags content it sends text/html with the actual
            #    <img src="..."> already resolved — extract that directly
            if mimedata.hasHtml():
                try:
                    html = mimedata.html()
                    logger.debug(f'Browser HTML mimedata: {html[:200]}')
                    img_url = self._extract_img_src_from_html(html)
                    if img_url:
                        logger.debug(f'Found image URL in HTML mimedata: {img_url}')
                        from threecolref import widgets
                        widgets.BeeNotification(
                            self.control_target, '🔗 Fetching image from the web…')
                        from PyQt6.QtWidgets import QApplication
                        QApplication.processEvents()
                        self.control_target.do_insert_images([QUrl(img_url)], pos)
                        return
                except Exception as e:
                    logger.error(f'Error handling HTML drag: {e}', exc_info=True)

            # 3. URL list (file paths or web URLs)
            if mimedata.hasUrls():
                try:
                    logger.debug(f'Found dropped urls: {mimedata.urls()}')
                    
                    # Check for project file (.3col / .bee) drop first
                    first_url = mimedata.urls()[0]
                    if first_url.isLocalFile():
                        local_path = first_url.toLocalFile()
                        if fileio.is_bee_file(local_path):
                            if not self.control_target.scene.items():
                                self.control_target.open_from_file(local_path)
                            else:
                                # Use method with unsaved confirmation
                                self.control_target.on_action_open_recent_file(local_path)
                            return
                    web_urls = [u for u in mimedata.urls() if not u.isLocalFile()]
                    if web_urls:
                        from threecolref import widgets
                        widgets.BeeNotification(
                            self.control_target, '🔗 Fetching from the web…')
                        from PyQt6.QtWidgets import QApplication
                        QApplication.processEvents()
                    
                    # Separate by file type — ignore non-media files (scripts, folders, etc.)
                    video_exts = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.wmv', '.flv', '.m4v')
                    image_exts = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
                                  '.tiff', '.tif', '.avif', '.svg', '.ico', '.icns')

                    video_urls = []
                    image_urls = []

                    for u in mimedata.urls():
                        url_str = u.toString().lower()
                        path_str = u.toLocalFile().lower() if u.isLocalFile() else url_str
                        
                        # Check for video extensions (local or web)
                        is_video = any(path_str.endswith(ext) for ext in video_exts)
                        
                        # Special cases for popular video sites and their thumbnails
                        if not is_video:
                            if any(x in url_str for x in ('youtube.com/watch', 'youtu.be/', 'youtube.com/embed')):
                                is_video = True
                            elif any(x in url_str for x in ('vimeo.com/', 'player.vimeo.com')):
                                is_video = True
                            elif 'i.ytimg.com' in url_str: # YouTube thumbnails
                                is_video = True
                            elif 'i.vimeocdn.com' in url_str: # Vimeo thumbnails
                                is_video = True
                        
                        if is_video:
                            video_urls.append(u)
                        else:
                            # Treat everything else as potential image (filters non-media later)
                            if not u.isLocalFile() or path_str.endswith(image_exts):
                                image_urls.append(u)

                    if video_urls:
                        from threecolref import widgets
                        widgets.BeeNotification(
                            self.control_target, 'Loading video...')
                        from PyQt6.QtWidgets import QApplication
                        QApplication.processEvents()
                        self.control_target.do_insert_videos(video_urls, pos)
                    if image_urls:
                        self.control_target.do_insert_images(image_urls, pos)
                    return
                except Exception as e:
                    logger.error(f'Error handling URL drop: {e}', exc_info=True)
                    return

            # 4. Plain text that could be an image or video URL
            if mimedata.hasText():
                try:
                    text = mimedata.text().strip()
                    if text.startswith('http') and any(
                            text.lower().endswith(ext)
                            for ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif',
                                        '.bmp', '.tiff', '.avif')):
                        from threecolref import widgets
                        widgets.BeeNotification(
                            self.control_target, '🔗 Fetching image from the web…')
                        from PyQt6.QtWidgets import QApplication
                        QApplication.processEvents()
                        self.control_target.do_insert_images([QUrl(text)], pos)
                        return
                except Exception as e:
                    logger.error(f'Error handling text drag: {e}', exc_info=True)
                    return

            logger.info('Drop not an image')
        except Exception as e:
            logger.error(f'Unexpected error in dropEvent: {e}', exc_info=True)

    def _extract_img_src_from_html(self, html):
        """Extract the first image src from HTML string (browser drag data)."""
        import re
        # Try to find img src - browsers put resolved URLs here
        match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if match:
            src = match.group(1)
            # Only return if it looks like a real image URL, not a base64 or tracker
            if src.startswith('http') and not src.startswith('data:'):
                return src
        return None


    def mousePressEventMainControls(self, event):
        if self.movewin_active:
            self.exit_movewin_mode()
            event.accept()
            return True

        action, inverted =\
            self.control_target.keyboard_settings.mouse_action_for_event(event)
        if action == 'movewindow':
            self.enter_movewin_mode()
            event.accept()
            return True

    def mouseMoveEventMainControls(self, event):
        if self.movewin_active:
            pos = self.mapToGlobal(event.position())
            delta = pos - self.event_start
            self.event_start = pos
            self.main_window.move(self.main_window.x() + int(delta.x()),
                                  self.main_window.y() + int(delta.y()))
            event.accept()
            return True

    def mouseReleaseEventMainControls(self, event):
        if self.movewin_active:
            self.exit_movewin_mode()
            event.accept()
            return True

    def keyPressEventMainControls(self, event):
        if self.movewin_active:
            self.exit_movewin_mode()
            event.accept()
            return True
