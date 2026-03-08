import sys
import os
from PyQt6 import QtWidgets, QtGui, QtCore

# Add current dir to path
sys.path.append(os.getcwd())

app = QtWidgets.QApplication(sys.argv)

with open("mro_check.txt", "w") as f:
    try:
        from threecolref.items import BeeTextItem
        item = BeeTextItem("Test")
        f.write("Attempting item.bounding_rect_unselected()...\n")
        try:
            val = item.bounding_rect_unselected()
            f.write(f"bounding_rect_unselected worked: {val}\n")
        except Exception as e:
            f.write(f"bounding_rect_unselected failed: {e}\n")
            import traceback
            f.write(traceback.format_exc())

    except Exception as e:
        import traceback
        f.write(f"Overall error: {e}\n")
        f.write(traceback.format_exc())
