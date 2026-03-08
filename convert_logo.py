import os
import struct

def png_to_ico(png_path, ico_path):
    if not os.path.exists(png_path):
        print(f"Error: {png_path} not found")
        return False
    
    with open(png_path, 'rb') as f:
        png_data = f.read()
    
    png_size = len(png_data)
    
    # ICO Header
    # Reserved: 0 (2 bytes)
    # Type: 1 (2 bytes)
    # Count: 1 (2 bytes)
    header = struct.pack('<HHH', 0, 1, 1)
    
    # Directory Entry (16 bytes)
    # Width: 0 (means 256)
    # Height: 0 (means 256)
    # Colors: 0
    # Reserved: 0
    # Planes: 1
    # BPP: 32
    # Size: png_size
    # Offset: 22 (header size 6 + entry size 16)
    entry = struct.pack('BBBBHHII', 0, 0, 0, 0, 1, 32, png_size, 22)
    
    with open(ico_path, 'wb') as f:
        f.write(header)
        f.write(entry)
        f.write(png_data)
    
    print(f"Successfully created {ico_path}")
    return True

if __name__ == "__main__":
    png_to_ico(r'threecolref\assets\logo.png', r'threecolref\assets\logo.ico')
