"""Task 13 tests: adoption application wizard, drafts, and tracking."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from werkzeug.datastructures import MultiDict

from petship.extensions import db
from petship.models.application import Application, ApplicationStage
from petship.models.appointment import Appointment, AppointmentKind, AppointmentStatus
from petship.models.reminder import Notification
from petship.models.pet import Pet, PetStatus
from petship.models.user import User, UserRole
from petship.seed import seed_data


def setup_adopter(client, app):
    seed_data()
    u = User(email="a@example.com", first_name="Agalya", role=UserRole.ADOPTER)
    u.set_password("password123")
    u.is_active = True
    db.session.add(u)
    db.session.commit()
    client.post("/auth/login", data={"role": "adopter", "email": "a@example.com", "password": "password123"})
    return u


def bruno():
    return db.session.scalar(db.select(Pet).filter_by(name="Bruno"))


def test_other_pets_accepts_multiple_selections(client, app):
    setup_adopter(client, app)
    pet = bruno()
    client.get(f"/adopt/start/{pet.id}")
    draft = db.session.scalar(db.select(Application).filter_by(pet_id=pet.id))

    response = client.post(
        f"/adopt/application/{draft.id}/step/2",
        data=MultiDict([
            ("prior_experience", "Previously owned pets"),
            ("other_pets", "Dogs"),
            ("other_pets", "Cats"),
            ("current_pets_count", "2"),
            ("action", "next"),
        ]),
    )
    assert response.status_code == 302
    db.session.refresh(draft)
    assert draft.answers["other_pets"] == "Dogs, Cats"


def test_start_requires_login(client, app):
    seed_data()
    pet = bruno()
    resp = client.get(f"/adopt/start/{pet.id}", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_start_creates_draft(client, app):
    setup_adopter(client, app)
    pet = bruno()
    resp = client.get(f"/adopt/start/{pet.id}", follow_redirects=False)
    assert resp.status_code == 302
    draft = db.session.scalar(db.select(Application).filter_by(pet_id=pet.id))
    assert draft is not None
    assert draft.stage is ApplicationStage.DRAFT
    assert draft.reference.startswith("PS-")


def test_start_reuses_existing_draft(client, app):
    setup_adopter(client, app)
    pet = bruno()
    client.get(f"/adopt/start/{pet.id}")
    client.get(f"/adopt/start/{pet.id}")
    count = db.session.scalar(
        db.select(db.func.count()).select_from(Application).filter_by(pet_id=pet.id)
    )
    assert count == 1


def test_wizard_step_saves_answers(client, app):
    setup_adopter(client, app)
    pet = bruno()
    client.get(f"/adopt/start/{pet.id}")
    draft = db.session.scalar(db.select(Application).filter_by(pet_id=pet.id))
    client.post(
        f"/adopt/application/{draft.id}/step/1",
        data={"applicant_name": "Agalya", "applicant_phone": "555-0101",
              "applicant_address": "12 Marina Road", "home_type": "Apartment", "ownership": "Own",
              "sleep_location": "Living room", "hours_alone": "2 to 4",
              "action": "next"},
    )
    db.session.refresh(draft)
    assert draft.answers["home_type"] == "Apartment"
    assert draft.answers["hours_alone"] == "2 to 4"


def test_save_draft_keeps_stage_draft(client, app):
    setup_adopter(client, app)
    pet = bruno()
    client.get(f"/adopt/start/{pet.id}")
    draft = db.session.scalar(db.select(Application).filter_by(pet_id=pet.id))
    client.post(
        f"/adopt/application/{draft.id}/step/1",
        data={"home_type": "Apartment", "action": "save"},
    )
    db.session.refresh(draft)
    assert draft.stage is ApplicationStage.DRAFT
    assert draft.answers["home_type"] == "Apartment"


def test_resume_draft_from_saved_step(client, app):
    setup_adopter(client, app)
    pet = bruno()
    client.get(f"/adopt/start/{pet.id}")
    draft = db.session.scalar(db.select(Application).filter_by(pet_id=pet.id))
    # Advance to step 2 and follow the redirect so step 2 is actually visited.
    client.post(
        f"/adopt/application/{draft.id}/step/1",
        data={"applicant_name": "Agalya", "applicant_phone": "555-0101",
              "applicant_address": "12 Marina Road", "action": "next"},
        follow_redirects=True,
    )
    db.session.refresh(draft)
    # Highest step reached is now 2 (step 2 was rendered).
    assert draft.step >= 2


def test_submit_moves_to_submitted(client, app):
    setup_adopter(client, app)
    pet = bruno()
    client.get(f"/adopt/start/{pet.id}")
    draft = db.session.scalar(db.select(Application).filter_by(pet_id=pet.id))
    draft.answers = {
        "applicant_name": "Agalya",
        "applicant_phone": "555-0101",
        "applicant_address": "12 Marina Road",
        "current_pets_count": "0",
    }
    db.session.commit()
    resp = client.post(
        f"/adopt/application/{draft.id}/step/4",
        data={"action": "submit"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.session.refresh(draft)
    assert draft.stage is ApplicationStage.SUBMITTED
    tracking_page = client.get(resp.headers["Location"])
    assert b"Back to Adoptions" in tracking_page.data
    notices = db.session.scalars(
        db.select(Notification).filter_by(category="adoption")
    ).all()
    assert any("Application submitted" in notice.title for notice in notices)
    assert any("New application" in notice.title for notice in notices)


def test_application_wizard_collects_contact_and_current_pet_count(client, app):
    setup_adopter(client, app)
    pet = bruno()
    client.get(f"/adopt/start/{pet.id}")
    draft = db.session.scalar(db.select(Application).filter_by(pet_id=pet.id))
    contact_page = client.get(f"/adopt/application/{draft.id}/step/1")
    assert b'name="applicant_name"' in contact_page.data
    assert b'name="applicant_phone"' in contact_page.data
    assert b'name="applicant_address"' in contact_page.data
    pet_count_page = client.get(f"/adopt/application/{draft.id}/step/2")
    assert b'name="current_pets_count"' in pet_count_page.data


def test_application_submission_requires_contact_details_and_pet_count(client, app):
    setup_adopter(client, app)
    pet = bruno()
    client.get(f"/adopt/start/{pet.id}")
    draft = db.session.scalar(db.select(Application).filter_by(pet_id=pet.id))
    response = client.post(
        f"/adopt/application/{draft.id}/step/4",
        data={"action": "submit"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/adopt/application/{draft.id}/step/1")
    db.session.refresh(draft)
    assert draft.stage is ApplicationStage.DRAFT


def test_tracking_page_renders(client, app):
    setup_adopter(client, app)
    pet = bruno()
    client.get(f"/adopt/start/{pet.id}")
    draft = db.session.scalar(db.select(Application).filter_by(pet_id=pet.id))
    draft.stage = ApplicationStage.HOME_VISIT
    db.session.commit()
    resp = client.get(f"/adopt/application/{draft.id}")
    assert resp.status_code == 200
    assert b"Application status" in resp.data
    assert draft.reference.encode() in resp.data
    assert b"Home visit" in resp.data
    assert b"Cancel Adoption" in resp.data
    assert resp.data.count(b"Cancel Adoption") == 1


def test_completed_adoption_tracking_hides_progress_steps(client, app):
    adopter = setup_adopter(client, app)
    pet = bruno()
    application = Application(
        reference="PS-COMPLETE-TRACK",
        applicant_id=adopter.id,
        pet_id=pet.id,
        stage=ApplicationStage.COMPLETE,
        adopted_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.session.add(application)
    db.session.commit()

    response = client.get(f"/adopt/application/{application.id}")

    assert response.status_code == 200
    assert b"Adoption complete" in response.data
    assert b"Progress" not in response.data
    assert b"Step 6 of 6" not in response.data


def test_returned_adoption_tracking_hides_progress_steps(client, app):
    adopter = setup_adopter(client, app)
    pet = bruno()
    application = Application(
        reference="PS-RETURNED-TRACK",
        applicant_id=adopter.id,
        pet_id=pet.id,
        stage=ApplicationStage.COMPLETE,
        adopted_at=datetime.now(timezone.utc) - timedelta(days=4),
        returned_at=datetime.now(timezone.utc),
        return_status="returned_shelter",
        return_reason="Needs a different home.",
    )
    db.session.add(application)
    db.session.commit()

    response = client.get(f"/adopt/application/{application.id}")

    assert response.status_code == 200
    assert b"Return completed" in response.data
    assert b"Progress" not in response.data
    assert b"Step 6 of 6" not in response.data


def test_cancel_adoption_cancels_application_and_home_visit(client, app):
    adopter = setup_adopter(client, app)
    pet = bruno()
    pet.reserve()
    application = Application(
        reference="PS-CANCEL-TEST",
        applicant_id=adopter.id,
        pet_id=pet.id,
        stage=ApplicationStage.HOME_VISIT,
        step=4,
    )
    db.session.add(application)
    db.session.flush()
    appointment = Appointment(
        kind=AppointmentKind.HOME_VISIT,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=2),
        user_id=adopter.id,
        shelter_id=pet.shelter_id,
        pet_id=pet.id,
        application_id=application.id,
    )
    db.session.add(appointment)
    db.session.commit()

    response = client.post(
        f"/adopt/application/{application.id}/cancel",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Adoption cancelled" in response.data
    db.session.refresh(application)
    db.session.refresh(appointment)
    db.session.refresh(pet)
    assert application.stage is ApplicationStage.DECLINED
    assert application.applicant_cancelled is True
    assert appointment.status is AppointmentStatus.CANCELLED
    assert pet.status is PetStatus.AVAILABLE
    assert b"Cancelled" in response.data


def test_active_application_has_reschedule_visit_button(client, app):
    adopter = setup_adopter(client, app)
    application = Application(
        reference="PS-54321",
        applicant_id=adopter.id,
        pet_id=bruno().id,
        stage=ApplicationStage.HOME_VISIT,
        step=3,
    )
    db.session.add(application)
    db.session.commit()

    response = client.get("/adopt/applications")
    assert response.status_code == 200
    assert b"Reschedule visit" in response.data
    assert f"/adopt/application/{application.id}#reschedule-visit".encode() in response.data


def test_reschedule_visit_creates_pending_shelter_request(client, app):
    adopter = setup_adopter(client, app)
    pet = bruno()
    application = Application(
        reference="PS-51234",
        applicant_id=adopter.id,
        pet_id=pet.id,
        stage=ApplicationStage.HOME_VISIT,
        answers={},
    )
    db.session.add(application)
    db.session.commit()
    requested = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
        second=0, microsecond=0
    )
    response = client.post(
        f"/adopt/application/{application.id}/visit/reschedule",
        data={"scheduled_for": requested.isoformat()},
    )
    assert response.status_code == 302
    appointment = db.session.scalar(
        db.select(Appointment).filter_by(application_id=application.id)
    )
    assert appointment is not None
    assert appointment.kind is AppointmentKind.HOME_VISIT
    assert appointment.status is AppointmentStatus.PENDING
    assert appointment.scheduled_for.replace(tzinfo=timezone.utc) == requested


def test_adopter_confirms_availability_for_scheduled_home_visit(client, app):
    adopter = setup_adopter(client, app)
    pet = bruno()
    application = Application(
        reference="PS-51235",
        applicant_id=adopter.id,
        pet_id=pet.id,
        stage=ApplicationStage.HOME_VISIT,
        answers={},
    )
    appointment = Appointment(
        application=application,
        kind=AppointmentKind.HOME_VISIT,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=2),
        shelter_id=pet.shelter_id,
        user_id=adopter.id,
        pet_id=pet.id,
    )
    db.session.add_all([application, appointment])
    db.session.commit()

    tracking = client.get(f"/adopt/application/{application.id}")
    response = client.post(
        f"/adopt/application/{application.id}/visit/confirm",
        follow_redirects=True,
    )
    assert response.status_code == 200
    db.session.refresh(appointment)
    assert appointment.adopter_confirmed is True
    notice = db.session.scalar(
        db.select(Notification).filter_by(
            user_id=pet.shelter.owner_id,
            title=f"Adopter confirmed home visit for {pet.name}",
        )
    )
    assert notice is not None
    assert appointment.scheduled_for.strftime("%d %b %Y at %I:%M %p") in notice.body


def test_adopter_cannot_confirm_unconfirmed_visit_time(client, app):
    adopter = setup_adopter(client, app)
    pet = bruno()
    application = Application(
        reference="PS-51236",
        applicant_id=adopter.id,
        pet_id=pet.id,
        stage=ApplicationStage.HOME_VISIT,
        answers={},
    )
    appointment = Appointment(
        application=application,
        kind=AppointmentKind.HOME_VISIT,
        status=AppointmentStatus.PENDING,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=2),
        shelter_id=pet.shelter_id,
        user_id=adopter.id,
        pet_id=pet.id,
    )
    db.session.add_all([application, appointment])
    db.session.commit()

    response = client.post(
        f"/adopt/application/{application.id}/visit/confirm",
        follow_redirects=True,
    )
    assert b"The shelter must confirm a visit time before you can confirm availability." in response.data
    db.session.refresh(appointment)
    assert appointment.adopter_confirmed is False


def test_stage_step_number(app):
    a = Application(reference="PS-1", applicant_id=1, pet_id=1,
                    stage=ApplicationStage.REVIEW)
    assert a.step_number == 2  # submitted=1, review=2


def test_cannot_access_others_application(client, app):
    setup_adopter(client, app)
    pet = bruno()
    client.get(f"/adopt/start/{pet.id}")
    draft = db.session.scalar(db.select(Application).filter_by(pet_id=pet.id))
    # Log in as a different user.
    other = User(email="b@example.com", first_name="B", role=UserRole.ADOPTER)
    other.set_password("password123")
    other.is_active = True
    db.session.add(other)
    db.session.commit()
    client.get("/auth/logout")
    client.post("/auth/login", data={"role": "adopter", "email": "b@example.com", "password": "password123"})
    resp = client.get(f"/adopt/application/{draft.id}")
    assert resp.status_code == 404


def test_my_applications_excludes_drafts(client, app):
    setup_adopter(client, app)
    pet = bruno()
    client.get(f"/adopt/start/{pet.id}")  # creates a draft
    resp = client.get("/adopt/applications")
    assert b"haven't applied" in resp.data  # draft not shown
