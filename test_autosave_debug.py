#!/usr/bin/env python3
"""
Debug script to test autosave behavior during image import.
This creates a test file, imports an image, and verifies persistence.
"""

import os
import sys
import tempfile
import logging
from pathlib import Path

# Setup logging to capture debug messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(name)s - %(levelname)s - %(message)s'
)

# Add repo to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6 import QtCore, QtWidgets, QtGui
from threecolref.items import BeeScene, BeePixmapItem
from threecolref.fileio.sql import SQLiteIO
from threecolref import constants

logger = logging.getLogger(__name__)

def test_autosave_persistence():
    """Test that autosave persists changes when enabled and disabled."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, 'test_autosave.3col')
        logger.info(f"Testing autosave to: {test_file}")
        
        # Create scene and initial file
        scene = BeeScene()
        io = SQLiteIO(test_file, scene, create_new=True)
        io.write()
        io._close_connection()
        
        initial_size = os.path.getsize(test_file)
        logger.info(f"✓ Initial file created: {initial_size} bytes")
        
        # Now simulate what happens during import:
        # 1. We have the file open
        # 2. We add an item to the scene
        # 3. We mark the undo stack as not clean
        # 4. We save
        
        # Add a pixmap item (simulating imported image)
        img = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_RGB32)
        img.fill(QtCore.Qt.GlobalColor.red)
        item = BeePixmapItem(img, "test_image.png")
        item.setPos(0, 0)
        scene.addItem(item)
        scene._items_by_type.setdefault('pixmap', []).append(item)
        
        logger.info("✓ Added pixmap item to scene")
        
        # Now test save with connection closure
        io2 = SQLiteIO(test_file, scene, create_new=False)
        logger.info("About to call io.write()...")
        io2.write()
        logger.info("write() returned, about to close connection...")
        io2._close_connection()
        logger.info("Connection closed")
        
        # Verify file was updated
        final_size = os.path.getsize(test_file)
        logger.info(f"✓ File after save: {final_size} bytes")
        
        if final_size > initial_size:
            logger.info("✓ SUCCESS: File size increased - data was persisted!")
        else:
            logger.error(f"✗ FAILURE: File size did not increase (initial={initial_size}, final={final_size})")
            
        # Try to reload and verify the item is there
        scene2 = BeeScene()
        io3 = SQLiteIO(test_file, scene2, readonly=True)
        logger.info("Reading file back...")
        io3.read()
        
        items = list(scene2.items_by_type('pixmap'))
        logger.info(f"✓ Items loaded from file: {len(items)} pixmap items")
        if items:
            logger.info("✓ SUCCESS: Image was persisted to file!")
        else:
            logger.error("✗ FAILURE: No pixmap items found in loaded file!")

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    test_autosave_persistence()
    print("\nTest complete.")
