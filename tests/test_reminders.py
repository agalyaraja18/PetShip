"""Task 24 tests: reminders, notifications, and the scheduler logic."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from petship.extensions import db
from petship.models.application import Application, ApplicationStage, ReturnStatus
from petship.models.health import OwnedPet
from petship.models.appointment import Appointment, AppointmentKind, AppointmentStatus
from petship.models.pet import Pet
from petship.models.review import FollowUp, FollowUpStatus
from petship.models.reminder import Notification, Recurrence, Reminder
from petship.models.user import User, UserRole
from petship.seed import seed_data
from petship.services.scheduler import run_due_reminders


def login_agalya(client):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})


def agalya():
    return db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))


# ---- Recurrence model ----
def test_once_reminder_completes(app):
    r = Reminder(owner_id=1, title="X", recurrence=Recurrence.ONCE, next_due=date.today())
    r.advance()
    assert r.done is True


def test_daily_reminder_rolls_forward(app):
    today = date.today()
    r = Reminder(owner_id=1, title="X", recurrence=Recurrence.DAILY, next_due=today)
    r.advance()
    assert r.done is False
    assert r.next_due == today + timedelta(days=1)


# ---- CRUD ----
def test_reminder_centre_renders(client, app):
    login_agalya(client)
    resp = client.get("/lifestyle/reminders")
    assert resp.status_code == 200
    assert b"Smart Reminder Centre" in resp.data
    assert b"Today's progress" not in resp.data
    assert b"Smart tip" not in resp.data
    for label in (b"All", b"Today", b"Tomorrow", b"This Week", b"This Month"):
        assert label in resp.data
    for category in (
        b"Vet appointments",
        b"Today&#39;s tasks",
        b"Adoption applications",
        b"Return pets",
    ):
        assert category in resp.data
    assert b"Follow ups" not in resp.data
    assert b'href="/lifestyle/reminders?period=all"' in resp.data
    assert b'aria-current="page"' in resp.data
    assert b"Create a task" in resp.data
    assert b"Save task" not in resp.data


def test_adopter_reminder_centre_handles_active_adoption(client, app):
    login_agalya(client)
    user = agalya()
    pet = db.session.scalar(db.select(Pet).limit(1))
    db.session.add(Application(
        reference="PS-REMINDER-TEST",
        applicant_id=user.id,
        pet_id=pet.id,
        stage=ApplicationStage.REVIEW,
    ))
    db.session.commit()
    response = client.get("/lifestyle/reminders")
    assert response.status_code == 200
    assert b"Adoption applications" in response.data


def test_adoptions_page_has_adopt_a_pet_button(client, app):
    login_agalya(client)
    response = client.get("/me/adoptions")
    assert response.status_code == 200
    assert b"Adopt a pet" in response.data


def test_shelter_reminder_centre_shows_shelter_categories(client, app):
    from petship.models.shelter import Shelter

    seed_data()
    shelter_user = db.session.scalar(
        db.select(User).filter_by(email="kavya@demo.petship")
    )
    shelter = db.session.scalar(
        db.select(Shelter).filter_by(owner_id=shelter_user.id)
    )
    pet = db.session.scalar(
        db.select(Pet).filter(Pet.shelter_id == shelter.id)
    )
    return_visit = Application(
        reference="PS-RETURN-REMINDER",
        applicant_id=agalya().id,
        pet_id=pet.id,
        stage=ApplicationStage.COMPLETE,
        return_status=ReturnStatus.RETURN_VISIT.value,
        return_visit_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.session.add(return_visit)
    db.session.commit()
    client.post("/auth/login", data={"role": "shelter", "email": "kavya@demo.petship", "password": "password123"})
    resp = client.get("/lifestyle/reminders")
    assert resp.status_code == 200
    assert b"Home visits" in resp.data
    assert b"Return visit" in resp.data
    assert f"Return visit: {pet.name}".encode() in resp.data
    assert b"reminder-categories--shelter" in resp.data
    assert b'class="grid reminder-categories--shelter"' in resp.data
    assert b"Adoption applications" not in resp.data
    assert b"Return requests" not in resp.data
    assert b"Today&#39;s tasks" in resp.data
    assert b"Vet appointments" not in resp.data
    assert b"Create a task" in resp.data
    assert b"Save task" not in resp.data


def test_task_creation_page_works_for_adopter_and_shelter(client, app):
    login_agalya(client)
    response = client.get("/lifestyle/reminders/new")
    assert response.status_code == 200
    assert b"name=\"title\"" in response.data

    user = agalya()
    due = (date.today() + timedelta(days=1)).isoformat()
    client.post(
        "/lifestyle/reminders/add",
        data={
            "title": "Adopter task",
            "recurrence": "once",
            "next_due": due,
            "at_time": "09:00",
        },
    )
    assert db.session.scalar(
        db.select(Reminder).filter_by(owner_id=user.id, title="Adopter task")
    ) is not None

    client.get("/auth/logout")
    seed_data()
    shelter_user = db.session.scalar(
        db.select(User).filter_by(email="kavya@demo.petship")
    )
    client.post(
        "/auth/login",
        data={"role": "shelter", "email": "kavya@demo.petship", "password": "password123"},
    )
    assert client.get("/lifestyle/reminders/new").status_code == 200
    client.post(
        "/lifestyle/reminders/add",
        data={
            "title": "Shelter task",
            "recurrence": "once",
            "next_due": due,
            "at_time": "10:00",
        },
    )
    assert db.session.scalar(
        db.select(Reminder).filter_by(owner_id=shelter_user.id, title="Shelter task")
    ) is not None


def test_adopter_notifications_are_grouped_without_community_filter(client, app):
    login_agalya(client)
    user = agalya()
    db.session.add_all([
        Notification(user_id=user.id, title="Adoption notice", category="adoption"),
        Notification(user_id=user.id, title="Care notice", category="health"),
    ])
    db.session.commit()

    response = client.get("/lifestyle/notifications")
    assert b"Adoption notice" in response.data
    assert b"Care notice" in response.data
    assert b'href="/lifestyle/notifications?category=community"' not in response.data
    assert b"Community" not in response.data
    assert b"<h2" in response.data

    filtered = client.get("/lifestyle/notifications?category=health")
    assert b"Care notice" in filtered.data
    assert b"Adoption notice" not in filtered.data


def test_reminder_date_filters_select_one_period(client, app):
    login_agalya(client)
    user = agalya()
    tomorrow = date.today() + timedelta(days=1)
    later_this_week = date.today() + timedelta(days=3)
    db.session.add_all([
        Reminder(
            owner_id=user.id,
            title="Tomorrow task only",
            recurrence=Recurrence.ONCE,
            next_due=tomorrow,
        ),
        Reminder(
            owner_id=user.id,
            title="Later this week only",
            recurrence=Recurrence.ONCE,
            next_due=later_this_week,
        ),
    ])
    db.session.commit()

    tomorrow_page = client.get("/lifestyle/reminders?period=tomorrow")
    assert b"Tomorrow task only" in tomorrow_page.data
    assert b"Later this week only" not in tomorrow_page.data
    assert b"aria-current=\"page\"" in tomorrow_page.data

    week_page = client.get("/lifestyle/reminders?period=this-week")
    assert b"Later this week only" in week_page.data
    assert b"Tomorrow task only" not in week_page.data


def test_all_reminder_filter_is_default_and_shows_all_upcoming_periods(client, app):
    login_agalya(client)
    user = agalya()
    tomorrow = date.today() + timedelta(days=1)
    later_this_week = date.today() + timedelta(days=3)
    db.session.add_all([
        Reminder(
            owner_id=user.id,
            title="All filter tomorrow task",
            recurrence=Recurrence.ONCE,
            next_due=tomorrow,
        ),
        Reminder(
            owner_id=user.id,
            title="All filter week task",
            recurrence=Recurrence.ONCE,
            next_due=later_this_week,
        ),
    ])
    db.session.commit()

    response = client.get("/lifestyle/reminders")
    assert b"All filter tomorrow task" in response.data
    assert b"All filter week task" in response.data
    assert b'href="/lifestyle/reminders?period=all"' in response.data
    assert b'aria-current="page"' in response.data


def test_day_of_appointment_notification_is_created_once(client, app):
    seed_data()
    user = agalya()
    scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=30)
    appointment = Appointment(
        kind=AppointmentKind.VET_VISIT,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=scheduled_for,
        user_id=user.id,
    )
    db.session.add(appointment)
    db.session.commit()

    run_due_reminders(app)
    notification = db.session.scalar(
        db.select(Notification).filter_by(
            user_id=user.id,
            title="Today's appointment: Vet visit",
            category="appointments",
        )
    )
    assert notification is not None
    before = db.session.scalar(
        db.select(db.func.count()).select_from(Notification).filter_by(
            user_id=user.id,
            title="Today's appointment: Vet visit",
            category="appointments",
        )
    )
    run_due_reminders(app)
    after = db.session.scalar(
        db.select(db.func.count()).select_from(Notification).filter_by(
            user_id=user.id,
            title="Today's appointment: Vet visit",
            category="appointments",
        )
    )
    assert before == after == 1


def test_day_of_followup_and_return_visit_notifications(client, app):
    seed_data()
    user = agalya()
    pet = db.session.scalar(db.select(Pet).limit(1))
    now = datetime.now(timezone.utc)
    application = Application(
        reference="PS-DAY001",
        applicant_id=user.id,
        pet_id=pet.id,
        stage=ApplicationStage.COMPLETE,
        adopted_at=now - timedelta(days=7),
        return_status=ReturnStatus.RETURN_VISIT.value,
        return_requested_at=now - timedelta(days=1),
        return_visit_at=now + timedelta(minutes=45),
    )
    db.session.add(application)
    db.session.flush()
    db.session.add(FollowUp(
        application_id=application.id,
        milestone="7 days",
        due_on=now + timedelta(minutes=20),
        status=FollowUpStatus.DUE,
    ))
    db.session.commit()

    run_due_reminders(app)

    titles = db.session.scalars(
        db.select(Notification.title).filter_by(user_id=user.id)
    ).all()
    assert f"Today's adoption follow-up: {pet.name} · 7 days" in titles
    assert f"Today's return visit: {pet.name}" in titles


def test_add_reminder(client, app):
    login_agalya(client)
    client.post("/lifestyle/reminders/add",
                data={"title": "Flea drops", "recurrence": "monthly", "at_time": "09:00"})
    r = db.session.scalar(db.select(Reminder).filter_by(title="Flea drops"))
    assert r is not None
    assert r.recurrence is Recurrence.MONTHLY
    assert r.next_due == date.today()


def test_add_reminder_saves_scheduled_date_and_time(client, app):
    login_agalya(client)
    scheduled_date = date.today() + timedelta(days=3)
    client.post(
        "/lifestyle/reminders/add",
        data={
            "title": "Grooming",
            "recurrence": "once",
            "next_due": scheduled_date.isoformat(),
            "at_time": "14:30",
        },
    )
    reminder = db.session.scalar(
        db.select(Reminder).filter_by(title="Grooming")
    )
    assert reminder.next_due == scheduled_date
    assert reminder.at_time == time(14, 30)


def test_toggle_once_reminder(client, app):
    login_agalya(client)
    client.post("/lifestyle/reminders/add",
                data={"title": "One-off", "recurrence": "once"})
    r = db.session.scalar(db.select(Reminder).filter_by(title="One-off"))
    client.post(f"/lifestyle/reminders/{r.id}/toggle")
    db.session.refresh(r)
    assert r.done is True


def test_toggle_recurring_advances(client, app):
    login_agalya(client)
    client.post("/lifestyle/reminders/add",
                data={"title": "Daily feed", "recurrence": "daily"})
    r = db.session.scalar(db.select(Reminder).filter_by(title="Daily feed"))
    original_due = r.next_due
    client.post(f"/lifestyle/reminders/{r.id}/toggle")
    db.session.refresh(r)
    assert r.done is False
    assert r.next_due == original_due + timedelta(days=1)


def test_cannot_toggle_others_reminder(client, app):
    login_agalya(client)
    other = User(email="z@example.com", first_name="Z")
    other.set_password("password123"); other.is_active = True
    db.session.add(other); db.session.commit()
    r = Reminder(owner_id=other.id, title="Theirs", recurrence=Recurrence.ONCE,
                 next_due=date.today())
    db.session.add(r); db.session.commit()
    assert client.post(f"/lifestyle/reminders/{r.id}/toggle").status_code == 404


# ---- Scheduler logic ----
def test_run_due_reminders_creates_notifications(client, app):
    seed_data()
    user = agalya()
    r = Reminder(owner_id=user.id, title="Deworming tablet",
                 recurrence=Recurrence.MONTHLY, next_due=date.today())
    db.session.add(r)
    db.session.commit()

    count = run_due_reminders(app)
    assert count >= 1
    # Find the notification generated for this reminder specifically (the seed
    # also creates a few starter notifications for the demo adopter).
    notif = db.session.scalar(
        db.select(Notification).filter(
            Notification.user_id == user.id,
            Notification.title.like("%Deworming tablet%"),
        )
    )
    assert notif is not None


def test_run_due_reminders_dedupes_same_day(client, app):
    seed_data()
    user = agalya()
    r = Reminder(owner_id=user.id, title="Daily", recurrence=Recurrence.DAILY,
                 next_due=date.today())
    db.session.add(r)
    db.session.commit()
    run_due_reminders(app)
    first = db.session.scalar(
        db.select(db.func.count()).select_from(Notification).filter_by(user_id=user.id)
    )
    # Running again the same day shouldn't duplicate.
    run_due_reminders(app)
    second = db.session.scalar(
        db.select(db.func.count()).select_from(Notification).filter_by(user_id=user.id)
    )
    assert first == second


def test_future_reminders_not_notified(client, app):
    seed_data()
    user = agalya()
    r = Reminder(owner_id=user.id, title="Future", recurrence=Recurrence.ONCE,
                 next_due=date.today() + timedelta(days=5))
    db.session.add(r)
    db.session.commit()
    count = run_due_reminders(app)
    assert count == 0


def test_reminder_expires_only_after_scheduled_time(client, app):
    seed_data()
    user = agalya()
    scheduled_for = datetime.now().astimezone().replace(
        second=0, microsecond=0
    ) + timedelta(hours=1)
    scheduled_for = scheduled_for.replace(second=0, microsecond=0)
    reminder = Reminder(
        owner_id=user.id,
        title="Evening medicine",
        recurrence=Recurrence.ONCE,
        next_due=scheduled_for.date(),
        at_time=scheduled_for.time().replace(tzinfo=None),
    )
    db.session.add(reminder)
    db.session.commit()

    before_due = scheduled_for - timedelta(minutes=1)
    run_due_reminders(app, before_due)
    db.session.refresh(reminder)
    assert reminder.done is False

    after_due = scheduled_for + timedelta(minutes=1)
    run_due_reminders(app, after_due)
    db.session.refresh(reminder)
    assert reminder.done is True
    notification = db.session.scalar(
        db.select(Notification).filter_by(user_id=user.id, title="Reminder: Evening medicine")
    )
    assert notification is not None
    assert "has passed" in notification.body


def test_expired_appointment_notifies_and_leaves_upcoming_list(client, app):
    seed_data()
    user = agalya()
    scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
    appointment = Appointment(
        kind=AppointmentKind.VET_VISIT,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=scheduled_for,
        user_id=user.id,
    )
    db.session.add(appointment)
    db.session.commit()

    assert run_due_reminders(app) == 1
    db.session.refresh(appointment)
    assert appointment.status is AppointmentStatus.COMPLETED
    notification = db.session.scalar(
        db.select(Notification).filter_by(
            user_id=user.id,
            title="Appointment completed: Vet visit",
        )
    )
    assert notification is not None
    run_due_reminders(app)
    notifications = db.session.scalars(
        db.select(Notification).filter_by(
            user_id=user.id,
            title="Appointment completed: Vet visit",
        )
    ).all()
    assert len(notifications) == 1


def test_past_welcome_home_auto_completes_adoption(client, app):
    login_agalya(client)
    user = agalya()
    pet = db.session.scalar(db.select(Pet).limit(1))
    welcome_home = datetime.now(timezone.utc) - timedelta(minutes=5)
    application = Application(
        reference="PS-WELCOME-TEST",
        applicant_id=user.id,
        pet_id=pet.id,
        stage=ApplicationStage.AGREEMENT,
    )
    db.session.add(application)
    db.session.flush()
    pickup = Appointment(
        kind=AppointmentKind.PICKUP,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=welcome_home,
        application_id=application.id,
        shelter_id=pet.shelter_id,
        user_id=user.id,
        pet_id=pet.id,
    )
    db.session.add(pickup)
    db.session.commit()

    run_due_reminders(app)
    db.session.refresh(application)

    assert application.stage is ApplicationStage.COMPLETE
    assert application.adopted_at is not None
    assert application.owned_pet is not None
    assert application.owned_pet.owner_id == user.id
    assert application.pet.status.value == "adopted"
    assert b"My Pets" in client.get("/me/pets").data
    assert application.pet.name.encode() in client.get("/me/adoptions").data


def test_expired_reminder_is_removed_from_smart_reminders(client, app):
    login_agalya(client)
    user = agalya()
    elapsed_at = datetime.now().astimezone() - timedelta(minutes=1)
    reminder = Reminder(
        owner_id=user.id,
        title="Expired care task",
        recurrence=Recurrence.ONCE,
        next_due=elapsed_at.date(),
        at_time=elapsed_at.time().replace(tzinfo=None),
    )
    db.session.add(reminder)
    db.session.commit()

    response = client.get("/lifestyle/reminders")

    assert response.status_code == 200
    assert b"Expired care task" not in response.data


def test_expired_return_visit_is_removed_from_smart_reminders(client, app):
    login_agalya(client)
    user = agalya()
    pet = db.session.scalar(db.select(Pet).limit(1))
    application = Application(
        reference="PS-RETURN-REMINDER",
        applicant_id=user.id,
        pet_id=pet.id,
        stage=ApplicationStage.COMPLETE,
        adopted_at=datetime.now(timezone.utc) - timedelta(days=10),
        return_status=ReturnStatus.RETURN_VISIT.value,
        return_visit_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db.session.add(application)
    db.session.commit()

    response = client.get("/lifestyle/reminders")

    assert response.status_code == 200
    assert b"Home collection" not in response.data


def test_expired_appointment_is_removed_from_smart_reminders(client, app):
    login_agalya(client)
    user = agalya()
    appointment = Appointment(
        kind=AppointmentKind.VET_VISIT,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=1),
        user_id=user.id,
        service="Expired appointment task",
    )
    db.session.add(appointment)
    db.session.commit()

    response = client.get("/lifestyle/reminders")

    assert response.status_code == 200
    assert b"Expired appointment task" not in response.data


def test_expired_home_visit_is_removed_from_shelter_reminders(client, app):
    seed_data()
    user = agalya()
    pet = db.session.scalar(db.select(Pet).limit(1))
    appointment = Appointment(
        kind=AppointmentKind.HOME_VISIT,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=1),
        shelter_id=pet.shelter_id,
        user_id=user.id,
        pet_id=pet.id,
        location="Expired home visit location",
    )
    db.session.add(appointment)
    db.session.commit()
    client.post(
        "/auth/login",
        data={
            "role": "shelter",
            "email": "kavya@demo.petship",
            "password": "password123",
        },
    )

    response = client.get("/lifestyle/reminders")

    assert response.status_code == 200
    assert b"Expired home visit location" not in response.data


# ---- Notifications centre ----
def test_notifications_centre(client, app):
    login_agalya(client)
    user = agalya()
    Notification.push(user.id, "Vaccine due soon", "Mochi's rabies booster.", "health")
    db.session.commit()
    resp = client.get("/lifestyle/notifications")
    assert resp.status_code == 200
    assert b"Vaccine due soon" in resp.data


def test_mark_all_read(client, app):
    login_agalya(client)
    user = agalya()
    Notification.push(user.id, "One", category="health")
    Notification.push(user.id, "Two", category="health")
    db.session.commit()
    client.post("/lifestyle/notifications/read-all")
    unread = db.session.scalar(
        db.select(db.func.count()).select_from(Notification)
        .filter_by(user_id=user.id, read=False)
    )
    assert unread == 0
