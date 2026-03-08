from threecolref import constants
import os

print("--- SECURITY CHECK ---")
print(f"Current Working Dir: {os.getcwd()}")
print(f"Constants File: {constants.__file__}")
print(f"Loaded URL: {constants.COLLAB_SERVER_URL}")

if "onrender.com" in constants.COLLAB_SERVER_URL:
    print("\n✅ SUCCESS: The app is using your PRIVATE Render URL!")
    print("Shield status: ACTIVE. (GitHub will only see localhost)")
else:
    print("\n❌ WARNING: The app is using the public localhost fallback.")
    print("Check if your .env file is in the root folder.")
