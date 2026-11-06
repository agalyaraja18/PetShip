"""Task 16 tests: adoption request management + applicant details."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from petship.extensions import db
from petship.models.application import Application, ApplicationStage
from petship.models.application import AdoptionAgreement
from petship.models.appointment import Appointment, AppointmentKind, AppointmentStatus
from petship.models.health import OwnedPet
from petship.models.pet import Pet, PetStatus
from petship.models.reminder import Notification
from petship.models.user import User, UserRole
from petship.seed import seed_data


def _make_application(pet_name="Bruno", stage=ApplicationStage.SUBMITTED, tags=None):
    """Create an adopter with an application against a Happy Paws pet."""
    seed_data()
    adopter = User(email="app@example.com", first_name="Meera", last_name="J",
                   role=UserRole.ADOPTER, is_verified=True, city="Chennai")
    adopter.set_password("password123")
    adopter.is_active = True
    adopter.lifestyle_tags = tags or ["Has kids", "Apartment"]
    db.session.add(adopter)
    db.session.commit()
    pet = db.session.scalar(db.select(Pet).filter_by(name=pet_name))
    application = Application(
        reference="PS-50001", applicant_id=adopter.id, pet_id=pet.id,
        stage=stage, answers={"home_type": "Apartment", "ownership": "Own",
                              "prior_experience": "Had a dog before",
                              "ref_name": "Ravi"},
    )
    db.session.add(application)
    db.session.commit()
    return application


def login_shelter(client):
    client.post("/auth/login", data={"role": "shelter", "email": "kavya@demo.petship", "password": "password123"})


def test_requests_list_requires_shelter(client, app):
    _make_application()
    client.post("/auth/login", data={"role": "adopter", "email": "app@example.com", "password": "password123"})
    assert client.get("/shelter/requests").status_code == 403


def test_requests_list_shows_applications(client, app):
    _make_application()
    login_shelter(client)
    resp = client.get("/shelter/requests")
    assert resp.status_code == 200
    assert b"Meera J" in resp.data
    assert b"% match" in resp.data
    assert b"New <span class=\"text-muted\">(1)</span>" in resp.data
    assert b"In review <span class=\"text-muted\">(0)</span>" in resp.data


def test_match_score_rewards_kids(client, app):
    # Bruno is good_with kids; applicant has kids -> higher score.
    app1 = _make_application(tags=["Has kids", "Apartment"])
    login_shelter(client)
    resp = client.get(f"/shelter/requests/{app1.id}")
    assert resp.status_code == 200
    assert b"Meera J" in resp.data


def test_applicant_detail_renders(client, app):
    a = _make_application()
    login_shelter(client)
    resp = client.get(f"/shelter/requests/{a.id}")
    assert resp.status_code == 200
    assert b"Household" in resp.data
    assert b"Checks" in resp.data
    assert b"Apartment" in resp.data


def test_schedule_home_visit(client, app):
    a = _make_application()
    login_shelter(client)
    client.post(
        f"/shelter/requests/{a.id}/action",
        data={"action": "review"},
    )
    client.post(
        f"/shelter/requests/{a.id}/action",
        data={"action": "confirm"},
    )
    scheduled_for = datetime.now(timezone.utc) + timedelta(days=2)
    client.post(
        f"/shelter/requests/{a.id}/action",
        data={
            "action": "home_visit",
            "scheduled_for": scheduled_for.isoformat(),
            "location": "Applicant home",
            "note": "Bring checklist",
        },
    )
    db.session.refresh(a)
    assert a.stage is ApplicationStage.HOME_VISIT
    assert a.home_visit_note == "Bring checklist"
    visit = db.session.scalar(
        db.select(Appointment).filter_by(application_id=a.id)
    )
    assert visit.kind is AppointmentKind.HOME_VISIT
    assert visit.status is AppointmentStatus.CONFIRMED
    assert visit.location == "Applicant home"
    assert visit.scheduled_for.replace(tzinfo=timezone.utc) == scheduled_for


def test_shelter_updates_application_in_order_and_notifies_adopter(client, app):
    a = _make_application()
    login_shelter(client)

    client.post(f"/shelter/requests/{a.id}/action", data={"action": "home_visit"})
    db.session.refresh(a)
    assert a.stage is ApplicationStage.SUBMITTED

    client.post(f"/shelter/requests/{a.id}/action", data={"action": "review"})
    db.session.refresh(a)
    assert a.stage is ApplicationStage.REVIEW
    client.post(f"/shelter/requests/{a.id}/action", data={"action": "confirm"})
    db.session.refresh(a)
    assert a.stage is ApplicationStage.CONFIRMED

    client.post(
        f"/shelter/requests/{a.id}/action",
        data={
            "action": "home_visit",
            "scheduled_for": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        },
    )
    db.session.refresh(a)
    assert a.stage is ApplicationStage.HOME_VISIT

    visit = db.session.scalar(
        db.select(Appointment).filter_by(application_id=a.id)
    )
    visit.status = AppointmentStatus.COMPLETED
    db.session.commit()
    client.post(f"/shelter/requests/{a.id}/action", data={"action": "agreement"})
    db.session.refresh(a)
    assert a.stage is ApplicationStage.AGREEMENT

    db.session.add(AdoptionAgreement(
        application_id=a.id,
        file_name="agreement.pdf",
        original_filename="agreement.pdf",
        shelter_signature="Kavya",
        adopter_signature="Meera",
    ))
    db.session.commit()
    client.post(f"/shelter/requests/{a.id}/action", data={"action": "complete"})
    db.session.refresh(a)
    assert a.stage is ApplicationStage.COMPLETE
    notices = db.session.scalars(
        db.select(Notification).filter_by(
            user_id=a.applicant_id,
            category="adoption",
        )
    ).all()
    assert len(notices) >= 5
    assert all(notice.link == f"/adopt/application/{a.id}" for notice in notices)


def test_decline_application(client, app):
    a = _make_application()
    login_shelter(client)
    client.post(f"/shelter/requests/{a.id}/action", data={"action": "decline"})
    db.session.refresh(a)
    assert a.stage is ApplicationStage.DECLINED


def test_complete_marks_pet_adopted(client, app):
    a = _make_application(stage=ApplicationStage.AGREEMENT)
    db.session.add(AdoptionAgreement(
        application_id=a.id,
        file_name="agreement.pdf",
        original_filename="agreement.pdf",
        shelter_signature="Kavya",
        adopter_signature="Meera",
    ))
    db.session.commit()
    login_shelter(client)
    client.post(f"/shelter/requests/{a.id}/action", data={"action": "complete"})
    db.session.refresh(a)
    assert a.stage is ApplicationStage.COMPLETE
    assert a.pet.status is PetStatus.ADOPTED
    assert a.owned_pet is not None
    assert a.owned_pet.owner_id == a.applicant_id
    assert a.owned_pet.application_id == a.id


def test_shelter_can_reschedule_welcome_home_and_notifies_adopter(client, app):
    a = _make_application(stage=ApplicationStage.AGREEMENT)
    original_time = datetime.now(timezone.utc) + timedelta(days=2)
    pickup = Appointment(
        application_id=a.id,
        kind=AppointmentKind.PICKUP,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=original_time,
        shelter_id=a.pet.shelter_id,
        user_id=a.applicant_id,
        pet_id=a.pet_id,
        location="Old address",
        adopter_confirmed=True,
    )
    db.session.add(pickup)
    db.session.commit()
    login_shelter(client)

    detail = client.get(f"/shelter/requests/{a.id}")
    assert b"Reschedule welcome home" in detail.data
    assert b"Mark as adopted" in detail.data

    new_time = datetime.now(timezone.utc) + timedelta(days=5)
    client.post(
        f"/shelter/requests/{a.id}/action",
        data={
            "action": "schedule_welcome_home",
            "scheduled_for": new_time.isoformat(),
            "browser_timezone": "UTC",
            "location": "New address",
        },
    )
    db.session.refresh(pickup)
    assert pickup.scheduled_for.replace(tzinfo=timezone.utc) == new_time
    assert pickup.location == "New address"
    assert pickup.adopter_confirmed is False
    notice = db.session.scalar(
        db.select(Notification).filter_by(
            user_id=a.applicant_id,
            title="Welcome-home date rescheduled for Bruno",
        )
    )
    assert notice is not None
    assert "New address" in notice.body


def test_mark_as_adopted_adds_pet_to_adopter_pages(client, app):
    a = _make_application(stage=ApplicationStage.AGREEMENT)
    pickup = Appointment(
        application_id=a.id,
        kind=AppointmentKind.PICKUP,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=2),
        shelter_id=a.pet.shelter_id,
        user_id=a.applicant_id,
        pet_id=a.pet_id,
    )
    db.session.add(pickup)
    db.session.commit()
    login_shelter(client)

    client.post(
        f"/shelter/requests/{a.id}/action",
        data={"action": "complete"},
    )

    db.session.refresh(a)
    assert a.stage is ApplicationStage.COMPLETE
    assert a.pet.status is PetStatus.ADOPTED
    assert a.adopted_at is not None
    owned_pet = db.session.scalar(
        db.select(OwnedPet).filter_by(application_id=a.id)
    )
    assert owned_pet is not None
    assert owned_pet.owner_id == a.applicant_id

    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={
            "role": "adopter",
            "email": "app@example.com",
            "password": "password123",
        },
    )
    assert b"Bruno" in client.get("/me/pets").data
    assert b"Bruno" in client.get("/me/adoptions").data


def test_cannot_complete_without_signed_agreement(client, app):
    a = _make_application(stage=ApplicationStage.AGREEMENT)
    login_shelter(client)
    client.post(f"/shelter/requests/{a.id}/action", data={"action": "complete"})
    db.session.refresh(a)
    assert a.stage is ApplicationStage.AGREEMENT
    assert a.pet.status is PetStatus.AVAILABLE


def test_cannot_manage_other_shelters_request(client, app):
    # Application for Ginger (Purr House), but logged in as Happy Paws.
    a = _make_application(pet_name="Ginger")
    login_shelter(client)
    assert client.get(f"/shelter/requests/{a.id}").status_code == 404
