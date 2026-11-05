"""Task 38 tests: notification preference enforcement + transactional email."""
from __future__ import annotations

import logging

from petship.extensions import db
from petship.models.reminder import Notification
from petship.models.user import User, UserRole
from petship.services.notify import notify


def _user(prefs=None):
    u = User(email="n@example.com", first_name="N", role=UserRole.ADOPTER)
    u.set_password("password123")
    u.is_active = True
    if prefs is not None:
        u.notification_prefs = prefs
    db.session.add(u)
    db.session.commit()
    return u


def test_notify_creates_notification(app):
    with app.app_context():
        u = _user()
        n = notify(u, "Hi", body="Body", category="adoption")
        db.session.commit()
        assert n is not None
        assert db.session.scalar(db.select(Notification).filter_by(user_id=u.id)) is not None


def test_notify_respects_optout(app):
    with app.app_context():
        # Opted out of adoption updates.
        u = _user(prefs={"adoption_updates": False})
        n = notify(u, "Hi", category="adoption")
        db.session.commit()
        assert n is None
        assert db.session.scalar(db.select(Notification).filter_by(user_id=u.id)) is None


def test_notify_allows_other_categories_when_one_optout(app):
    with app.app_context():
        u = _user(prefs={"adoption_updates": False, "health_reminders": True})
        # Adoption suppressed...
        assert notify(u, "A", category="adoption") is None
        # ...health still delivered.
        assert notify(u, "H", category="health") is not None
        db.session.commit()


def test_notify_accepts_user_id(app):
    with app.app_context():
        u = _user()
        n = notify(u.id, "ById", category="messages")
        db.session.commit()
        assert n is not None


def test_notify_sends_email_when_requested(app, caplog):
    with app.app_context():
        u = _user()
        caplog.set_level(logging.INFO)
        notify(u, "Emailed", body="Please read", category="adoption",
               email=True, email_subject="Subject here")
        db.session.commit()
    # Console mail fallback logs the email in dev/test.
    assert "Subject here" in caplog.text


def test_notify_suppresses_email_on_optout(app, caplog):
    with app.app_context():
        u = _user(prefs={"adoption_updates": False})
        caplog.set_level(logging.INFO)
        result = notify(u, "Emailed", category="adoption", email=True,
                        email_subject="Should not send")
        db.session.commit()
    assert result is None
    assert "Should not send" not in caplog.text


def test_unknown_category_always_delivers(app):
    with app.app_context():
        u = _user(prefs={"adoption_updates": False})
        # A category with no preference key is not gated.
        assert notify(u, "General", category="general") is not None
        db.session.commit()
