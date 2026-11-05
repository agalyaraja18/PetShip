"""Task 2 tests: the users table exists and the model round-trips."""
from __future__ import annotations

from sqlalchemy import inspect

from petship.extensions import db
from petship.models import User
from petship.models.user import UserRole


def test_users_table_exists(app):
    inspector = inspect(db.engine)
    assert "users" in inspector.get_table_names()
    columns = {c["name"] for c in inspector.get_columns("users")}
    assert {"id", "email", "role", "is_active", "is_verified"} <= columns


def test_user_persists_with_default_role(app):
    user = User(email="pat@example.com")
    db.session.add(user)
    db.session.commit()

    loaded = db.session.get(User, user.id)
    assert loaded is not None
    assert loaded.email == "pat@example.com"
    assert loaded.role is UserRole.ADOPTER
    assert loaded.is_active is True
    assert loaded.is_verified is False
    assert loaded.created_at is not None


def test_email_is_unique(app):
    db.session.add(User(email="dup@example.com"))
    db.session.commit()
    db.session.add(User(email="dup@example.com"))
    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
