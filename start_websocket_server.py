#!/usr/bin/env python
"""
Start Django server with WebSocket support using Daphne
"""
import os
import subprocess
import sys

def start_daphne_server():
    """Start Daphne server for WebSocket support"""
    print("Starting Django server with WebSocket support...")
    print("Press Ctrl+C to stop the server")

    # Change to backend directory
    backend_dir = r"C:\Users\planeteye01\Documents\backend"
    os.chdir(backend_dir)

    # Set environment variables
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

    # Start Daphne server
    cmd = [
        sys.executable, '-m', 'daphne',
        '-b', '127.0.0.1',  # bind to localhost
        '-p', '8000',       # port 8000
        'backend.asgi:application'  # ASGI application
    ]

    print(f"Running command: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"Server failed to start: {e}")
        print("Make sure Daphne is installed: pip install daphne")

if __name__ == '__main__':
    start_daphne_server()