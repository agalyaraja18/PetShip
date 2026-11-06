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
from petship.models.review import Review, ReviewTarget
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
    user = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    user.notification_prefs = {
        **user.prefs,
        "messages": True,
    }
    db.session.commit()
    login_vet(client)
    settings_page = client.get("/vet/settings")
    assert b"Notifications" in settings_page.data
    assert b'name="messages"' not in settings_page.data
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
    assert user.prefs["messages"] is True


def test_vet_notifications_page_is_removed(client, app):
    seed_data()
    login_vet(client)

    assert client.get("/vet/notifications").status_code == 404
    assert client.post("/vet/notifications/read-all").status_code == 404
    dashboard = client.get("/vet/dashboard")
    assert b"Notifications</a>" not in dashboard.data
    assert b"Messages</a>" not in dashboard.data


def test_vet_can_view_own_visible_ratings_and_reviews(client, app):
    seed_data()
    vet_user = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    adopter = db.session.scalar(
        db.select(User).filter_by(email="agalya@demo.petship")
    )
    vet_profile = vet_user.vet_profile[0]
    db.session.add_all([
        Review(
            author_id=adopter.id,
            target_type=ReviewTarget.VET,
            target_id=vet_profile.id,
            rating=5,
            body="Kind and thorough care.",
        ),
        Review(
            author_id=adopter.id,
            target_type=ReviewTarget.VET,
            target_id=vet_profile.id,
            rating=1,
            body="Hidden review.",
            hidden=True,
        ),
    ])
    db.session.commit()
    login_vet(client)

    response = client.get("/vet/reviews")

    assert response.status_code == 200
    assert b"Ratings &amp; Reviews" in response.data
    assert b"Kind and thorough care." in response.data
    assert b"Hidden review." not in response.data
    assert b"Average rating" in response.data
    assert b"Total reviews" in response.data


def test_vet_messages_page_is_removed(client, app):
    seed_data()
    login_vet(client)

    assert client.get("/messages/").status_code == 404
    assert client.get("/messages/start/1").status_code == 404


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
    _book_with_ananya(
        client,
        when=(date.today() + timedelta(days=1)).isoformat(),
        slot="12:30",
        pet="Future appointment",
    )
    login_vet(client)
    resp = client.get("/vet/dashboard")
    assert resp.status_code == 200
    assert b"Today's appointments" in resp.data
    assert b"Mochi" in resp.data
    assert b"Future appointment" not in resp.data
    assert b"Monthly appointments" in resp.data
    assert b"appointmentsChart" in resp.data
    assert b"Needs attention" not in resp.data
    assert b"Upcoming appointments" not in resp.data


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
    assert b"Schedule new plan" not in record_page.data
    assert b"Add vaccination" in record_page.data
    today_record_form = record_page.data.split(
        b"<summary>Create today's health record</summary>", 1
    )[1].split(b"</details>", 1)[0]
    assert b"Vaccination" not in today_record_form
    assert b"Surgery" not in today_record_form


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
    assert b"Schedule new plan" not in health_record_page.data
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


def test_vet_health_record_vaccination_and_visit_type_options(client, app):
    seed_data()
    owner = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    pet = db.session.scalar(
        db.select(OwnedPet).filter_by(owner_id=owner.id, name="Mochi")
    )
    vet = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    db.session.add_all([
        VetPatient(vet_id=vet.id, pet_id=pet.id),
        Reminder(
            owner_id=owner.id,
            pet_id=pet.id,
            title="Take Mochi for a walk",
            recurrence=Recurrence.ONCE,
            next_due=date.today() + timedelta(days=3),
        ),
    ])
    db.session.commit()
    login_vet(client)

    record_page = client.get(f"/vet/patients/{pet.id}/health-record")
    assert record_page.status_code == 200
    assert b"Take Mochi for a walk" not in record_page.data
    assert b"Schedule new plan" not in record_page.data
    assert b"Add vaccination" in record_page.data
    today_record_form = record_page.data.split(
        b"<summary>Create today's health record</summary>", 1
    )[1].split(b"</details>", 1)[0]
    assert b"Vaccination" not in today_record_form
    assert b"Surgery" not in today_record_form
    book_visit_form = record_page.data.split(b"<summary>Book a new visit</summary>", 1)[1].split(
        b"</details>", 1
    )[0]
    assert b"Vaccination" not in book_visit_form
    assert b"Surgery" not in book_visit_form

    for rejected_type in ("Vaccination", "Surgery"):
        today_record = client.post(
            f"/vet/patients/{pet.id}/health-record/today-record",
            data={
                "visit_type": rejected_type,
                "findings": f"{rejected_type} should use its separate workflow.",
            },
            follow_redirects=True,
        )
        assert today_record.status_code == 200
        assert b"Choose a valid health record visit type." in today_record.data
        assert db.session.scalar(
            db.select(MedicalRecord).filter_by(
                pet_id=pet.id,
                findings=f"{rejected_type} should use its separate workflow.",
            )
        ) is None

    vaccination_date = date.today() + timedelta(days=2)
    vaccination_response = client.post(
        f"/vet/patients/{pet.id}/health-record/vaccination",
        data={
            "vaccine_name": "Canine influenza",
            "vaccination_date": vaccination_date.isoformat(),
            "vaccination_time": "15:30",
        },
        follow_redirects=True,
    )
    assert vaccination_response.status_code == 200
    assert b"Vaccination saved and shared with the owner." in vaccination_response.data
    assert db.session.scalar(
        db.select(Vaccination).filter_by(
            pet_id=pet.id, name="Canine influenza", due_on=vaccination_date
        )
    ) is not None
    appointment = db.session.scalar(
        db.select(Appointment).filter_by(
            user_id=owner.id,
            vet_id=vet.id,
            service="Vaccination · Canine influenza",
        )
    )
    assert appointment is not None
    assert appointment.scheduled_for.date() == vaccination_date
    assert appointment.scheduled_for.strftime("%H:%M") == "15:30"
    assert db.session.scalar(
        db.select(Notification).filter_by(
            user_id=owner.id,
            title="Vaccination scheduled for Mochi",
        )
    ) is not None

    for rejected_type in ("Vaccination", "Surgery"):
        response = client.post(
            f"/vet/patients/{pet.id}/health-record/book-visit",
            data={
                "visit_type": rejected_type,
                "visit_date": (date.today() + timedelta(days=2)).isoformat(),
                "visit_time": "15:30",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Choose a valid visit type." in response.data
    for rejected_type in ("Vaccination", "Surgery"):
        assert db.session.scalar(
            db.select(Appointment).filter_by(
                user_id=owner.id,
                vet_id=vet.id,
                service=rejected_type,
                note=f"{pet.name} · {pet.public_pet_id}",
            )
        ) is None


def test_vet_prescription_requires_and_shares_four_fields_for_each_medicine(client, app):
    seed_data()
    owner = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    pet = db.session.scalar(
        db.select(OwnedPet).filter_by(owner_id=owner.id, name="Mochi")
    )
    vet = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    db.session.add(VetPatient(vet_id=vet.id, pet_id=pet.id))
    db.session.commit()
    login_vet(client)

    record_page = client.get(f"/vet/patients/{pet.id}/health-record")
    assert b"Add vaccination" in record_page.data
    assert b"Instructions" in record_page.data
    assert b"How many days to be taken" not in record_page.data
    prescription_form = record_page.data.split(
        b'<form id="patient-prescription-form"', 1
    )[1]
    assert prescription_form.index(b"Add another prescription") < prescription_form.index(
        b"Save & share with owner"
    )

    incomplete = client.post(
        f"/vet/patients/{pet.id}/health-record/prescription",
        data={
            "medicine_name": ["Medicine A", "Medicine B"],
            "instructions": ["After food", ""],
            "frequency": ["Days", "Weekly"],
            "stop_date": [
                (date.today() + timedelta(days=14)).isoformat(),
                (date.today() + timedelta(days=28)).isoformat(),
            ],
            "timing_0": ["Morning"],
            "timing_1": ["Evening"],
        },
        follow_redirects=True,
    )
    assert incomplete.status_code == 200
    assert b"Complete the medicine name, instructions, frequency, and stop date" in incomplete.data
    assert db.session.scalar(
        db.select(HealthPlan).filter_by(pet_id=pet.id, title="Prescription · Medicine A, Medicine B")
    ) is None

    response = client.post(
        f"/vet/patients/{pet.id}/health-record/prescription",
        data={
            "medicine_name": ["Medicine A", "Medicine B"],
            "instructions": ["Give after meals", "Use with food"],
            "frequency": ["Days", "Weekly"],
            "stop_date": [
                (date.today() + timedelta(days=14)).isoformat(),
                (date.today() + timedelta(days=28)).isoformat(),
            ],
            "timing_0": ["Morning", "Evening"],
            "timing_1": ["Afternoon"],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Prescription shared with the owner." in response.data
    medicine_a_plan = db.session.scalar(
        db.select(HealthPlan).filter_by(
            pet_id=pet.id,
            title="Prescription · Medicine A",
        )
    )
    medicine_b_plan = db.session.scalar(
        db.select(HealthPlan).filter_by(
            pet_id=pet.id,
            title="Prescription · Medicine B",
        )
    )
    assert medicine_a_plan is not None and medicine_b_plan is not None
    assert medicine_a_plan.prescribed_medicines == "Medicine A"
    assert medicine_a_plan.prescription_end_on == date.today() + timedelta(days=14)
    assert medicine_a_plan.instructions == (
        "Medicine A\nInstructions: Give after meals\n"
        "When to take it: Days\nTiming: Morning, Evening\n"
        f"Stop date: {(date.today() + timedelta(days=14)).strftime('%d %b %Y')}"
    )
    assert medicine_b_plan.prescription_end_on == date.today() + timedelta(days=28)
    assert medicine_b_plan.instructions == (
        "Medicine B\nInstructions: Use with food\n"
        "When to take it: Weekly\nTiming: Afternoon\n"
        f"Stop date: {(date.today() + timedelta(days=28)).strftime('%d %b %Y')}"
    )
    records = db.session.scalars(
        db.select(MedicalRecord).filter(
            MedicalRecord.pet_id == pet.id,
            MedicalRecord.record_type == RecordType.PRESCRIPTION,
            MedicalRecord.title.in_([
                "Prescription · Medicine A",
                "Prescription · Medicine B",
            ]),
        )
    ).all()
    assert len(records) == 2
    assert all(record.shared_with_owner for record in records)
    assert db.session.scalar(
        db.select(Notification).filter_by(
            user_id=owner.id,
            title="Prescription for Mochi",
        )
    ) is not None

    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={"role": "adopter", "email": owner.email, "password": "password123"},
    )
    owner_health = client.get(f"/me/pets/{pet.id}/health")
    assert owner_health.status_code == 200
    assert b"Give after meals" in owner_health.data
    assert b"When to take it: Days" in owner_health.data
    assert b"Timing: Afternoon" in owner_health.data
    assert b"Stop date:" in owner_health.data

    medicine_a_plan.prescription_end_on = date.today() - timedelta(days=1)
    db.session.commit()
    client.get("/auth/logout")
    login_vet(client)
    updated_vet_page = client.get(f"/vet/patients/{pet.id}/health-record")
    past_section = updated_vet_page.data.split(
        b"<h3>Past prescribed medicines</h3>", 1
    )[1].split(b"</section>", 1)[0]
    current_section = updated_vet_page.data.split(
        b"<h3>Present health record", 1
    )[1].split(b"</section>", 1)[0]
    assert b"Medicine A" in past_section
    assert b"Give after meals" in past_section
    assert b"Medicine B" in current_section
    assert b"Medicine A" not in current_section
    assert current_section.count(b"Medicine B") == 2
    assert past_section.count(b"Medicine A") == 2

    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={"role": "adopter", "email": owner.email, "password": "password123"},
    )
    updated_owner_page = client.get(f"/me/pets/{pet.id}/health")
    owner_past_section = updated_owner_page.data.split(
        b"<h3>Prescribed medicines - Past</h3>", 1
    )[1].split(b"</section>", 1)[0]
    owner_current_section = updated_owner_page.data.split(
        b"<h3>Prescribed medicines</h3>", 1
    )[1].split(b"</section>", 1)[0]
    assert b"Medicine A" in owner_past_section
    assert b"Give after meals" in owner_past_section
    assert b"Medicine B" in owner_current_section
    assert b"Medicine A" not in owner_current_section


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
    assert b"Today's health actions" in response.data
    assert b"Morning meal" not in response.data
    assert b"Upcoming schedule" in response.data
    assert b"Follow-up" not in response.data
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


def test_dashboard_shows_requested_counts_and_verification_status(client, app):
    seed_data()
    _book_with_ananya(client, when=date.today().isoformat(), slot="09:30", pet="A")
    _book_with_ananya(client, when=(date.today() + timedelta(days=2)).isoformat(), slot="10:30", pet="B")
    vet = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    vet_profile = vet.vet_profile[0]
    vet_profile.is_verified = True
    pet = db.session.scalar(
        db.select(OwnedPet).filter_by(name="Mochi")
    )
    db.session.add(VetPatient(vet_id=vet.id, pet_id=pet.id))
    db.session.commit()
    login_vet(client)
    resp = client.get("/vet/dashboard")
    assert b"Patients" in resp.data
    assert b">1</div>" in resp.data
    assert b"Appointments" in resp.data
    assert b">2</div>" in resp.data
    assert b"Verification status" in resp.data
    assert b"Verified" in resp.data
    assert b"This week" not in resp.data
    assert b"Needs attention" not in resp.data


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
    assert f"{pet.name} · {pet.public_pet_id}".encode() not in dashboard.data
    details = client.get(f"/vet/patients/{appointment.id}")
    assert f"{pet.name} · {pet.public_pet_id}".encode() in details.data


def test_vet_dashboard_hides_standalone_medical_and_vaccination_links(client, app):
    seed_data()
    login_vet(client)
    response = client.get("/vet/dashboard")
    assert b"Medical Records</a>" not in response.data
    assert b"Vaccinations</a>" not in response.data
    assert b"New Patient</a>" in response.data
    assert b"Notifications</a>" not in response.data
    assert b"Messages</a>" not in response.data
