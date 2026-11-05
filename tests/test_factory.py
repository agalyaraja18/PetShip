"""Task 1 tests: the app factory boots and the health check responds."""
from __future__ import annotations

from petship import create_app


def test_factory_builds_testing_app():
    app = create_app("testing")
    assert app.config["TESTING"] is True
    # CSRF is disabled under the testing config for easy form posting.
    assert app.config["WTF_CSRF_ENABLED"] is False


def test_healthz_returns_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["service"] == "petship"


def test_index_placeholder_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"PetShip" in resp.data
