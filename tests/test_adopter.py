"""Task 22 tests: adopter dashboard, My Adopted Pets, pet profile management."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from petship.extensions import db
from petship.models.application import Application, ApplicationStage, ReturnStatus
from petship.models.health import OwnedPet, Vaccination
from petship.models.lifestyle import ExpenseFrequency, ExpenseItem
from petship.models.appointment import Appointment, AppointmentKind, AppointmentStatus
from petship.models.pet import Pet
from petship.models.user import User
from petship.seed import seed_data


def login_agalya(client):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})


def mochi():
    return db.session.scalar(db.select(OwnedPet).filter_by(name="Mochi"))


def test_adopter_dashboard_redirect(client, app):
    seed_data()
    resp = client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    resp = client.get("/auth/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert "/me/dashboard" in resp.headers["Location"]


def test_dashboard_renders_with_stats(client, app):
    login_agalya(client)
    resp = client.get("/me/dashboard")
    assert resp.status_code == 200
    assert b"Good day, Agalya" in resp.data
    assert b"My pets" in resp.data
    # Agalya owns Mochi and Snowball (2 pets).
    assert b"Mochi" in resp.data
    assert b'href="/me/appointments"' in resp.data


def test_adopter_can_view_and_cancel_vet_appointments(client, app):
    login_agalya(client)
    adopter = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    vet = db.session.scalar(db.select(User).filter_by(email="ananya@demo.petship"))
    appt = Appointment(
        kind=AppointmentKind.VET_VISIT,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=datetime.now(timezone.utc) + timedelta(days=2),
        vet_id=vet.id,
        user_id=adopter.id,
        service="Vaccination",
        location="Happy Paws Clinic",
        note="Mochi",
        reference="VB-TEST1",
    )
    db.session.add(appt)
    db.session.commit()

    page = client.get("/me/appointments?category=vaccination")
    assert page.status_code == 200
    assert b"Book a Vet" in page.data
    assert b"Mochi" in page.data
    assert b"Vaccination" in page.data
    assert b"Cancel appointment" in page.data

    response = client.post(
        f"/me/appointments/{appt.id}/cancel",
        follow_redirects=True,
    )
    assert response.status_code == 200
    db.session.expire_all()
    cancelled = db.session.get(Appointment, appt.id)
    assert cancelled.status == AppointmentStatus.CANCELLED


def test_dashboard_monthly_spend_uses_expense_items(client, app):
    login_agalya(client)
    user = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    db.session.add_all([
        ExpenseItem(
            owner_id=user.id,
            label="Monthly food",
            category="food",
            amount=1200,
            frequency=ExpenseFrequency.MONTHLY,
        ),
        ExpenseItem(
            owner_id=user.id,
            label="Annual checkup",
            category="vet",
            amount=2400,
            frequency=ExpenseFrequency.YEARLY,
        ),
    ])
    db.session.commit()

    response = client.get("/me/dashboard")
    assert b"Monthly spend" in response.data
    assert b"\xe2\x82\xb9" in response.data
    assert "\u20b95,200" in response.data.decode()


def test_my_pets_lists_owned(client, app):
    login_agalya(client)
    resp = client.get("/me/pets")
    assert resp.status_code == 200
    assert b"My Pets" in resp.data
    assert b"Mochi" in resp.data
    assert b"Snowball" in resp.data
    assert b"Add another friend" in resp.data


def test_my_pets_counts_unique_vaccines(client, app):
    login_agalya(client)
    pet = db.session.scalar(db.select(OwnedPet).filter_by(name="Mochi"))

    db.session.add_all([
        Vaccination(pet_id=pet.id, name=" rabies "),
        Vaccination(pet_id=pet.id, name="Rabies"),
    ])
    db.session.commit()

    assert pet.unique_vaccination_count == 4


def test_return_page_filters_by_return_status(client, app):
    login_agalya(client)
    user = db.session.scalar(db.select(User).filter_by(email="agalya@demo.petship"))
    pet = db.session.scalar(db.select(Pet).limit(1))
    application = Application(
        reference="PS-84001",
        applicant_id=user.id,
        pet_id=pet.id,
        stage=ApplicationStage.COMPLETE,
        adopted_at=datetime.now(timezone.utc) - timedelta(days=2),
        return_status=ReturnStatus.SUBMITTED.value,
        return_reason="Needs extra support.",
    )
    db.session.add(application)
    db.session.commit()

    response = client.get("/me/returns?status=submitted")
    assert response.status_code == 200
    assert b"Return submitted" in response.data
    assert b"Needs extra support." in response.data
    assert b"aria-current=\"page\"" in response.data
    assert b"Needs extra support." not in client.get("/me/returns?status=return_visit").data


def test_add_pet(client, app):
    login_agalya(client)
    resp = client.post("/me/pets/add", data={"name": "Rex", "species": "Dog"},
                       follow_redirects=False)
    assert resp.status_code == 302
    pet = db.session.scalar(db.select(OwnedPet).filter_by(name="Rex"))
    assert pet is not None
    assert pet.species == "Dog"


def test_pet_profile_renders_tabs(client, app):
    login_agalya(client)
    pet = mochi()
    resp = client.get(f"/me/pets/{pet.id}")
    assert resp.status_code == 200
    assert b"Basic info" in resp.data
    assert b"Diet &amp; routine" in resp.data
    assert b"Documents" not in resp.data
    assert b"Edit profile" in resp.data
    assert b"Sharing" not in resp.data
    assert b"Behaviour" not in resp.data
    old_documents_tab = client.get(f"/me/pets/{pet.id}?tab=documents")
    assert old_documents_tab.status_code == 302
    assert old_documents_tab.headers["Location"].endswith(f"/me/pets/{pet.id}")


def test_pet_profile_edit_mode(client, app):
    login_agalya(client)
    pet = mochi()
    resp = client.get(f"/me/pets/{pet.id}?edit=1")
    assert resp.status_code == 200
    assert b"Save changes" in resp.data
    assert b'name="species"' in resp.data


def test_pet_profile_basic_save(client, app):
    login_agalya(client)
    pet = mochi()
    client.post(
        f"/me/pets/{pet.id}",
        data={"section": "basic", "name": "Mochi", "breed": "Tabby",
              "weight_kg": "4.5", "microchip_id": "ABC123",
              "personality_tags": ["Calm", "Playful"]},
    )
    db.session.refresh(pet)
    assert pet.weight_kg == 4.5
    assert pet.microchip_id == "ABC123"
    assert set(pet.personality_tags) == {"Calm", "Playful"}


def test_pet_profile_diet_plan_save_and_display(client, app):
    login_agalya(client)
    pet = mochi()
    client.post(f"/me/pets/{pet.id}?tab=diet",
                data={"section": "diet_plan", "diet_note": "No fish treats.",
                      "diet_time": ["08:00", "18:00"],
                      "diet_food": ["Wet food", "Dry food"],
                      "diet_quantity": ["1 pouch", "40 g"]})
    db.session.refresh(pet)
    assert pet.diet_note == "No fish treats."
    assert pet.care_schedule["diet_plan"] == [
        {"time": "08:00", "food": "Wet food", "quantity": "1 pouch"},
        {"time": "18:00", "food": "Dry food", "quantity": "40 g"},
    ]
    assert pet.care_schedule["routine_plan"]
    page = client.get(f"/me/pets/{pet.id}?tab=diet")
    assert b"Wet food" in page.data
    assert b"1 pouch" in page.data
    assert b"No fish treats." in page.data
    assert b"10-minute play" in page.data


def test_pet_profile_routine_plan_save_preserves_diet(client, app):
    login_agalya(client)
    pet = mochi()
    existing_diet = pet.care_schedule["diet_plan"]
    client.post(
        f"/me/pets/{pet.id}?tab=diet",
        data={"section": "routine_plan", "routine_plan": "Walk Mochi by 5 pm each evening."},
    )
    db.session.refresh(pet)
    assert pet.care_schedule["diet_plan"] == existing_diet
    assert pet.care_schedule["routine_plan"] == "Walk Mochi by 5 pm each evening."
    page = client.get(f"/me/pets/{pet.id}?tab=diet")
    assert b"Walk Mochi by 5 pm each evening." in page.data


def test_adding_diet_plans_preserves_existing_plan(client, app):
    login_agalya(client)
    pet = mochi()
    existing_diet = pet.care_schedule["diet_plan"]
    existing_routine = pet.care_schedule["routine_plan"]

    client.post(
        f"/me/pets/{pet.id}?tab=diet",
        data={
            "section": "add_diet_plan",
            "diet_plan_name": "Sensitive stomach",
            "diet_time": ["08:00"],
            "diet_food": ["Prescription food"],
            "diet_quantity": ["50 g"],
            "diet_plan_note": "Serve with water.",
        },
    )
    db.session.refresh(pet)
    assert pet.care_schedule["diet_plan"] == existing_diet
    assert pet.care_schedule["routine_plan"] == existing_routine
    assert pet.care_schedule["diet_plans"] == [{
        "name": "Sensitive stomach",
        "meals": [{"food": "Prescription food", "quantity": "50 g", "time": "08:00"}],
        "notes": "Serve with water.",
    }]
    page = client.get(f"/me/pets/{pet.id}?tab=diet")
    assert b"Sensitive stomach" in page.data
    assert b"Prescription food" in page.data


def test_adding_routine_plans_preserves_existing_plan(client, app):
    login_agalya(client)
    pet = mochi()
    existing_diet = pet.care_schedule["diet_plan"]
    existing_routine = pet.care_schedule["routine_plan"]

    client.post(
        f"/me/pets/{pet.id}?tab=diet",
        data={
            "section": "add_routine_plan",
            "routine_plan_name": "Weekend routine",
            "routine_plan_details": "Long walk after breakfast.",
        },
    )
    db.session.refresh(pet)
    assert pet.care_schedule["diet_plan"] == existing_diet
    assert pet.care_schedule["routine_plan"] == existing_routine
    assert pet.care_schedule["routine_plans"] == [{
        "name": "Weekend routine",
        "details": "Long walk after breakfast.",
    }]
    page = client.get(f"/me/pets/{pet.id}?tab=diet")
    assert b"Weekend routine" in page.data
    assert b"Long walk after breakfast." in page.data


def test_pet_profile_legacy_care_schedule_still_renders(client, app):
    login_agalya(client)
    pet = mochi()
    pet.care_schedule = [
        {"time": "08:00", "food": "Legacy food", "activity": "Morning walk", "notes": "Fresh water"}
    ]
    db.session.commit()
    page = client.get(f"/me/pets/{pet.id}?tab=diet")
    assert page.status_code == 200
    assert b"Legacy food" in page.data
    assert b"Morning walk" in page.data


def test_cannot_edit_others_pet(client, app):
    login_agalya(client)
    from petship.models.user import User
    other = User(email="z@example.com", first_name="Z")
    other.set_password("password123")
    other.is_active = True
    db.session.add(other)
    db.session.commit()
    their = OwnedPet(owner_id=other.id, name="Theirs")
    db.session.add(their)
    db.session.commit()
    assert client.get(f"/me/pets/{their.id}").status_code == 404


def test_dashboard_requires_login(client, app):
    resp = client.get("/me/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]
