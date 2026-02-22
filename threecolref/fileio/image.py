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
import os.path
import tempfile
from urllib.error import URLError
from urllib import parse, request

from PyQt6 import QtGui

import exif
from lxml import etree
import plum


logger = logging.getLogger(__name__)


def exif_rotated_image(path=None):
    """Returns a QImage that is transformed according to the source's
    orientation EXIF data.
    """

    img = QtGui.QImage(path)
    if img.isNull():
        return img

    with open(path, 'rb') as f:
        try:
            exifimg = exif.Image(f)
        except Exception:
            logger.debug(f'Exif parser failed on image: {path}')
            return img

    try:
        if 'orientation' in exifimg.list_all():
            orientation = exifimg.orientation
        else:
            return img
    except (NotImplementedError, ValueError):
        logger.exception(f'Exif failed reading orientation of image: {path}')
        return img

    transform = QtGui.QTransform()

    if orientation == exif.Orientation.TOP_RIGHT:
        return img.mirrored(horizontal=True, vertical=False)
    if orientation == exif.Orientation.BOTTOM_RIGHT:
        transform.rotate(180)
        return img.transformed(transform)
    if orientation == exif.Orientation.BOTTOM_LEFT:
        return img.mirrored(horizontal=False, vertical=True)
    if orientation == exif.Orientation.LEFT_TOP:
        transform.rotate(90)
        return img.transformed(transform).mirrored(
            horizontal=True, vertical=False)
    if orientation == exif.Orientation.RIGHT_TOP:
        transform.rotate(90)
        return img.transformed(transform)
    if orientation == exif.Orientation.RIGHT_BOTTOM:
        transform.rotate(270)
        return img.transformed(transform).mirrored(
            horizontal=True, vertical=False)
    if orientation == exif.Orientation.LEFT_BOTTOM:
        transform.rotate(270)
        return img.transformed(transform)

    return img


def _extract_image_url_from_page(url, page_data):
    """Given a webpage URL and its HTML bytes, extract the best image URL.
    
    Priority:
    1. og:image (OpenGraph meta tag) - best quality, used by all major sites
    2. First <img> tag with src
    """
    try:
        root = etree.HTML(page_data)
        # 1. Try og:image meta tag (used by Twitter, Facebook, news sites, etc.)
        og_img = root.xpath('//meta[@property="og:image"]/@content')
        if og_img:
            return og_img[0]
        # 2. Try twitter:image
        tw_img = root.xpath('//meta[@name="twitter:image"]/@content')
        if tw_img:
            return tw_img[0]
        # 3. Fallback to first large-looking img tag
        imgs = root.xpath('//img/@src')
        if imgs:
            # Try to pick an img with http in the src (absolute URL)
            for src in imgs:
                if src and (src.startswith('http') or src.startswith('//')):
                    if src.startswith('//'):
                        src = 'https:' + src
                    return src
    except Exception as e:
        logger.debug(f'Failed to extract image URL from page: {e}')
    return None


def _looks_like_html(data):
    """Check if raw bytes look like an HTML page."""
    try:
        sample = data[:512].lower()
        return b'<html' in sample or b'<!doctype' in sample or b'<head' in sample
    except Exception:
        return False


def load_image(path):
    if isinstance(path, str):
        path = os.path.normpath(path)
        return (exif_rotated_image(path), path)
    if path.isLocalFile():
        path = os.path.normpath(path.toLocalFile())
        return (exif_rotated_image(path), path)

    url = bytes(path.toEncoded()).decode()
    img = exif_rotated_image()

    def _fetch(target_url):
        """Download bytes from a URL with a browser-like User-Agent."""
        req = request.Request(
            target_url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                                   'Chrome/120.0.0.0 Safari/537.36'})
        return request.urlopen(req, timeout=15).read()

    try:
        data = _fetch(url)
    except URLError as e:
        logger.debug(f'Downloading URL failed: {e}')
        return (img, url)

    # If the downloaded content is HTML (webpage, not a direct image),
    # extract the best image URL from the page first.
    if _looks_like_html(data):
        logger.debug(f'URL returned HTML, extracting image URL from page: {url}')

        # Instagram — JS-rendered, og:image not in raw HTML, use oembed API
        import json
        parsed_url = parse.urlparse(url)
        domain = '.'.join(parsed_url.netloc.split('.')[-2:])
        extracted = None

        if domain == 'instagram.com':
            try:
                oembed_url = (f'https://api.instagram.com/oembed/?url={parse.quote(url)}'
                              f'&maxwidth=1080')
                oembed_data = json.loads(_fetch(oembed_url))
                extracted = oembed_data.get('thumbnail_url')
                logger.debug(f'Instagram oembed thumbnail: {extracted}')
            except Exception as e:
                logger.debug(f'Instagram oembed failed: {e}')

        if not extracted:
            extracted = _extract_image_url_from_page(url, data)

        if extracted:
            logger.debug(f'Extracted image URL: {extracted}')
            try:
                data = _fetch(extracted)
                url = extracted
            except URLError as e:
                logger.debug(f'Downloading extracted image URL failed: {e}')
                return (img, url)
        else:
            logger.debug('No image URL found in page')
            return (img, url)

    with tempfile.TemporaryDirectory() as tmp:
        fname = os.path.join(tmp, 'img')
        with open(fname, 'wb') as f:
            f.write(data)
            logger.debug(f'Temporarily saved in: {fname}')
        img = exif_rotated_image(fname)

    return (img, url)

