import os
import subprocess
import sys
import shutil

# Files to manage
CONSTANTS_FILE = os.path.join('threecolref', 'constants.py')
ENV_FILE = '.env'
SPEC_FILE = 'threecolref.spec'

def get_secret_url():
    """Read the real URL from the local .env file."""
    if not os.path.exists(ENV_FILE):
        print(f"ERROR: {ENV_FILE} not found! Create it first.")
        sys.exit(1)
    
    with open(ENV_FILE, 'r') as f:
        for line in f:
            if line.startswith('COLLAB_SERVER_URL='):
                return line.split('=', 1)[1].strip()
    return None

def build():
    real_url = get_secret_url()
    if not real_url:
        print("ERROR: COLLAB_SERVER_URL not found in .env")
        sys.exit(1)

    # 1. Backup constants.py
    backup_file = CONSTANTS_FILE + '.bak'
    shutil.copy2(CONSTANTS_FILE, backup_file)
    print(f"Backed up {CONSTANTS_FILE}")

    try:
        # 2. Patch constants.py with the REAL url for the build
        with open(CONSTANTS_FILE, 'r') as f:
            content = f.read()
        
        # Replace the env loader with the hardcoded real URL
        new_content = content.replace(
            "os.environ.get('COLLAB_SERVER_URL', 'https://threecolref-server.onrender.com')",
            f"'{real_url}'"
        )
        
        with open(CONSTANTS_FILE, 'w') as f:
            f.write(new_content)
        print("Patched constants.py with production URL...")

        # 3. Run PyInstaller
        print("Running PyInstaller build...")
        pyinstaller_exe = os.path.join(os.getcwd(), 'venv', 'Scripts', 'pyinstaller.exe')
        if not os.path.exists(pyinstaller_exe):
            pyinstaller_exe = 'pyinstaller'
            
        cmd = [
            pyinstaller_exe, 
            '--noconfirm', 
            '--name', '3ColRef', 
            '--onefile', 
            '--windowed', 
            '--icon=' + os.path.join('threecolref', 'assets', 'logo.ico'),
            '--add-data', f'threecolref/assets{os.path.pathsep}threecolref/assets',
            'threecolref/__main__.py'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        with open('build.log', 'w', encoding='utf-8') as log_file:
            log_file.write(result.stdout)
            log_file.write("\n--- ERRORS ---\n")
            log_file.write(result.stderr)

        if result.returncode == 0:
            print("Build SUCCESSFUL! Check build.log for details.")
        else:
            print(f"Build FAILED with return code {result.returncode}. Check build.log.")

    except Exception as e:
        print(f"Build SCRIPT ERROR: {e}")
    
    finally:
        # 4. ALWAYS Revert constants.py so secrets aren't left in the source
        shutil.move(backup_file, CONSTANTS_FILE)
        print(f"Restored original {CONSTANTS_FILE} (secrets removed from source)")

if __name__ == "__main__":
    build()
