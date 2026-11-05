"""WSGI / application entry point.

Usage:
    flask --app wsgi run                     # development server
    gunicorn -k eventlet -w 1 wsgi:app       # production (SocketIO-compatible)

The ``socketio`` object is also exported so the real-time server can be run
with ``socketio.run(app)`` in development when websockets are needed.
"""
from __future__ import annotations

from petship import create_app
from petship.extensions import socketio

app = create_app()


if __name__ == "__main__":
    # Use socketio.run so websocket support works in local development.
    socketio.run(app, host="127.0.0.1", port=5000, debug=True)
