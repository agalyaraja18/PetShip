"""Task 20 tests: vet dashboard, appointment management, patient details."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from petship.extensions import db
from petship.models.appointment import Appointment, AppointmentKind
from petship.models.health import (
    HealthPlan,
    MedicalRecord,
    OwnedPet,
    RecordType,
    Vaccination,
    VetPatient,
)
from petship.models.reminder import Notification, Recurrence, Reminder
from petship.models.user import User, UserRole
from petship.seed import seed_data


def _book_with_ananya(client, when=None, slot="11:00", pet="Mochi"):
    """As an adopter, book an appointment with Dr. Ananya Rao."""
    when = when or (date.today()).isoformat()
    u = db.session.scalar(db.select(User).filter_by(email="booker@example.com"))
    if u is None:
        u = User(email="booker@example.com", first_name="Booker", role=UserRole.ADOPTER,
                 is_verified=True)
        u.set_password("password123")
        u.is_active = True
        db.session.add(u)
        db.session.commit()
    client.post("/auth/login", data={"role": "adopter", "email": "booker@example.com", "password": "password123"})
    client.post("/book/ananya-rao",
                data={"pet_name": pet, "service": "general", "date": when, "slot": slot})
    client.get("/auth/logout")


def login_vet(client):
    client.post("/auth/login", data={"role": "vet", "email": "ananya@demo.petship", "password": "password123"})


def test_dashboard_requires_vet(client, app):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    assert client.get("/vet/dashboard").status_code == 403


def test_vet_role_redirects_to_dashboard(client, app):
    seed_data()
    resp = client.post("/auth/login",
                       data={"role": "vet", "email": "ananya@demo.petship", "password": "password123"})
    resp = client.get("/auth/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert "/vet/dashboard" in resp.headers["Location"]


def test_vet_settings_shows_user_id_and_account_deletion(client, app):
    seed_data()
    user = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    user.public_id = "VET-00000001"
    db.session.commit()
    login_vet(client)

    response = client.get("/vet/settings")
    assert response.status_code == 200
    assert b"User ID" in response.data
    assert b"VET-00000001" in response.data
    assert b"Delete account" in response.data
    assert b'action="/profile/settings/delete"' in response.data


def test_vet_settings_saves_notification_preferences(client, app):
    seed_data()
    login_vet(client)
    settings_page = client.get("/vet/settings")
    assert b"Notifications" in settings_page.data
    response = client.post(
        "/vet/settings",
        data={"section": "notifications", "health_reminders": "on"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    user = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    assert user.prefs["health_reminders"] is True
    assert user.prefs["vet_appointments"] is False


def test_vet_notifications_are_grouped_and_markable_read(client, app):
    seed_data()
    user = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    db.session.add_all([
        Notification(user_id=user.id, category="health", title="Health update"),
        Notification(user_id=user.id, category="appointments", title="Appointment update"),
    ])
    db.session.commit()
    login_vet(client)

    all_notifications = client.get("/vet/notifications")
    assert b"Health" in all_notifications.data
    assert b"Appointment update" in all_notifications.data
    health_only = client.get("/vet/notifications?category=health")
    assert b"Health update" in health_only.data
    assert b"Appointment update" not in health_only.data

    client.post("/vet/notifications/read-all")
    assert db.session.scalar(
        db.select(Notification).filter_by(user_id=user.id, read=False)
    ) is None


def test_vet_profile_has_view_and_edit_states(client, app):
    seed_data()
    login_vet(client)

    profile = client.get("/vets/manage/profile")
    assert b"Edit profile" in profile.data
    assert b'name="display_name" value="Dr. Ananya Rao" disabled' in profile.data
    assert client.post(
        "/vets/manage/profile", data={"display_name": "Ignored"}
    ).status_code == 400
    edit = client.get("/vets/manage/profile?edit=1")
    assert b"Save profile" in edit.data
    assert b'name="display_name" value="Dr. Ananya Rao" disabled' not in edit.data
    saved = client.post(
        "/vets/manage/profile?edit=1",
        data={
            "display_name": "Dr. Ananya Updated",
            "clinic_name": "CareVet Clinic",
            "qualifications": "BVSc",
            "city": "Chennai",
        },
        follow_redirects=True,
    )
    assert b"Profile saved" in saved.data


def test_vet_can_delete_account(client, app):
    seed_data()
    user = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    user_id = user.id
    profile_id = user.vet_profile[0].id
    login_vet(client)

    response = client.post("/profile/settings/delete", follow_redirects=False)
    assert response.status_code == 302
    assert db.session.get(User, user_id) is None
    from petship.models.vet import VetProfile
    assert db.session.get(VetProfile, profile_id) is None


def test_dashboard_shows_todays_appointments(client, app):
    seed_data()
    _book_with_ananya(client, when=date.today().isoformat())
    login_vet(client)
    resp = client.get("/vet/dashboard")
    assert resp.status_code == 200
    assert b"Today's schedule" in resp.data
    assert b"Mochi" in resp.data


def test_appointments_grouped_view(client, app):
    seed_data()
    _book_with_ananya(client, when=(date.today() + timedelta(days=1)).isoformat())
    login_vet(client)
    resp = client.get("/vet/appointments?view=week")
    assert resp.status_code == 200
    assert b"Appointment management" in resp.data
    assert b"Mochi" in resp.data


def test_patients_list(client, app):
    seed_data()
    _book_with_ananya(client, pet="Bruno")
    login_vet(client)
    resp = client.get("/vet/patients")
    assert resp.status_code == 200
    assert b"Bruno" not in resp.data
    assert b"Appointment details" not in resp.data
    assert b"Mochi" in resp.data
    assert b"Open health record" in resp.data


def test_regular_owned_pet_is_listed_with_same_health_record_action(client, app):
    seed_data()
    pet = db.session.scalar(db.select(OwnedPet).filter_by(name="Mochi"))
    assert pet.primary_vet
    login_vet(client)

    patients = client.get("/vet/patients")
    assert f"Mochi · {pet.public_pet_id}".encode() in patients.data
    assert b"Open health record" in patients.data
    assert db.session.scalar(
        db.select(VetPatient).filter_by(vet_id=db.session.scalar(
            db.select(User.id).filter_by(email="ananya@demo.petship")
        ), pet_id=pet.id)
    ) is not None
    record_page = client.get(f"/vet/patients/{pet.id}/health-record")
    assert record_page.status_code == 200
    assert b"Primary vet:" not in record_page.data
    assert b"Schedule new plan" in record_page.data


def test_vet_links_adopted_pet_and_shares_records_and_health_plan(client, app):
    seed_data()
    owner = db.session.scalar(
        db.select(User).filter_by(email="agalya@demo.petship")
    )
    pet = db.session.scalar(
        db.select(OwnedPet).filter_by(owner_id=owner.id, name="Mochi")
    )
    public_pet_id = pet.public_pet_id
    login_vet(client)

    response = client.post(
        "/vet/patients/new",
        data={"pet_id": public_pet_id.lower()},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Mochi" in response.data
    assert public_pet_id.encode() in response.data
    assert b"Open health record" in response.data
    assert db.session.scalar(
        db.select(VetPatient).filter_by(vet_id=db.session.scalar(
            db.select(User.id).filter_by(email="ananya@demo.petship")
        ), pet_id=pet.id)
    ) is not None

    health_record_page = client.get(
        f"/vet/patients/{pet.id}/health-record"
    )
    assert health_record_page.status_code == 200
    assert b"Past health records" in health_record_page.data
    assert b"Schedule new plan" in health_record_page.data
    assert public_pet_id.encode() in health_record_page.data
    assert b"Deworming prescription" in health_record_page.data
    existing_vaccination = db.session.scalar(
        db.select(Vaccination).filter_by(pet_id=pet.id, name="Rabies").limit(1)
    )
    db.session.add(Vaccination(
        pet_id=pet.id,
        name=existing_vaccination.name,
        due_on=existing_vaccination.due_on,
        last_given=existing_vaccination.last_given,
        kind=existing_vaccination.kind,
    ))
    db.session.commit()
    health_record_page = client.get(f"/vet/patients/{pet.id}/health-record")
    assert health_record_page.data.count(b">Rabies<") == 1

    duplicate = MedicalRecord(
        pet_id=pet.id,
        record_type=RecordType.LAB,
        title="Complete blood panel",
        record_date=date.today() - timedelta(days=16),
        vet_name="Dr. Rao",
        diagnosis="Healthy. Recheck in 12 months.",
        summary="All values within normal range. Haemoglobin 12.1 g/dL.",
    )
    db.session.add(duplicate)
    db.session.commit()
    health_record_page = client.get(f"/vet/patients/{pet.id}/health-record")
    assert b"Complete blood panel" in health_record_page.data

    client.post(
        f"/vet/patients/{pet.id}/health-record/medical-record",
        data={
            "record_type": "prescription",
            "title": "New prescription",
            "record_date": date.today().isoformat(),
            "diagnosis": "Seasonal allergy",
            "summary": "Follow treatment plan.",
        },
    )
    client.post(
        f"/vet/patients/{pet.id}/health-record/plan",
        data={
            "title": "Allergy care plan",
            "instructions": "Give with food.",
            "prescribed_medicines": "One tablet daily",
            "next_visit_on": (date.today() + timedelta(days=14)).isoformat(),
        },
    )
    db.session.expire_all()
    plan = db.session.scalar(db.select(HealthPlan).filter_by(pet_id=pet.id))
    record = db.session.scalar(
        db.select(MedicalRecord).filter_by(pet_id=pet.id, title="New prescription")
    )
    assert plan is not None and record is not None
    assert plan.prescribed_medicines == "One tablet daily"
    assert db.session.scalar(
        db.select(Notification).filter_by(
            user_id=owner.id, title="New health plan for Mochi"
        )
    ) is not None
    client.post(
        "/vet/patients/new-plan",
        data={
            "pet_id": pet.public_pet_id,
            "consultation": "Monitor appetite and hydration.",
            "diagnosis": "Recovering well",
            "prescribed_medicines": "One tablet with dinner",
            "next_visit_on": (date.today() + timedelta(days=10)).isoformat(),
        },
    )
    assert len(db.session.scalars(
        db.select(HealthPlan).filter_by(
            pet_id=pet.id,
            title=f"Care plan · {date.today().strftime('%d %b %Y')}",
        )
    ).all()) == 1
    assert len(db.session.scalars(
        db.select(MedicalRecord).filter_by(
            pet_id=pet.id,
            title=f"Consultation · {date.today().strftime('%d %b %Y')}",
        )
    ).all()) == 1

    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={"role": "adopter", "email": owner.email, "password": "password123"},
    )
    owner_health = client.get(f"/health/pet/{pet.id}")
    assert b"Allergy care plan" in owner_health.data
    assert b"One tablet daily" in owner_health.data


def test_vet_plan_can_be_saved_without_next_visit(client, app):
    seed_data()
    owner = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    pet = db.session.scalar(db.select(OwnedPet).filter_by(owner_id=owner.id, name="Mochi"))
    db.session.add(VetPatient(
        vet_id=db.session.scalar(db.select(User.id).filter_by(email="ananya@demo.petship")),
        pet_id=pet.id,
    ))
    db.session.commit()
    login_vet(client)

    response = client.post(
        "/vet/patients/new-plan",
        data={
            "pet_id": pet.public_pet_id,
            "consultation": "No follow-up visit is necessary.",
            "prescribed_medicines": "None",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    plan = db.session.scalar(db.select(HealthPlan).filter_by(pet_id=pet.id).order_by(HealthPlan.id.desc()))
    assert plan is not None
    assert plan.next_visit_on is None
    assert plan.next_visit_purpose is None


def test_vet_schedule_new_plan_by_pet_id_shares_consultation_and_prescription(client, app):
    seed_data()
    owner = db.session.scalar(
        db.select(User).filter_by(email="agalya@demo.petship")
    )
    pet = db.session.scalar(
        db.select(OwnedPet).filter_by(owner_id=owner.id, name="Mochi")
    )
    pet.diet_note = "Wet food morning and evening."
    db.session.add(VetPatient(
        vet_id=db.session.scalar(
            db.select(User.id).filter_by(email="ananya@demo.petship")
        ),
        pet_id=pet.id,
    ))
    db.session.add_all([
        Reminder(
            owner_id=owner.id, pet_id=pet.id, title="Morning meal",
            recurrence=Recurrence.DAILY, next_due=date.today(),
        ),
        Reminder(
            owner_id=owner.id, pet_id=pet.id, title="Follow-up",
            recurrence=Recurrence.ONCE, next_due=date.today() + timedelta(days=5),
        ),
    ])
    db.session.commit()
    login_vet(client)

    page = client.get(f"/vet/patients/new-plan?pet_id={pet.public_pet_id}")
    assert page.status_code == 200
    assert pet.public_pet_id.encode() in page.data
    response = client.post(
        "/vet/patients/new-plan",
        data={
            "pet_id": pet.public_pet_id,
            "consultation": "Monitor appetite and hydration.",
            "diagnosis": "Recovering well",
            "prescribed_medicines": "One tablet with dinner",
            "next_visit_on": (date.today() + timedelta(days=10)).isoformat(),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Save and share with owner" not in response.data
    assert b"Present health record" in response.data
    assert b"Wet food morning and evening." in response.data
    assert b"One tablet with dinner" in response.data
    assert b"Today's schedule" in response.data
    assert b"Morning meal" in response.data
    assert b"Upcoming schedule" in response.data
    assert b"Follow-up" in response.data
    assert db.session.scalar(
        db.select(Notification).filter_by(
            user_id=owner.id, title="New health plan for Mochi"
        )
    ) is not None


def test_vet_cannot_add_unlinked_pet_id(client, app):
    seed_data()
    login_vet(client)
    response = client.post(
        "/vet/patients/new", data={"pet_id": "PET-99999999"}, follow_redirects=True
    )
    assert b"Enter a valid pet ID" in response.data
    assert db.session.scalar(db.select(VetPatient)) is None


def test_vet_cannot_view_another_vets_linked_patient(client, app):
    seed_data()
    owner = db.session.scalar(
        db.select(User).filter_by(email="agalya@demo.petship")
    )
    pet = db.session.scalar(
        db.select(OwnedPet).filter_by(owner_id=owner.id, name="Mochi")
    )
    vet = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    db.session.add(VetPatient(vet_id=vet.id, pet_id=pet.id))
    other_vet = User(
        email="other-vet@example.com",
        first_name="Other",
        role=UserRole.VET,
        is_verified=True,
    )
    other_vet.set_password("password123")
    other_vet.is_active = True
    db.session.add(other_vet)
    db.session.commit()
    client.post("/auth/login", data={
        "role": "vet",
        "email": "other-vet@example.com",
        "password": "password123",
    })

    assert client.get(
        f"/vet/patients/{pet.id}/health-record"
    ).status_code == 404


def test_patient_detail(client, app):
    seed_data()
    _book_with_ananya(client, pet="Mochi")
    login_vet(client)
    appt = db.session.scalar(db.select(Appointment))
    resp = client.get(f"/vet/patients/{appt.id}")
    assert resp.status_code == 200
    assert b"Mochi" in resp.data
    assert b"Owner" in resp.data
    assert b"Visit history" in resp.data


def test_vet_cannot_see_others_patient(client, app):
    seed_data()
    _book_with_ananya(client, pet="Mochi")
    appt = db.session.scalar(db.select(Appointment))
    # Log in as a different vet (Vikram).
    client.post("/auth/login", data={"role": "vet", "email": "vikram@demo.petship", "password": "password123"})
    assert client.get(f"/vet/patients/{appt.id}").status_code == 404


def test_dashboard_stats_count_week(client, app):
    seed_data()
    _book_with_ananya(client, when=date.today().isoformat(), slot="09:30", pet="A")
    _book_with_ananya(client, when=(date.today() + timedelta(days=2)).isoformat(), slot="10:30", pet="B")
    login_vet(client)
    resp = client.get("/vet/dashboard")
    # Two appointments this week.
    assert b"This week" in resp.data


def test_vet_appointment_category_and_period_filters(client, app):
    seed_data()
    vet = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    owner = db.session.scalar(
        db.select(User).filter_by(email="agalya@demo.petship")
    )
    today = date.today()
    db.session.add_all([
        Appointment(
            kind=AppointmentKind.VET_VISIT,
            scheduled_for=datetime.combine(today, datetime.min.time()),
            vet_id=vet.id,
            user_id=owner.id,
            service="Dental",
            note="Mochi dental",
        ),
        Appointment(
            kind=AppointmentKind.VET_VISIT,
            scheduled_for=datetime.combine(today + timedelta(days=1), datetime.min.time()),
            vet_id=vet.id,
            user_id=owner.id,
            service="Vaccination",
            note="Mochi vaccine",
        ),
    ])
    db.session.commit()
    login_vet(client)

    dental = client.get("/vet/appointments?category=dental&period=today")
    assert b"Mochi dental" in dental.data
    assert b"Mochi vaccine" not in dental.data
    vaccination = client.get("/vet/appointments?category=vaccination&period=tomorrow")
    assert b"Mochi vaccine" in vaccination.data
    assert b"Mochi dental" not in vaccination.data


def test_vet_appointment_views_show_linked_pet_id_with_name(client, app):
    seed_data()
    owner = db.session.scalar(
        db.select(User).filter_by(email="agalya@demo.petship")
    )
    pet = db.session.scalar(
        db.select(OwnedPet).filter_by(owner_id=owner.id, name="Mochi")
    )
    vet = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    appointment = Appointment(
        kind=AppointmentKind.VET_VISIT,
        scheduled_for=datetime.combine(
            date.today() + timedelta(days=1), datetime.min.time()
        ),
        vet_id=vet.id,
        user_id=owner.id,
        service="General check-up",
        note=pet.name,
    )
    db.session.add(appointment)
    db.session.commit()
    login_vet(client)

    appointments = client.get("/vet/appointments")
    assert f"{pet.name} · {pet.public_pet_id}".encode() in appointments.data
    dashboard = client.get("/vet/dashboard")
    assert f"{pet.name} · {pet.public_pet_id}".encode() in dashboard.data
    details = client.get(f"/vet/patients/{appointment.id}")
    assert f"{pet.name} · {pet.public_pet_id}".encode() in details.data


def test_vet_dashboard_hides_standalone_medical_and_vaccination_links(client, app):
    seed_data()
    login_vet(client)
    response = client.get("/vet/dashboard")
    assert b"Medical Records</a>" not in response.data
    assert b"Vaccinations</a>" not in response.data
    assert b"New Patient</a>" in response.data
    assert b"Notifications</a>" in response.data
