"""Central notification dispatch respecting user preferences (Task 38).

``notify()`` is the single entry point for in-app notifications and optional
transactional emails. It checks the recipient's notification preferences
before creating a Notification row, pushing it live over SocketIO, and
sending an email. This means opt-outs are honoured everywhere.

Category -> preference key mapping lets one call site declare intent
("adoption", "health", "messages") and have the right toggle consulted.
"""
from __future__ import annotations

from flask import url_for

from ..extensions import db
from ..models.reminder import Notification
from ..models.user import User

# Maps a notification category to the preference key that gates it.
CATEGORY_PREF = {
    "adoption": "adoption_updates",
    "health": "health_reminders",
    "appointments": "appointment_updates",
    "messages": "messages",
    "community": "messages",
    "newsletter": "newsletter",
}


def _email_allowed(user: User, category: str) -> bool:
    """Whether an email may be sent for this category (SMS/newsletter gated)."""
    prefs = user.prefs
    if category == "newsletter":
        return bool(prefs.get("newsletter"))
    # Adoption/health/messages emails follow their in-app toggle.
    pref_key = CATEGORY_PREF.get(category)
    return prefs.get(pref_key, True) if pref_key else True


def notify(user, title, body=None, category="general", link=None,
           email=False, email_subject=None, email_body=None):
    """Create an in-app notification (if allowed) and optionally email.

    Returns the created Notification, or None if the user has opted out of the
    category entirely.
    """
    if isinstance(user, int):
        user = db.session.get(User, user)
    if user is None:
        return None

    pref_key = CATEGORY_PREF.get(category)
    allowed = user.prefs.get(pref_key, True) if pref_key else True
    if not allowed:
        return None  # user opted out of this category

    notif = Notification.push(user.id, title=title, body=body,
                              category=category, link=link)
    db.session.flush()

    # Live push over SocketIO (no-op if sockets idle).
    try:
        from ..realtime import emit_notification

        emit_notification(user.id, {"title": title, "body": body})
    except Exception:  # pragma: no cover - realtime optional
        pass

    # Optional transactional email, gated by the same preference.
    if email and _email_allowed(user, category):
        from .mail import send_email

        send_email(
            to=user.email,
            subject=email_subject or title,
            body=email_body or body or title,
        )

    return notif
