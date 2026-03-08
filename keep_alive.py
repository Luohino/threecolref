import urllib.request
import time
import sys

# The URL to keep alive
URL = "https://.com/ping"
# Stay below Render's 15-minute timeout
INTERVAL_SECONDS = 600 

def ping():
    try:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Pinging {URL}...")
        with urllib.request.urlopen(URL, timeout=10) as response:
            if response.status == 200:
                print("SUCCESS: Server is awake.")
            else:
                print(f"FAILED: Received status {response.status}")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    print("Starting Render Keep-Alive script...")
    # If running as a one-shot (like in a Cron job), just ping once
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        ping()
    else:
        # Otherwise, run a loop
        while True:
            ping()
            time.sleep(INTERVAL_SECONDS)
