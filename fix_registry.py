import winreg
import os
import sys

def set_reg_value(key_path, value_name, value):
    try:
        # Create/Open the key
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        # Set the value
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, value)
        winreg.CloseKey(key)
        print(f"Set {key_path}\\{value_name or '(Default)'} = {value}")
        return True
    except Exception as e:
        print(f"Error setting {key_path}: {e}")
        return False

def fix_association():
    app_root = os.path.dirname(os.path.abspath(__file__))
    extension = ".3col"
    prog_id = "3ColRef.Scene"
    description = "3ColRef Scene"
    
    icon_path = os.path.join(app_root, "threecolref", "assets", "logo.ico")
    pythonw_exe = os.path.join(app_root, "venv", "Scripts", "pythonw.exe")
    
    if not os.path.exists(pythonw_exe):
        # Fallback to system pythonw if venv not found (though it should be there)
        pythonw_exe = "pythonw.exe"

    python_code = f"import sys; sys.path.insert(0, r'{app_root}'); from threecolref.__main__ import main; main()"
    command = f'"{pythonw_exe}" -c "{python_code}" "%1"'

    print(f"App Root: {app_root}")
    print(f"Icon Path: {icon_path}")

    # 1. ProgID
    set_reg_value(f"Software\\Classes\\{prog_id}", "", description)
    # 2. Icon
    set_reg_value(f"Software\\Classes\\{prog_id}\\DefaultIcon", "", icon_path)
    # 3. Command
    set_reg_value(f"Software\\Classes\\{prog_id}\\shell\\open\\command", "", command)
    # 4. Association
    set_reg_value(f"Software\\Classes\\{extension}", "", prog_id)

    print("\nRegistry associations updated successfully via Python WinReg.")

if __name__ == "__main__":
    fix_association()
