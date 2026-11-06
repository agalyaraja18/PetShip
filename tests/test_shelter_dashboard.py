"""Task 14 tests: shelter dashboard, profile, and public page."""
from __future__ import annotations

from datetime import datetime, timezone

from petship.extensions import db
from petship.models.application import Application, ApplicationStage
from petship.models.application import ReturnStatus
from petship.models.shelter import Shelter
from petship.models.user import User, UserRole
from petship.seed import seed_data


def login_shelter(client):
    """Seed creates kavya@demo.petship (shelter owner of Happy Paws)."""
    seed_data()
    client.post(
        "/auth/login",
        data={"role": "shelter", "email": "kavya@demo.petship", "password": "password123"},
    )


def test_dashboard_requires_shelter_role(client, app):
    seed_data()
    # Adopter cannot access the shelter dashboard.
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    resp = client.get("/shelter/dashboard")
    assert resp.status_code == 403


def test_dashboard_renders_for_shelter(client, app):
    login_shelter(client)
    resp = client.get("/shelter/dashboard")
    assert resp.status_code == 200
    assert b"Shelter overview" in resp.data
    assert b"Listed pets" in resp.data
    assert b"shell-dark" in resp.data  # dark shelter shell
    assert b"Appointments" not in resp.data
    assert b"Follow-ups" not in resp.data
    assert b">Notifications<" not in resp.data
    assert b"Return Requests" in resp.data


def test_dashboard_stats_count_pets(client, app):
    login_shelter(client)
    resp = client.get("/shelter/dashboard")
    # Happy Paws has several listed pets in the seed.
    shelter = db.session.scalar(db.select(Shelter).filter_by(slug="happy-paws"))
    assert str(len(shelter.pets)).encode() in resp.data


def test_dashboard_shows_shelter_metrics_recent_returns_and_monthly_adoptions(
    client, app
):
    login_shelter(client)
    shelter = db.session.scalar(db.select(Shelter).filter_by(slug="happy-paws"))
    adopter = db.session.scalar(
        db.select(User).filter_by(email="agalya@demo.petship")
    )
    pets = shelter.pets[:3]
    now = datetime.now(timezone.utc)
    db.session.add_all([
        Application(
            reference="PS-DASH-NEW",
            applicant_id=adopter.id,
            pet_id=pets[0].id,
            stage=ApplicationStage.SUBMITTED,
            return_status=ReturnStatus.SUBMITTED.value,
            return_reason="Needs a different home.",
            return_requested_at=now,
        ),
        Application(
            reference="PS-DASH-ADOPTED",
            applicant_id=adopter.id,
            pet_id=pets[1].id,
            stage=ApplicationStage.COMPLETE,
            adopted_at=now,
            return_status=ReturnStatus.RETURNED_SHELTER.value,
            returned_at=now,
            return_reason="Returned for care.",
            return_requested_at=now,
        ),
    ])
    db.session.commit()

    response = client.get("/shelter/dashboard")

    assert response.status_code == 200
    for label in (
        b"Listed pets",
        b"Adopted pets",
        b"Returned pets",
        b"New adoption requests",
        b"New return requests",
        b"Verified",
        b"Recent adoption requests",
        b"Recent return requests",
        b"Adoptions per month",
        b"Needs a different home.",
        b"Returned for care.",
    ):
        assert label in response.data
    assert pets[0].name.encode() in response.data
    assert pets[1].name.encode() in response.data


def test_shelter_role_dashboard_redirect(client, app):
    login_shelter(client)
    resp = client.get("/auth/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert "/shelter/dashboard" in resp.headers["Location"]


def test_profile_edit_persists(client, app):
    login_shelter(client)
    resp = client.post(
        "/shelter/profile",
        data={
            "name": "Happy Paws Rescue",
            "city": "Adyar, Chennai",
            "about": "We rehome street animals.",
            "contact_name": "Kavya S",
            "capacity": "80",
            "operating_since": "2014",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    shelter = db.session.scalar(db.select(Shelter).filter_by(slug="happy-paws"))
    assert shelter.name == "Happy Paws Rescue"
    assert shelter.capacity == 80


def test_shelter_profile_shows_edit_button_and_edit_form(client, app):
    login_shelter(client)
    view = client.get("/shelter/profile")
    assert view.status_code == 200
    assert b"Edit profile" in view.data
    assert b'name="name"' not in view.data

    edit = client.get("/shelter/profile?edit=1")
    assert edit.status_code == 200
    assert b'name="name"' in edit.data
    assert b"Save changes" in edit.data


def test_shelter_profile_displays_and_updates_requested_details(client, app):
    login_shelter(client)
    client.post(
        "/shelter/profile",
        data={
            "name": "Happy Paws",
            "address": "12 Marina Road",
            "city": "Chennai",
            "phone": "+91 9876543210",
            "about": "A local rescue shelter.",
            "contact_name": "Kavya",
            "registration_no": "TN-123",
            "capacity": "60",
            "operating_since": "2012",
        },
    )
    response = client.get("/shelter/profile")
    assert response.status_code == 200
    for value in (
        b"Happy Paws",
        b"Shelter",
        b"Kavya",
        b"12 Marina Road",
        b"+91 9876543210",
        b"A local rescue shelter.",
        b"TN-123",
        b"60",
        b"2012",
    ):
        assert value in response.data


def test_shelter_settings_persist_notification_preferences(client, app):
    login_shelter(client)
    user = db.session.scalar(
        db.select(User).filter_by(email="kavya@demo.petship")
    )
    user.public_id = "SHL-00000001"
    db.session.commit()
    page = client.get("/shelter/settings")
    assert page.status_code == 200
    assert b"Notification preferences" in page.data
    assert page.data.index(b"Adoption requests") < page.data.index(b"Return requests")
    assert page.data.index(b"Return requests") < page.data.index(b"Smart reminders")
    assert b"Appointments" not in page.data
    assert b"Care reminders" not in page.data
    assert b"Two-factor authentication" in page.data
    assert b"User ID" in page.data
    assert b"SHL-00000001" in page.data
    assert b"Delete account" in page.data
    assert b'action="/profile/settings/delete"' in page.data

    client.post(
        "/shelter/settings",
        data={
            "section": "notifications",
            "adoption_updates": "on",
            "return_requests": "on",
            "smart_reminders": "on",
        },
    )
    shelter_user = db.session.scalar(
        db.select(User).filter_by(email="kavya@demo.petship")
    )
    assert shelter_user.prefs["adoption_updates"] is True
    assert shelter_user.prefs["return_requests"] is True
    assert shelter_user.prefs["smart_reminders"] is True


def test_shelter_can_delete_account_and_shelter_data(client, app):
    login_shelter(client)
    user = db.session.scalar(
        db.select(User).filter_by(email="kavya@demo.petship")
    )
    user_id = user.id
    shelter = db.session.scalar(db.select(Shelter).filter_by(owner_id=user_id))
    shelter_id = shelter.id

    response = client.post("/profile/settings/delete", follow_redirects=False)
    assert response.status_code == 302
    assert db.session.get(User, user_id) is None
    assert db.session.get(Shelter, shelter_id) is None


def test_shelter_notifications_show_requests_and_home_visits(client, app):
    from datetime import datetime, timedelta, timezone

    from petship.models.application import Application, ApplicationStage
    from petship.models.appointment import Appointment, AppointmentKind, AppointmentStatus
    from petship.models.pet import Pet
    from petship.models.reminder import Notification

    login_shelter(client)
    shelter = db.session.scalar(db.select(Shelter).filter_by(slug="happy-paws"))
    adopter = db.session.scalar(
        db.select(User).filter_by(email="agalya@demo.petship")
    )
    pet = db.session.scalar(db.select(Pet).filter_by(name="Bruno"))
    application = Application(
        reference="PS-85123",
        applicant_id=adopter.id,
        pet_id=pet.id,
        stage=ApplicationStage.SUBMITTED,
        answers={},
    )
    db.session.add(application)
    db.session.flush()
    appointment = Appointment(
        application_id=application.id,
        kind=AppointmentKind.HOME_VISIT,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=datetime.now(timezone.utc) + timedelta(hours=2),
        shelter_id=shelter.id,
        user_id=adopter.id,
        pet_id=pet.id,
    )
    db.session.add(appointment)
    Notification.push(
        shelter.owner_id,
        "Application update",
        category="adoption",
        link=f"/shelter/requests/{application.id}",
    )
    db.session.commit()

    response = client.get("/shelter/notifications")
    assert response.status_code == 200
    assert b"New adoption requests" in response.data
    assert b"PS-85123" in response.data
    assert b"Appointments &amp; home visits" in response.data
    assert b"Home visit reminder: Bruno" in response.data
    assert b"Application update" in response.data
    assert b"Adoption" in response.data
    assert b"Appointments" in response.data

    adoption_only = client.get("/shelter/notifications?category=adoption")
    assert b"Application update" in adoption_only.data
    assert b"Home visit reminder: Bruno" not in adoption_only.data


def test_public_shelter_page(client, app):
    seed_data()
    resp = client.get("/shelter/happy-paws")
    assert resp.status_code == 200
    assert b"Happy Paws Shelter" in resp.data
    assert b"Verified" in resp.data
    assert b"Bruno" in resp.data  # an available pet from this shelter


def test_public_shelter_404(client, app):
    resp = client.get("/shelter/does-not-exist")
    assert resp.status_code == 404
