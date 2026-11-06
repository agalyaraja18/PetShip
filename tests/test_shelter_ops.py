"""Task 17 tests: shelter appointments, reviews, and follow-ups."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from petship.extensions import db
from petship.models.application import Application, ApplicationStage
from petship.models.application import AdoptionAgreement, ReturnStatus
from petship.models.appointment import Appointment, AppointmentKind, AppointmentStatus
from petship.models.pet import Pet, PetStatus
from petship.models.review import FollowUp, FollowUpStatus, Review, ReviewTarget
from petship.models.shelter import Shelter
from petship.models.user import User, UserRole
from petship.seed import seed_data


def login_shelter(client):
    seed_data()
    client.post("/auth/login", data={"role": "shelter", "email": "kavya@demo.petship", "password": "password123"})


def happy_paws():
    return db.session.scalar(db.select(Shelter).filter_by(slug="happy-paws"))


# ---- Appointments ----
def test_appointments_requires_shelter(client, app):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    assert client.get("/shelter/appointments").status_code == 403


def test_create_and_list_appointment(client, app):
    login_shelter(client)
    client.post(
        "/shelter/appointments/new",
        data={"kind": "meet_greet", "scheduled_for": "2026-11-02T11:00",
              "location": "At shelter", "note": "Coordinator: Kavya"},
    )
    appt = db.session.scalar(db.select(Appointment))
    assert appt is not None
    assert appt.shelter_id == happy_paws().id
    resp = client.get("/shelter/appointments")
    assert b"Meet &amp; greet" in resp.data or b"Meet & greet" in resp.data


def test_checkin_appointment(client, app):
    login_shelter(client)
    shelter = happy_paws()
    from petship.models.appointment import AppointmentKind
    appt = Appointment(kind=AppointmentKind.MEET_GREET, shelter_id=shelter.id,
                       scheduled_for=datetime.now(timezone.utc),
                       status=AppointmentStatus.CONFIRMED)
    db.session.add(appt)
    db.session.commit()
    client.post(f"/shelter/appointments/{appt.id}/checkin")
    db.session.refresh(appt)
    assert appt.status is AppointmentStatus.CHECKED_IN


def test_shelter_confirms_reschedule_request(client, app):
    login_shelter(client)
    application = _completed_application()
    appt = Appointment(
        application_id=application.id,
        kind=AppointmentKind.HOME_VISIT,
        shelter_id=happy_paws().id,
        user_id=application.applicant_id,
        pet_id=application.pet_id,
        scheduled_for=datetime.now(timezone.utc),
        status=AppointmentStatus.PENDING,
    )
    db.session.add(appt)
    db.session.commit()
    client.post(f"/shelter/appointments/{appt.id}/confirm")
    db.session.refresh(appt)
    assert appt.status is AppointmentStatus.CONFIRMED


# ---- Reviews ----
def test_reviews_page_and_reply(client, app):
    login_shelter(client)
    shelter = happy_paws()
    author = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    review = Review(author_id=author.id, target_type=ReviewTarget.SHELTER,
                    target_id=shelter.id, rating=5, body="Caring staff!")
    db.session.add(review)
    db.session.commit()

    resp = client.get("/shelter/reviews")
    assert b"Caring staff!" in resp.data

    client.post(f"/shelter/reviews/{review.id}/reply", data={"reply": "Thank you!"})
    db.session.refresh(review)
    assert review.reply == "Thank you!"


def test_review_avg_computed(client, app):
    login_shelter(client)
    shelter = happy_paws()
    author = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    db.session.add_all([
        Review(author_id=author.id, target_type=ReviewTarget.SHELTER, target_id=shelter.id, rating=5),
        Review(author_id=author.id, target_type=ReviewTarget.SHELTER, target_id=shelter.id, rating=3),
    ])
    db.session.commit()
    resp = client.get("/shelter/reviews")
    assert b"4.0" in resp.data  # (5+3)/2


def test_shelter_dashboard_links_to_reviews_and_platform_feedback(client, app):
    login_shelter(client)

    response = client.get("/shelter/dashboard")

    assert response.status_code == 200
    page = response.data.decode()
    reviews_link = page.index('href="/shelter/reviews"')
    profile_link = page.index('href="/shelter/profile"')
    settings_link = page.index('href="/shelter/settings"')
    feedback_link = page.index('href="/feedback"')
    assert reviews_link < profile_link < settings_link < feedback_link


# ---- Follow-ups ----
def _completed_application():
    """Create and complete an adoption so follow-ups are generated."""
    adopter = User(email="fu@example.com", first_name="Meera", role=UserRole.ADOPTER,
                   is_verified=True)
    adopter.set_password("password123")
    adopter.is_active = True
    db.session.add(adopter)
    db.session.commit()
    pet = db.session.scalar(db.select(Pet).filter_by(name="Bruno"))
    a = Application(reference="PS-60001", applicant_id=adopter.id, pet_id=pet.id,
                    stage=ApplicationStage.AGREEMENT, answers={})
    db.session.add(a)
    db.session.commit()
    db.session.add(AdoptionAgreement(
        application_id=a.id,
        file_name="agreement.pdf",
        original_filename="agreement.pdf",
        shelter_signature="Kavya",
        adopter_signature="Meera",
    ))
    db.session.commit()
    return a


def test_complete_adoption_creates_followups(client, app):
    login_shelter(client)
    a = _completed_application()
    client.post(f"/shelter/requests/{a.id}/action", data={"action": "complete"})
    fus = db.session.scalars(
        db.select(FollowUp).filter_by(application_id=a.id)
    ).all()
    assert {f.milestone for f in fus} == {"7 days", "15 days", "30 days"}
    assert all(
        (fu.due_on - a.adopted_at).days == int(fu.milestone.split()[0])
        for fu in fus
    )


def test_followups_page_shows_due(client, app):
    login_shelter(client)
    a = _completed_application()
    client.post(f"/shelter/requests/{a.id}/action", data={"action": "complete"})
    resp = client.get("/shelter/followups")
    assert resp.status_code == 200
    assert b"Post-adoption follow-ups" in resp.data
    assert b"7 days" in resp.data
    assert client.get("/shelter/returns").status_code == 200


def test_shelter_schedules_checkin_time(client, app):
    login_shelter(client)
    application = _completed_application()
    client.post(
        f"/shelter/requests/{application.id}/action",
        data={"action": "complete"},
    )
    fu = db.session.scalar(
        db.select(FollowUp).filter_by(application_id=application.id, milestone="7 days")
    )
    scheduled = fu.due_on.strftime("%Y-%m-%dT%H:%M")
    client.post(
        f"/shelter/followups/{fu.id}/schedule",
        data={"scheduled_for": scheduled},
    )
    db.session.refresh(fu)
    assert fu.due_on.strftime("%Y-%m-%dT%H:%M") == scheduled


def test_adopter_can_respond_to_due_checkin(client, app):
    login_shelter(client)
    application = _completed_application()
    client.post(
        f"/shelter/requests/{application.id}/action",
        data={"action": "complete"},
    )
    fu = db.session.scalar(
        db.select(FollowUp).filter_by(application_id=application.id, milestone="7 days")
    )
    fu.due_on = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.session.commit()
    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={"role": "adopter", "email": "fu@example.com", "password": "password123"},
    )

    resp = client.get("/me/followups")
    assert resp.status_code == 200
    assert b"7 days" in resp.data
    client.post(
        f"/me/followups/{fu.id}/respond",
        data={"outcome": "needs_support", "response": "Not settling in yet."},
    )
    db.session.refresh(fu)
    assert fu.status == FollowUpStatus.NEEDS_SUPPORT
    assert fu.response == "Not settling in yet."


def test_pet_is_added_to_my_pets_after_all_followups_are_completed(client, app):
    login_shelter(client)
    application = _completed_application()
    client.post(
        f"/shelter/requests/{application.id}/action",
        data={"action": "complete"},
    )
    followups = db.session.scalars(
        db.select(FollowUp).filter_by(application_id=application.id)
    ).all()
    assert application.owned_pet is None

    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={"role": "adopter", "email": "fu@example.com", "password": "password123"},
    )
    with client.session_transaction() as session:
        session.pop("_flashes", None)
    assert b"Bruno" not in client.get("/me/pets").data

    for followup in followups:
        followup.due_on = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.session.commit()
    for followup in followups:
        client.post(
            f"/me/followups/{followup.id}/respond",
            data={"outcome": "done", "response": "Settling in well."},
        )

    db.session.refresh(application)
    owned_pet = application.owned_pet
    assert owned_pet is not None
    assert owned_pet.owner_id == application.applicant_id
    assert b"Bruno" in client.get("/me/pets").data
    assert client.get(f"/me/pets/{owned_pet.id}").status_code == 200


def test_adopter_return_is_limited_to_first_30_days(client, app):
    login_shelter(client)
    application = _completed_application()
    client.post(
        f"/shelter/requests/{application.id}/action",
        data={"action": "complete"},
    )
    pet_name = application.pet.name
    application.adopted_at = datetime.now(timezone.utc) - timedelta(days=31)
    db.session.commit()
    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={"role": "adopter", "email": "fu@example.com", "password": "password123"},
    )
    client.post(
        f"/me/applications/{application.id}/return",
        data={"reason": "Not the right fit."},
    )
    db.session.refresh(application)
    assert application.returned_at is None

    application.adopted_at = datetime.now(timezone.utc) - timedelta(days=29)
    db.session.commit()
    client.post(
        f"/me/applications/{application.id}/return",
        data={"reason": "Not the right fit."},
    )
    db.session.refresh(application)
    assert application.return_status == ReturnStatus.SUBMITTED.value
    assert application.returned_at is None
    assert client.get("/me/pets").status_code == 200
    assert pet_name.encode() not in client.get("/me/pets").data
    dashboard = client.get("/me/dashboard")
    assert b"Return application status" in dashboard.data
    assert b"Return submitted" in dashboard.data


def test_shelter_can_record_return_after_30_day_support_response(client, app):
    login_shelter(client)
    application = _completed_application()
    client.post(
        f"/shelter/requests/{application.id}/action",
        data={"action": "complete"},
    )
    fu = db.session.scalar(
        db.select(FollowUp).filter_by(application_id=application.id, milestone="30 days")
    )
    application.adopted_at = datetime.now(timezone.utc) - timedelta(days=31)
    fu.status = FollowUpStatus.NEEDS_SUPPORT
    fu.due_on = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.session.commit()

    client.post(
        f"/shelter/followups/{fu.id}/return",
        data={"reason": "Pet needs a different home."},
    )
    db.session.refresh(application)
    assert application.return_status == ReturnStatus.SUBMITTED.value
    assert application.returned_at is None
    assert application.return_reason == "Pet needs a different home."
    resp = client.get("/shelter/followups")
    assert b"Open Return Requests" in resp.data
    resp = client.get("/shelter/returns")
    assert b"Return requests and collection visits" in resp.data
    assert b"Begin shelter review" in resp.data


def test_shelter_return_workflow_requires_scheduled_home_collection(client, app):
    login_shelter(client)
    application = _completed_application()
    client.post(
        f"/shelter/requests/{application.id}/action",
        data={"action": "complete"},
    )
    pet_name = application.pet.name
    application.adopted_at = datetime.now(timezone.utc) - timedelta(days=31)
    application.submit_return("The pet needs a different home.", datetime.now(timezone.utc))
    db.session.commit()

    action_url = f"/shelter/applications/{application.id}/return/action"
    client.post(action_url, data={"action": "review"})
    db.session.refresh(application)
    assert application.return_status == ReturnStatus.SHELTER_REVIEW.value

    client.post(action_url, data={"action": "confirm"})
    db.session.refresh(application)
    assert application.return_status == ReturnStatus.SHELTER_CONFIRMED.value

    future_visit = datetime.now(timezone.utc) + timedelta(days=1)
    client.post(
        action_url,
        data={
            "action": "schedule",
            "scheduled_for": future_visit.strftime("%Y-%m-%dT%H:%M"),
        },
    )
    db.session.refresh(application)
    assert application.return_status == ReturnStatus.RETURN_VISIT.value
    assert application.return_visit_at is not None
    assert application.returned_at is None

    client.post(action_url, data={"action": "complete"})
    db.session.refresh(application)
    assert application.returned_at is None

    application.return_visit_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.session.commit()
    client.post(action_url, data={"action": "complete"})
    db.session.refresh(application)
    db.session.refresh(application.pet)
    assert application.return_status == ReturnStatus.RETURNED_SHELTER.value
    assert application.returned_at is not None
    assert application.pet.status == PetStatus.AVAILABLE
    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={"role": "adopter", "email": "fu@example.com", "password": "password123"},
    )
    with client.session_transaction() as session:
        session.pop("_flashes", None)
    assert pet_name.encode() not in client.get("/me/pets").data
    assert b"Return completed" in client.get(
        "/me/adoptions?tab=returns"
    ).data


def test_shelter_can_complete_legacy_return_visit_after_local_time(client, app):
    from zoneinfo import ZoneInfo

    login_shelter(client)
    application = _completed_application()
    application.return_status = ReturnStatus.RETURN_VISIT.value
    application.return_visit_at = (
        datetime.now(timezone.utc)
        .astimezone(ZoneInfo("Asia/Kolkata"))
        .replace(tzinfo=None)
        - timedelta(minutes=10)
    )
    application.return_visit_timezone = None
    db.session.commit()

    response = client.post(
        f"/shelter/applications/{application.id}/return/action",
        data={"action": "complete", "browser_timezone": "Asia/Kolkata"},
        follow_redirects=True,
    )

    db.session.refresh(application)
    assert response.status_code == 200
    assert application.return_status == ReturnStatus.RETURNED_SHELTER.value
    assert application.returned_at is not None
    assert b"is now marked as returned to the shelter" in response.data


def test_shelter_return_visit_uses_browser_timezone(client, app):
    from zoneinfo import ZoneInfo

    login_shelter(client)
    application = _completed_application()
    application.return_status = ReturnStatus.SHELTER_CONFIRMED.value
    db.session.commit()

    local_timezone = ZoneInfo("Asia/Kolkata")
    local_visit = (
        datetime.now(timezone.utc)
        .astimezone(local_timezone)
        + timedelta(hours=1)
    ).replace(second=0, microsecond=0)
    response = client.post(
        f"/shelter/applications/{application.id}/return/action",
        data={
            "action": "schedule",
            "scheduled_for": local_visit.strftime("%Y-%m-%dT%H:%M"),
            "browser_timezone": local_timezone.key,
        },
        follow_redirects=True,
    )

    db.session.refresh(application)
    stored_visit = application.return_visit_at.replace(tzinfo=timezone.utc)
    expected_visit = local_visit.astimezone(timezone.utc)
    assert response.status_code == 200
    assert application.return_visit_timezone == local_timezone.key
    assert abs((stored_visit - expected_visit).total_seconds()) < 60


def test_shelter_returns_page_filters_by_workflow_status(client, app):
    login_shelter(client)
    application = _completed_application()
    client.post(
        f"/shelter/requests/{application.id}/action",
        data={"action": "complete"},
    )
    application.submit_return("Needs a different home.", datetime.now(timezone.utc))
    db.session.commit()

    submitted = client.get("/shelter/returns?status=submitted")
    assert b"Return submitted" in submitted.data
    assert b"Begin shelter review" in submitted.data
    assert b">New <span class=\"text-muted\">(1)</span></a>" in submitted.data
    assert b">Reviewed <span class=\"text-muted\">(0)</span></a>" in submitted.data
    assert b">Confirmed <span class=\"text-muted\">(0)</span></a>" in submitted.data
    assert b">Return visit <span class=\"text-muted\">(0)</span></a>" in submitted.data
    assert b">Returned <span class=\"text-muted\">(0)</span></a>" in submitted.data
    assert b"New <span class=\"text-muted\">(1)</span>" in submitted.data
    assert b"Reviewed <span class=\"text-muted\">(0)</span>" in submitted.data
    assert b"Returned <span class=\"text-muted\">(0)</span>" in submitted.data
    assert b"Return submitted</li>" not in submitted.data
    assert b"<ol" not in submitted.data
    assert b"aria-current=\"page\"" in submitted.data

    client.post(
        f"/shelter/applications/{application.id}/return/action",
        data={"action": "review"},
    )
    review = client.get("/shelter/returns?status=shelter_review")
    assert b"Return review" in review.data
    assert b"Confirm return" in review.data
    assert b"Begin shelter review" not in review.data
