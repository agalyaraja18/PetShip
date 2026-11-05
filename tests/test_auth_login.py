"""Task 6 tests: login/logout, sessions, and role-based shell routing."""
from __future__ import annotations

import pytest

from petship.extensions import db
from petship.models.user import User, UserRole


def make_user(email, role=UserRole.ADOPTER, password="password123", active=True):
    u = User(email=email, first_name="Test", last_name="User", role=role)
    u.set_password(password)
    u.is_active = active
    u.is_verified = True
    db.session.add(u)
    db.session.commit()
    return u


def login(client, email, password="password123", remember=False):
    data = {"email": email, "password": password}
    user = db.session.scalar(db.select(User).filter_by(email=email))
    data["role"] = user.role.value if user is not None else UserRole.ADOPTER.value
    if remember:
        data["remember"] = "y"
    return client.post("/auth/login", data=data, follow_redirects=False)


def test_login_page_renders(client):
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert b"Welcome back" in resp.data
    assert b"Remember me" in resp.data


def test_valid_login_redirects_to_dashboard(client, app):
    make_user("adopter@example.com")
    resp = login(client, "adopter@example.com")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/auth/dashboard")


def test_login_rejects_role_mismatch_for_email_and_user_id(client, app):
    user = make_user("adopter@example.com")
    user.public_id = "ADP-00000001"
    db.session.commit()

    for identifier in (user.email, user.public_id):
        response = client.post(
            "/auth/login",
            data={
                "role": UserRole.VET.value,
                "email": identifier,
                "password": "password123",
            },
        )
        assert response.status_code == 200
        assert b"credentials didn" in response.data


def test_invalid_password_rejected(client, app):
    make_user("adopter@example.com")
    resp = login(client, "adopter@example.com", password="wrong")
    assert resp.status_code == 200
    assert b"match" in resp.data  # "Those credentials didn't match..."


def test_unknown_email_rejected(client, app):
    resp = login(client, "ghost@example.com")
    assert resp.status_code == 200
    assert b"match" in resp.data


def test_suspended_account_blocked(client, app):
    make_user("suspended@example.com", active=False)
    resp = login(client, "suspended@example.com")
    assert resp.status_code == 200
    assert b"suspended" in resp.data


@pytest.mark.parametrize(
    "role,marker",
    [
        # All roles redirect to their full dashboards.
        (UserRole.ADOPTER, b"Good day"),
        (UserRole.SHELTER, b"Shelter overview"),
        (UserRole.VET, b"Today's schedule"),
        (UserRole.ADMIN, b"Platform overview"),
    ],
)
def test_role_routes_to_correct_shell(client, app, role, marker):
    make_user(f"{role.value}@example.com", role=role)
    login(client, f"{role.value}@example.com")
    resp = client.get("/auth/dashboard", follow_redirects=True)
    assert resp.status_code == 200
    assert marker in resp.data


def test_dark_shell_for_shelter_and_admin(client, app):
    for role in (UserRole.SHELTER, UserRole.ADMIN):
        make_user(f"{role.value}@example.com", role=role)
        login(client, f"{role.value}@example.com")
        resp = client.get("/auth/dashboard", follow_redirects=True)
        assert b"shell-dark" in resp.data
        client.get("/auth/logout")


def test_light_shell_for_adopter_and_vet(client, app):
    for role in (UserRole.ADOPTER, UserRole.VET):
        make_user(f"{role.value}@example.com", role=role)
        login(client, f"{role.value}@example.com")
        resp = client.get("/auth/dashboard", follow_redirects=True)
        assert b"shell-light" in resp.data
        client.get("/auth/logout")


def test_session_persists_across_requests(client, app):
    make_user("adopter@example.com")
    login(client, "adopter@example.com")
    # A second request without re-logging-in still resolves the dashboard
    # (adopters redirect to their full dashboard, which renders 200).
    resp = client.get("/auth/dashboard", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Good day" in resp.data


def test_logout_ends_session(client, app):
    make_user("adopter@example.com")
    login(client, "adopter@example.com")
    client.get("/auth/logout")
    # Now the dashboard should redirect to login.
    resp = client.get("/auth/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_remember_me_sets_cookie(client, app):
    make_user("adopter@example.com")
    resp = login(client, "adopter@example.com", remember=True)
    cookies = resp.headers.getlist("Set-Cookie")
    assert any("remember_token" in c for c in cookies)


def test_authenticated_login_redirects_away(client, app):
    make_user("adopter@example.com")
    login(client, "adopter@example.com")
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/auth/dashboard")


def test_next_redirect_only_same_site(client, app):
    make_user("adopter@example.com")
    # External next is ignored; internal next is honoured.
    resp = client.post(
        "/auth/login?next=https://evil.example.com",
        data={"role": "adopter", "email": "adopter@example.com", "password": "password123"},
    )
    assert "evil.example.com" not in resp.headers.get("Location", "")
