"""SocketIO real-time events for chat and notifications (Task 32).

Each logged-in user joins a private room named ``user:<id>``. Messages and
notifications are emitted into the recipient's room. HTTP routes (in the
messages blueprint) remain the source of truth and persist data; SocketIO is
the live-delivery layer on top, so the app still works without websockets.
"""
from __future__ import annotations

from flask import request
from flask_login import current_user
from flask_socketio import join_room

from .extensions import socketio


def user_room(user_id: int) -> str:
    return f"user:{user_id}"


def register_socketio_handlers() -> None:
    @socketio.on("connect")
    def _on_connect():  # pragma: no cover - requires a socket client
        if current_user.is_authenticated:
            join_room(user_room(current_user.id))

    @socketio.on("join")
    def _on_join(data):  # pragma: no cover - requires a socket client
        if current_user.is_authenticated:
            join_room(user_room(current_user.id))


def emit_message(recipient_id: int, payload: dict) -> None:
    """Push a chat message to a recipient's room (no-op if sockets idle)."""
    socketio.emit("message", payload, to=user_room(recipient_id))


def emit_notification(user_id: int, payload: dict) -> None:
    """Push a notification to a user's room."""
    socketio.emit("notification", payload, to=user_room(user_id))
