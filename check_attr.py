import sys
import os
from PyQt6 import QtWidgets, QtGui, QtCore

# Add current dir to path
sys.path.append(os.getcwd())

app = QtWidgets.QApplication(sys.argv)

try:
    from threecolref.items import BeeTextItem
    print(f"MRO: {BeeTextItem.__mro__}")
    
    item = BeeTextItem("Test")
    print(f"Has corners_scene_coords: {hasattr(item, 'corners_scene_coords')}")
    try:
        val = item.corners_scene_coords
        print(f"Value: {val}")
    except Exception as e:
        print(f"Access error: {e}")
        import traceback
        traceback.print_exc()

except Exception as e:
    import traceback
    traceback.print_exc()
