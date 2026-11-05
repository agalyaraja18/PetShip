"""Task 8 tests: profiles, account settings, and OAuth graceful disable."""
from __future__ import annotations

import io

from werkzeug.datastructures import FileStorage

from petship.extensions import db
from petship.models.health import OwnedPet
from petship.models.lifestyle import ExpenseItem
from petship.models.user import User, UserRole


def make_user(email="agalya@example.com", role=UserRole.ADOPTER, public=True):
    u = User(email=email, first_name="Agalya", last_name="R", role=role)
    u.set_password("password123")
    u.is_active = True
    u.profile_is_public = public
    db.session.add(u)
    db.session.commit()
    return u


def login(client, email="agalya@example.com"):
    return client.post("/auth/login", data={"email": email, "password": "password123"})


def test_profile_requires_login(client, app):
    resp = client.get("/profile/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_profile_view_renders(client, app):
    make_user()
    login(client)
    resp = client.get("/profile/")
    assert resp.status_code == 200
    assert b"Agalya R" in resp.data


def test_edit_profile_persists_fields_and_tags(client, app):
    make_user()
    login(client)
    resp = client.post(
        "/profile/edit",
        data={
            "first_name": "Agalya",
            "last_name": "Raman",
            "phone": "+91 98400 12345",
            "address": "12 Marina Road",
            "city": "Chennai",
            "bio": "Animal lover, works from home.",
            "lifestyle_tags": ["Apartment", "Has kids", "Works from home"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    user = db.session.scalar(db.select(User).filter_by(email="agalya@example.com"))
    assert user.last_name == "Raman"
    assert user.city == "Chennai"
    assert user.address == "12 Marina Road"
    assert user.bio == "Animal lover, works from home."
    assert set(user.lifestyle_tags) == {"Apartment", "Has kids", "Works from home"}
    page = client.get("/profile/edit")
    for selected in ("Apartment", "Has kids", "Works from home"):
        assert f'value="{selected}"'.encode() in page.data
    assert page.data.count(b'class="pill is-active"') == 3
    assert page.data.count(b'class="lifestyle-tag-input" checked') == 3
    profile = client.get("/profile/")
    assert b"Works from home" in profile.data
    assert b"Has dogs" in profile.data
    assert b"12 Marina Road" in profile.data
    bio_section = profile.data.split(b"<h3>Bio</h3>", 1)[1].split(
        b"<h3>Personal details</h3>", 1
    )[0]
    assert b"Apartment" not in bio_section
    assert b"Works from home" not in bio_section


def test_adopter_profile_lists_owned_pets(client, app):
    from petship.models.health import OwnedPet

    user = make_user()
    db.session.add(OwnedPet(owner_id=user.id, name="Mochi", species="Cat"))
    db.session.commit()
    login(client)
    response = client.get("/profile/")
    assert b"Home &amp; lifestyle" in response.data
    assert b"Bio" in response.data
    assert b"Personal details" in response.data
    assert b"My Pet" in response.data
    assert b"Mochi" in response.data


def test_lifestyle_choices_can_be_cleared(client, app):
    user = make_user()
    user.lifestyle_tags = ["Apartment", "Has dogs", "Has cats"]
    db.session.commit()
    login(client)

    client.post(
        "/profile/edit",
        data={
            "first_name": "Agalya",
            "lifestyle_tags": ["House with yard", "First-time owner"],
        },
    )
    db.session.refresh(user)
    assert user.lifestyle_tags == ["House with yard", "First-time owner"]


def test_edit_profile_rejects_unknown_tags(client, app):
    make_user()
    login(client)
    client.post(
        "/profile/edit",
        data={"first_name": "A", "lifestyle_tags": ["Apartment", "Hacker"]},
    )
    user = db.session.scalar(db.select(User).filter_by(email="agalya@example.com"))
    assert user.lifestyle_tags == ["Apartment"]


def test_avatar_upload_sets_url(client, app):
    make_user()
    login(client)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    data = {
        "first_name": "Agalya",
        "avatar": (io.BytesIO(png), "me.png"),
    }
    client.post(
        "/profile/edit", data=data, content_type="multipart/form-data"
    )
    user = db.session.scalar(db.select(User).filter_by(email="agalya@example.com"))
    assert user.avatar_url is not None
    assert "/static/uploads/avatars/" in user.avatar_url


def test_community_profile_public_visible(client, app):
    u = make_user(public=True)
    resp = client.get(f"/profile/u/{u.id}")
    assert resp.status_code == 200
    assert b"Agalya R" in resp.data


def test_community_profile_private_forbidden(client, app):
    u = make_user(public=False)
    resp = client.get(f"/profile/u/{u.id}")
    assert resp.status_code == 403


def test_notification_prefs_update(client, app):
    make_user()
    login(client)
    # Submit with only some toggles "on".
    client.post(
        "/profile/settings/notifications",
        data={"adoption_updates": "on", "messages": "on"},
    )
    user = db.session.scalar(db.select(User).filter_by(email="agalya@example.com"))
    assert user.prefs["adoption_updates"] is True
    assert user.prefs["messages"] is True
    assert user.prefs["newsletter"] is False
    assert user.prefs["health_reminders"] is False


def test_privacy_toggle(client, app):
    make_user(public=True)
    login(client)
    client.post("/profile/settings/privacy", data={})  # unchecked -> private
    user = db.session.scalar(db.select(User).filter_by(email="agalya@example.com"))
    assert user.profile_is_public is False


def test_2fa_toggle(client, app):
    make_user()
    login(client)
    client.post("/profile/settings/security/2fa", data={"two_factor_enabled": "on"})
    user = db.session.scalar(db.select(User).filter_by(email="agalya@example.com"))
    assert user.two_factor_enabled is True


def test_account_settings_shows_user_id(client, app):
    user = make_user()
    user.public_id = "ADP-00000001"
    db.session.commit()
    login(client)

    response = client.get("/profile/settings")
    assert response.status_code == 200
    assert b"User ID" in response.data
    assert b"ADP-00000001" in response.data
    assert b"Delete account" in response.data
    assert b'action="/profile/settings/delete"' in response.data


def test_delete_account(client, app):
    user = make_user()
    db.session.add(ExpenseItem(
        owner_id=user.id,
        label="Food",
        category="food",
        amount=500,
    ))
    db.session.add(OwnedPet(owner_id=user.id, name="Mochi", species="Cat"))
    db.session.commit()
    login(client)
    resp = client.post("/profile/settings/delete", follow_redirects=False)
    assert resp.status_code == 302
    assert db.session.scalar(db.select(User)) is None
    assert db.session.scalar(db.select(ExpenseItem)) is None
    assert db.session.scalar(db.select(OwnedPet)) is None

    restarted = client.post(
        "/auth/register",
        data={
            "role": "adopter",
            "full_name": "Agalya R",
            "email": "agalya@example.com",
            "phone": "+91 9876543210",
            "address": "12 Marina Road",
            "password": "password123",
            "agree": "y",
        },
    )
    assert restarted.status_code == 302
    assert db.session.scalar(db.select(User).filter_by(email="agalya@example.com")) is not None


def test_google_disabled_without_keys(client, app):
    resp = client.get("/auth/google", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_login_page_hides_google_when_unkeyed(client, app):
    resp = client.get("/auth/login")
    assert b"Continue with Google" not in resp.data


def test_login_page_shows_google_when_keyed(app):
    app.config["GOOGLE_CLIENT_ID"] = "fake-id"
    app.config["GOOGLE_CLIENT_SECRET"] = "fake-secret"
    client = app.test_client()
    resp = client.get("/auth/login")
    assert b"Continue with Google" in resp.data
