"""Task 5 tests: role-specific registration and the User model."""
from __future__ import annotations

import io
import re

from petship.extensions import db
from petship.models.user import User, UserRole


def _register(client, **overrides):
    data = {
        "role": "adopter",
        "full_name": "Agalya R",
        "first_name": "Agalya",
        "last_name": "R",
        "email": "agalya@example.com",
        "phone": "+91 9876543210",
        "address": "12 Marina Road, Chennai",
        "password": "supersecret1",
        "agree": "y",
    }
    data.update(overrides)
    if data["role"] == "shelter":
        data.update({
            "shelter_name": "Happy Paws",
            "owner_name": "Agalya R",
            "shelter_photos": (io.BytesIO(b"photo"), "shelter.jpg"),
        })
    elif data["role"] == "vet":
        data.update({
            "vet_name": "Dr. Agalya R",
            "clinic_name": "Happy Tails",
            "clinic_address": "15 Lake Road",
            "certificate_photo": (io.BytesIO(b"certificate"), "certificate.jpg"),
        })
    return client.post(
        "/auth/register",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )


def test_register_page_renders(client):
    resp = client.get("/auth/register")
    assert resp.status_code == 200
    assert b"Create your account" in resp.data
    # Role toggle options present.
    assert b"Adopter" in resp.data
    assert b"Shelter" in resp.data
    assert b"Vet" in resp.data
    assert resp.data.count(b'name="address"') == 1


def test_register_creates_adopter(client, app):
    resp = _register(client)
    assert resp.status_code == 302  # redirect to register_done
    user = db.session.scalar(db.select(User).filter_by(email="agalya@example.com"))
    assert user is not None
    assert user.role is UserRole.ADOPTER
    assert user.first_name == "Agalya"
    assert user.is_verified is False
    assert user.phone == "+919876543210"
    assert user.address == "12 Marina Road, Chennai"


def test_register_each_role(client, app):
    for i, role in enumerate(["adopter", "shelter", "vet"]):
        _register(client, role=role, email=f"user{i}@example.com")
    roles = {
        u.email: u.role
        for u in db.session.scalars(db.select(User)).all()
    }
    assert roles["user0@example.com"] is UserRole.ADOPTER
    assert roles["user1@example.com"] is UserRole.SHELTER
    assert roles["user2@example.com"] is UserRole.VET
    shelter_user = db.session.scalar(db.select(User).filter_by(email="user1@example.com"))
    vet_user = db.session.scalar(db.select(User).filter_by(email="user2@example.com"))
    assert shelter_user.registration_status == vet_user.registration_status == "pending"
    assert shelter_user.is_active is vet_user.is_active is False


def test_role_specific_requests_include_required_profiles(client, app):
    _register(client, role="shelter", email="shelter@example.com")
    _register(client, role="vet", email="vet@example.com")
    from petship.models.shelter import Shelter
    from petship.models.vet import VetProfile

    shelter_user = db.session.scalar(db.select(User).filter_by(email="shelter@example.com"))
    vet_user = db.session.scalar(db.select(User).filter_by(email="vet@example.com"))
    shelter = db.session.scalar(db.select(Shelter).filter_by(owner_id=shelter_user.id))
    vet = db.session.scalar(db.select(VetProfile).filter_by(user_id=vet_user.id))
    assert shelter.name == "Happy Paws"
    assert shelter.registration_photos
    assert vet.display_name == "Dr. Agalya R"
    assert vet.certificate_url


def test_password_is_hashed_not_plaintext(client, app):
    _register(client, password="plaintextpw123")
    user = db.session.scalar(db.select(User).filter_by(email="agalya@example.com"))
    assert user.password_hash is not None
    assert "plaintextpw123" not in user.password_hash
    assert user.check_password("plaintextpw123") is True
    assert user.check_password("wrong") is False


def test_validation_rejects_short_password(client, app):
    resp = _register(client, password="short")
    assert resp.status_code == 200  # re-renders form, no redirect
    assert db.session.scalar(db.select(User)) is None
    assert b"At least 8 characters" in resp.data


def test_validation_rejects_bad_email(client, app):
    resp = _register(client, email="not-an-email")
    assert resp.status_code == 200
    assert db.session.scalar(db.select(User)) is None


def test_validation_rejects_invalid_phone_number(client, app):
    resp = _register(client, phone="not a phone")
    assert resp.status_code == 200
    assert b"valid phone number" in resp.data
    assert db.session.scalar(db.select(User)) is None


def test_registration_rejects_invalid_email_for_every_role(client, app):
    for role in ("adopter", "shelter", "vet"):
        response = _register(
            client,
            role=role,
            email=f"invalid-{role}",
        )
        assert response.status_code == 200
    assert db.session.scalar(db.select(User)) is None


def test_registration_rejects_invalid_phone_for_every_role(client, app):
    for role in ("adopter", "shelter", "vet"):
        response = _register(
            client,
            role=role,
            email=f"phone-{role}@example.com",
            phone="555-ABCD",
        )
        assert response.status_code == 200
        assert b"valid phone number" in response.data
    assert db.session.scalar(db.select(User)) is None


def test_registration_rejects_impossible_phone_number(client, app):
    response = _register(client, phone="+91 1111111111")
    assert response.status_code == 200
    assert b"valid phone number" in response.data
    assert db.session.scalar(db.select(User)) is None


def test_provider_registration_status_code_is_shown_once(client, app):
    response = _register(client, role="shelter", email="status@example.com")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/registration-received")

    receipt = client.get(response.headers["Location"])
    assert receipt.status_code == 200
    user = db.session.scalar(db.select(User).filter_by(email="status@example.com"))
    assert user.registration_status_token_hash
    assert user.registration_status_token_hash.encode() not in receipt.data
    assert b"Registration access code" in receipt.data
    status_page = client.get("/auth/registration-status")
    assert status_page.status_code == 200
    assert b'value="vet"' in status_page.data
    assert b'value="shelter"' in status_page.data


def test_registration_status_requires_role_email_and_secret_code(client, app):
    receipt = _register(client, role="vet", email="status-vet@example.com")
    receipt_page = client.get(receipt.headers["Location"])
    user = db.session.scalar(
        db.select(User).filter_by(email="status-vet@example.com")
    )
    match = re.search(
        rb'<strong class="text-lg"[^>]*>([^<]+)</strong>',
        receipt_page.data,
    )
    assert match
    access_code = match.group(1).decode()

    invalid = client.post(
        "/auth/registration-status",
        data={
            "role": "shelter",
            "email": user.email,
            "access_code": access_code,
        },
    )
    assert b"Registration under review" not in invalid.data

    pending = client.post(
        "/auth/registration-status",
        data={
            "role": "vet",
            "email": user.email,
            "access_code": access_code,
        },
    )
    assert b"Registration under review" in pending.data
    assert b"Check status" not in pending.data
    assert b'name="access_code"' not in pending.data

    from petship.blueprints.admin import _approve_registration

    _approve_registration(user)
    db.session.commit()
    approved = client.post(
        "/auth/registration-status",
        data={
            "role": "vet",
            "email": user.email,
            "access_code": access_code,
        },
    )
    assert b"Your clinic is approved" in approved.data
    assert user.public_id.encode() in approved.data
    assert b"Create a password" in approved.data
    assert b"Check status" not in approved.data
    assert b'name="access_code"' not in approved.data

    password_response = client.post(
        "/auth/registration-status",
        data={
            "action": "set_password",
            "password": "securepassword123",
            "confirm": "securepassword123",
        },
    )
    assert password_response.status_code == 302
    db.session.refresh(user)
    assert user.check_password("securepassword123")
    assert user.force_password_reset is False


def test_duplicate_shelter_application_is_not_created_or_queued(client, app):
    from petship.models.shelter import Shelter

    _register(client, role="shelter", email="first-shelter@example.com")
    duplicate = _register(client, role="shelter", email="second-shelter@example.com")
    assert duplicate.status_code == 200
    assert b"already on file" in duplicate.data
    assert db.session.scalar(db.select(db.func.count()).select_from(Shelter)) == 1


def test_duplicate_veterinarian_application_is_not_created_or_queued(client, app):
    from petship.models.vet import VetProfile

    _register(client, role="vet", email="first-vet@example.com")
    duplicate = _register(client, role="vet", email="second-vet@example.com")
    assert duplicate.status_code == 200
    assert b"already on file" in duplicate.data
    assert db.session.scalar(db.select(db.func.count()).select_from(VetProfile)) == 1


def test_must_accept_terms(client, app):
    resp = _register(client, agree="")
    assert resp.status_code == 200
    assert db.session.scalar(db.select(User)) is None


def test_duplicate_email_blocked(client, app):
    _register(client)
    resp = _register(client, first_name="Other")
    assert resp.status_code == 200
    assert b"already exists" in resp.data
    count = db.session.scalar(db.select(db.func.count()).select_from(User))
    assert count == 1


def test_admin_role_cannot_be_selected(client, app):
    # Submitting role=admin is rejected by SelectField choice validation;
    # no account is created and the form re-renders.
    resp = _register(client, role="admin")
    assert resp.status_code == 200
    assert db.session.scalar(db.select(User)) is None


def test_user_display_helpers(app):
    u = User(email="pat.kim@example.com", first_name="Pat", last_name="Kim")
    assert u.full_name == "Pat Kim"
    assert u.initials == "PK"
    u2 = User(email="solo@example.com")
    assert u2.full_name == "solo"
    assert u2.initials == "S"
