"""Shared pytest fixtures for PetShip.

Tests run against the ``testing`` config (in-memory SQLite, CSRF off). The
application is built once per test session (building it is relatively
expensive — all blueprints, OAuth, scheduler checks), while the database
schema is recreated per test so no state leaks between tests.
"""
from __future__ import annotations

import pytest

from petship import create_app
from petship.extensions import db as _db


@pytest.fixture(scope="session")
def _app():
    """The application, built once for the whole test session."""
    return create_app("testing")


@pytest.fixture()
def app(_app):
    """Per-test app context with a fresh schema."""
    with _app.app_context():
        _db.create_all()
        try:
            yield _app
        finally:
            _db.session.remove()
            _db.drop_all()


@pytest.fixture()
def client(app):
    """A test client bound to the testing app."""
    return app.test_client()


@pytest.fixture()
def db(app):
    """Direct access to the SQLAlchemy session within an app context."""
    return _db
