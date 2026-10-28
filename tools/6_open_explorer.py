"""Open the Demographic Data Explorer in your browser.

What it does
    Starts a small web server for the repository folder and opens
    http://127.0.0.1:8000/explorer/index.html in your default browser.
    The server answers this computer only (127.0.0.1). Other computers cannot reach it.

Why a server is needed
    A browser blocks a page opened straight from disk from reading the config
    folder. Without the server, TRPA notes, the known-errors check, and the
    added-medians check in the Explorer are empty.

What it reads
    Files in this repository, served to your own browser. The Explorer page
    itself reads the published TRPA services, read only.

What it writes
    Nothing.

How to run it
    Double-click this file, or run: python tools/6_open_explorer.py
    Leave the window open while you use the Explorer. Close the window, or
    press Ctrl+C, to stop the server.
    Same as: python -m http.server 8000 --bind 127.0.0.1
    Any Python works. This script needs only the standard library.

Settings
    explorer_port in config/settings.json sets the port. It is 8000 when not set.
"""
import functools
import http.server
import json
import sys
import threading
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = REPO_ROOT / "config" / "settings.json"
HOST = "127.0.0.1"


def _port() -> int:
    try:
        return int(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")).get("explorer_port", 8000))
    except (OSError, ValueError):
        return 8000


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Serves repository files without printing a line for every request."""

    def log_message(self, format, *args):
        pass


def main():
    port = _port()
    handler = functools.partial(_QuietHandler, directory=str(REPO_ROOT))
    try:
        server = http.server.ThreadingHTTPServer((HOST, port), handler)
    except OSError:
        print(f"Port {port} is already in use. The Explorer may already be open in another window.")
        print(f"Close that window, or set explorer_port in config/settings.json to another number.")
        input("\nPress Enter to close this window.")
        sys.exit(1)

    url = f"http://{HOST}:{port}/explorer/index.html"
    print(f"Opening {url}")
    print("Leave this window open while you use the Explorer. Close it to stop.")
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
