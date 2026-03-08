import os
import asyncio
import logging
import sys

# Robust path handling: check current dir and parent dir for threecolref
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

if os.path.isdir(os.path.join(current_dir, 'threecolref')):
    sys.path.append(current_dir)
elif os.path.isdir(os.path.join(parent_dir, 'threecolref')):
    sys.path.append(parent_dir)

from threecolref.collaboration.server import CollaborationServer

# Configure logging for Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("render-backend")

async def main():
    # Render provides the port via the PORT environment variable
    port_str = os.environ.get("PORT", "8080")
    try:
        port = int(port_str)
    except ValueError:
        logger.error(f"Invalid PORT environment variable: {port_str}. Falling back to 8080.")
        port = 8080
    
    logger.info(f"Setting up Collaboration Server on port {port}...")
    
    # Instantiate the server
    server = CollaborationServer()
    
    # We call _serve directly instead of start() to run in the main asyncio loop
    # as required by cloud platforms like Render.
    try:
        await server._serve(port)
    except Exception as e:
        logger.fatal(f"Server crashed: {e}", exc_info=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
