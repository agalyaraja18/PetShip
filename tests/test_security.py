"""Task 39 tests: security headers, CSRF, role authorization, a11y skip link."""
from __future__ import annotations

import pytest

from petship import create_app
from petship.extensions import db
from petship.models.user import User, UserRole
from petship.seed import seed_data


# ---- Security headers ----
def test_security_headers_present(client, app):
    resp = client.get("/")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in resp.headers
    assert "Referrer-Policy" in resp.headers
    assert "Permissions-Policy" in resp.headers


def test_csp_restricts_sources(client, app):
    resp = client.get("/")
    csp = resp.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_hsts_only_with_https():
    # Default dev config is http -> no HSTS.
    app = create_app("testing")
    app.config["PREFERRED_URL_SCHEME"] = "http"
    resp = app.test_client().get("/")
    assert "Strict-Transport-Security" not in resp.headers


# ---- CSRF ----
def test_csrf_enforced_in_production_config():
    # The production/dev configs enable CSRF (testing disables it for ease).
    app = create_app("development")
    assert app.config["WTF_CSRF_ENABLED"] is True


# ---- Role authorization matrix ----
@pytest.mark.parametrize(
    "path",
    [
        "/shelter/dashboard",
        "/vet/dashboard",
        "/admin/",
    ],
)
def test_adopter_blocked_from_role_areas(client, app, path):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    assert client.get(path).status_code == 403


def test_shelter_blocked_from_admin(client, app):
    seed_data()
    client.post("/auth/login", data={"role": "shelter", "email": "kavya@demo.petship", "password": "password123"})
    assert client.get("/admin/").status_code == 403


def test_vet_blocked_from_shelter(client, app):
    seed_data()
    client.post("/auth/login", data={"role": "vet", "email": "ananya@demo.petship", "password": "password123"})
    assert client.get("/shelter/dashboard").status_code == 403


def test_admin_can_reach_everything(client, app):
    seed_data()
    client.post("/auth/login", data={"role": "admin", "email": "admin@demo.petship", "password": "password123"})
    # Admin passes role_required for shelter/vet areas too (admins always pass).
    assert client.get("/admin/").status_code == 200
    assert client.get("/shelter/dashboard").status_code == 200
    assert client.get("/vet/dashboard").status_code == 200


def test_anonymous_redirected_to_login(client, app):
    resp = client.get("/me/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


# ---- Accessibility ----
def test_skip_link_present(client, app):
    resp = client.get("/")
    assert b'class="skip-link"' in resp.data
    assert b'id="main-content"' in resp.data


def test_html_has_lang(client, app):
    resp = client.get("/")
    assert b'<html lang="en">' in resp.data
