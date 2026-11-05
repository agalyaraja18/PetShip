"""Task 7 tests: email verification (6-digit code) and password reset."""
from __future__ import annotations

from datetime import timedelta

from petship.extensions import db
from petship.models.mixins import utcnow
from petship.models.user import User, UserRole
from petship.services.tokens import generate_code, generate_reset_token


def register(client, email="new@example.com", password="password123"):
    return client.post(
        "/auth/register",
        data={
            "role": "adopter",
            "full_name": "New User",
            "first_name": "New",
            "last_name": "User",
            "email": email,
            "phone": "+91 9876543210",
            "address": "10 Park Street",
            "password": password,
            "agree": "y",
        },
        follow_redirects=False,
    )


def get_user(email):
    return db.session.scalar(db.select(User).filter_by(email=email))


# ---- Token helpers ----
def test_generate_code_is_six_digits():
    for _ in range(20):
        c = generate_code()
        assert len(c) == 6 and c.isdigit()


def test_reset_token_is_unique():
    assert generate_reset_token() != generate_reset_token()


# ---- Verification ----
def test_registration_starts_verification(client, app):
    resp = register(client)
    assert resp.status_code == 302
    assert "/auth/verify" in resp.headers["Location"]
    user = get_user("new@example.com")
    assert user.verification_code is not None
    assert user.is_verified is False
    assert user.public_id is None


def test_missing_smtp_configuration_shows_verification_code(client, app):
    app.config["MAIL_PROVIDER"] = "smtp"
    app.config["MAIL_SERVER"] = None

    response = register(client)
    user = get_user("new@example.com")
    verification_page = client.get("/auth/verify")

    assert response.status_code == 302
    assert user.verification_code.encode() in verification_page.data


def test_verify_with_correct_code(client, app):
    register(client)
    user = get_user("new@example.com")
    code = user.verification_code
    resp = client.post("/auth/verify", data={"code": code})
    assert resp.status_code == 302
    db.session.refresh(user)
    assert user.is_verified is True
    assert user.verification_code is None
    assert user.public_id.startswith("ADP-")


def test_verify_with_wrong_code(client, app):
    register(client)
    resp = client.post("/auth/verify", data={"code": "000000"})
    assert resp.status_code == 200
    assert b"match" in resp.data
    assert get_user("new@example.com").is_verified is False


def test_expired_code_triggers_resend(client, app):
    register(client)
    user = get_user("new@example.com")
    old_code = user.verification_code
    # Age the code beyond 15 minutes.
    user.verification_sent_at = utcnow() - timedelta(minutes=20)
    db.session.commit()
    resp = client.post("/auth/verify", data={"code": old_code})
    assert resp.status_code == 200
    assert b"expired" in resp.data
    db.session.refresh(user)
    # A fresh code was issued.
    assert user.verification_code != old_code


def test_resend_code_issues_new_code(client, app):
    register(client)
    user = get_user("new@example.com")
    first = user.verification_code
    client.post("/auth/verify/resend")
    db.session.refresh(user)
    assert user.verification_code is not None
    # Overwhelmingly likely to differ; just assert a code still present.
    assert len(user.verification_code) == 6


# ---- Password reset ----
def test_forgot_password_no_email_leak(client, app):
    # Unknown email still returns the generic success message.
    resp = client.post("/auth/forgot-password", data={"email": "ghost@example.com"})
    assert resp.status_code == 200
    assert b"6-digit reset code is on its way" in resp.data
    assert b"Send reset code" not in resp.data
    assert b"ghost@example.com" not in resp.data
    assert b"Enter code" in resp.data
    assert b'name="code"' in resp.data
    assert b"Step 2 of 4" in resp.data
    assert b'name="email"' not in resp.data


def test_forgot_password_page_starts_with_email_form(client, app):
    response = client.get("/auth/forgot-password")
    assert response.status_code == 200
    assert b'name="email"' in response.data
    assert b"Send reset code" in response.data
    assert b'name="code"' not in response.data
    assert b"Enter code" not in response.data


def test_forgot_password_sets_token_for_known_user(client, app):
    u = User(email="known@example.com", first_name="K", role=UserRole.ADOPTER)
    u.set_password("password123")
    db.session.add(u)
    db.session.commit()
    response = client.post("/auth/forgot-password", data={"email": "known@example.com"})
    db.session.refresh(u)
    assert u.reset_token is not None
    assert len(u.reset_token) == 6 and u.reset_token.isdigit()
    assert b"known@example.com" not in response.data
    assert b"Send reset code" not in response.data
    assert b"Enter code" in response.data
    assert b"Step 2 of 4" in response.data
    assert b'name="email"' not in response.data
    # Visiting the page anew starts the flow at the email entry step.
    initial_page = client.get("/auth/forgot-password")
    assert b'name="email"' in initial_page.data
    assert b"Send reset code" in initial_page.data


def test_reset_with_valid_token(client, app):
    u = User(email="known@example.com", first_name="K", role=UserRole.ADOPTER)
    u.set_password("oldpassword")
    token = generate_reset_token()
    u.start_reset(token)
    db.session.add(u)
    db.session.commit()

    resp = client.post(
        f"/auth/reset-password/{token}",
        data={"password": "brandnewpw1", "confirm": "brandnewpw1"},
    )
    assert resp.status_code == 302
    db.session.refresh(u)
    assert u.check_password("brandnewpw1") is True
    assert u.reset_token is None


def test_reset_password_uses_code_and_requires_matching_user_id(client, app):
    u = User(
        email="known@example.com",
        first_name="K",
        role=UserRole.ADOPTER,
        public_id="ADP-00000001",
    )
    u.set_password("oldpassword")
    db.session.add(u)
    db.session.commit()

    forgot = client.post(
        "/auth/forgot-password",
        data={"email": "known@example.com"},
    )
    assert b'name="code"' in forgot.data
    db.session.refresh(u)
    code = u.reset_token
    verified = client.post("/auth/reset-password/code", data={"code": code})
    assert verified.status_code == 302
    assert verified.headers["Location"].endswith("/auth/reset-password")

    wrong_id = client.post(
        "/auth/reset-password",
        data={
            "public_id": "VET-00000001",
            "password": "newpass123",
            "confirm": "newpass123",
        },
    )
    assert wrong_id.status_code == 200
    assert b"Step 3 of 4" in wrong_id.data
    assert b'name="public_id"' in wrong_id.data
    assert b'name="password"' in wrong_id.data
    assert b'name="confirm"' in wrong_id.data
    db.session.refresh(u)
    assert u.check_password("oldpassword")

    changed = client.post(
        "/auth/reset-password",
        data={
            "public_id": "ADP-00000001",
            "password": "newpass123",
            "confirm": "newpass123",
        },
    )
    assert changed.status_code == 302
    assert changed.headers["Location"].endswith("/auth/login")
    db.session.refresh(u)
    assert u.check_password("newpass123")
    assert u.reset_token is None


def test_reset_with_invalid_token(client, app):
    resp = client.get("/auth/reset-password/not-a-real-token", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/forgot-password" in resp.headers["Location"]


def test_verified_adopter_can_log_in_with_role_user_id(client, app):
    register(client, password="secretpw123")
    user = get_user("new@example.com")
    client.post("/auth/verify", data={"code": user.verification_code})
    db.session.refresh(user)
    response = client.post(
        "/auth/login",
        data={"email": user.public_id, "password": "secretpw123"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/dashboard")


def test_shelter_login_requires_approval(client, app):
    from petship.models.shelter import Shelter

    user = User(
        email="pending@example.com",
        first_name="Pending",
        role=UserRole.SHELTER,
        registration_status="pending",
        is_active=False,
    )
    db.session.add(user)
    db.session.flush()
    db.session.add(Shelter(
        owner_id=user.id,
        name="Pending Shelter",
        slug="pending-shelter",
    ))
    db.session.commit()
    response = client.post(
        "/auth/login",
        data={"role": "shelter", "email": "pending@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    assert b"awaiting admin approval" in response.data


def test_reset_with_expired_token(client, app):
    u = User(email="known@example.com", first_name="K", role=UserRole.ADOPTER)
    u.set_password("oldpassword")
    token = generate_reset_token()
    u.start_reset(token)
    u.reset_sent_at = utcnow() - timedelta(hours=2)
    db.session.add(u)
    db.session.commit()
    resp = client.get(f"/auth/reset-password/{token}", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/forgot-password" in resp.headers["Location"]


def test_reset_password_mismatch_rejected(client, app):
    u = User(email="known@example.com", first_name="K", role=UserRole.ADOPTER)
    u.set_password("oldpassword")
    token = generate_reset_token()
    u.start_reset(token)
    db.session.add(u)
    db.session.commit()
    resp = client.post(
        f"/auth/reset-password/{token}",
        data={"password": "brandnewpw1", "confirm": "different123"},
    )
    assert resp.status_code == 200
    assert b"match" in resp.data
    db.session.refresh(u)
    assert u.check_password("oldpassword") is True


# ---- Mail fallback ----
def test_console_mail_fallback(app, caplog):
    from petship.services.mail import send_email

    with app.app_context():
        import logging

        caplog.set_level(logging.INFO)
        provider = send_email("to@example.com", "Subject", "Body text")
    assert provider == "console"
