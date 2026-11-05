"""Role-based authorization decorators (used across role dashboards)."""
from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user

from .models.user import UserRole


def role_required(*roles: UserRole):
    """Allow only authenticated users whose role is in ``roles`` (admins always
    pass). Unauthenticated users are sent to login; wrong-role users get 403."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                from flask import redirect, request, url_for

                return redirect(url_for("auth.login", next=request.path))
            if current_user.role is UserRole.ADMIN or current_user.role in roles:
                return view(*args, **kwargs)
            abort(403)

        return wrapped

    return decorator
