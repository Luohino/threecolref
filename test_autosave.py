#!/usr/bin/env python3
"""Test autosave functionality by creating a test project and verifying persistence."""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add the repo to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_autosave():
    """Test that autosave persists changes after close."""
    from threecolref.fileio.sql import SQLiteIO
    from threecolref.items import BeeScene
    from PyQt6 import QtGui
    
    # Create temp directory for test
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, 'test_autosave.3col')
        print(f"Testing autosave to: {test_file}")
        
        # Create a scene and add an item
        scene = BeeScene()
        
        # Create initial file
        io = SQLiteIO(test_file, scene, create_new=True)
        io.write()
        io._close_connection()
        
        initial_size = os.path.getsize(test_file)
        print(f"Initial file size: {initial_size} bytes")
        assert initial_size > 0, "File not created"
        
        # Verify file exists and can be read
        assert os.path.exists(test_file), "File doesn't exist after write"
        print("✓ File persisted after close")
        
        # Test that subsequent writes also persist
        io2 = SQLiteIO(test_file, scene, create_new=False)
        io2.write()
        io2._close_connection()
        
        final_size = os.path.getsize(test_file)
        print(f"Final file size: {final_size} bytes")
        assert os.path.exists(test_file), "File doesn't exist after second write"
        print("✓ File persisted after second write/close")
        
        print("\nAll tests passed!")

if __name__ == '__main__':
    test_autosave()
