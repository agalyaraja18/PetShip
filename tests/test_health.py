"""Task 21 tests: medical records, vaccinations, adopter health views."""
from __future__ import annotations

from datetime import date, timedelta

from petship.extensions import db
from petship.models.health import (
    HealthPlan,
    MedicalRecord,
    OwnedPet,
    RecordType,
    Vaccination,
    VaccineStatus,
    VetPatient,
)
from petship.models.user import User
from petship.seed import seed_data


def login_agalya(client):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})


def mochi():
    return db.session.scalar(db.select(OwnedPet).filter_by(name="Mochi"))


# ---- Model ----
def test_vaccination_status_computation(app):
    today = date.today()
    overdue = Vaccination(pet_id=1, name="Rabies", due_on=today - timedelta(days=5))
    due = Vaccination(pet_id=1, name="FeLV", due_on=today + timedelta(days=10))
    upcoming = Vaccination(pet_id=1, name="FVRCP", due_on=today + timedelta(days=200))
    done = Vaccination(pet_id=1, name="Done", due_on=None)
    assert overdue.status is VaccineStatus.OVERDUE
    assert due.status is VaccineStatus.DUE
    assert upcoming.status is VaccineStatus.UPCOMING
    assert done.status is VaccineStatus.DONE


def test_owned_pet_age_text(app):
    p = OwnedPet(owner_id=1, name="X", date_of_birth=date.today() - timedelta(days=800))
    assert "yr" in p.age_text


# ---- Health dashboard ----
def test_health_dashboard_renders(client, app):
    login_agalya(client)
    resp = client.get("/health/")
    assert resp.status_code == 200
    assert b"Mochi" in resp.data
    assert b"Vaccinations" in resp.data


def test_health_dashboard_switch_pet(client, app):
    login_agalya(client)
    snowball = db.session.scalar(db.select(OwnedPet).filter_by(name="Snowball"))
    resp = client.get(f"/health/pet/{snowball.id}")
    assert resp.status_code == 200
    assert b"Snowball" in resp.data


def test_upcoming_vaccinations_do_not_link_to_primary_vet(client, app):
    login_agalya(client)
    pet = mochi()
    response = client.get(f"/me/pets/{pet.id}/health")
    assert response.status_code == 200
    assert b"Book Dr. Ananya Rao" not in response.data

    booking = client.get("/book/ananya-rao?pet_name=Mochi&service=vaccination")
    assert booking.status_code == 200
    assert b'value="Mochi"' in booking.data
    assert b'"vaccination"' in booking.data


def test_cannot_view_others_pet_health(client, app):
    login_agalya(client)
    # Create a pet owned by someone else.
    other = User(email="z@example.com", first_name="Z")
    other.set_password("password123")
    other.is_active = True
    db.session.add(other)
    db.session.commit()
    their_pet = OwnedPet(owner_id=other.id, name="NotYours")
    db.session.add(their_pet)
    db.session.commit()
    assert client.get(f"/health/pet/{their_pet.id}").status_code == 404


# ---- Records ----
def test_adopter_lab_report_page(client, app):
    login_agalya(client)
    pet = mochi()
    report = MedicalRecord(
        pet_id=pet.id,
        vet_id=None,
        record_type=RecordType.LAB,
        title="Chest X-ray",
        record_date=date.today(),
        vet_name="Ananya Rao",
        findings="Chest clear.",
        shared_with_owner=True,
    )
    db.session.add(report)
    db.session.add(MedicalRecord(
        pet_id=pet.id,
        record_type=RecordType.LAB,
        title="Chest X-ray",
        record_date=date.today(),
        vet_name="Ananya Rao",
        findings="Duplicate test record.",
        shared_with_owner=True,
    ))
    db.session.commit()

    overview = client.get(f"/me/pets/{pet.id}/health")
    assert overview.status_code == 200
    assert b"Lab reports" in overview.data
    assert b"Chest X-ray" in overview.data

    page = client.get(
        f"/me/pets/{pet.id}/health/lab-reports?record={report.id}"
    )
    assert page.status_code == 200
    assert b"Chest X-ray" in page.data


def test_records_list_and_filter(client, app):
    login_agalya(client)
    pet = mochi()
    resp = client.get(f"/health/pet/{pet.id}/records")
    assert resp.status_code == 200
    assert b"Complete blood panel" in resp.data

    resp = client.get(f"/health/pet/{pet.id}/records?type=surgery")
    assert b"Spay surgery report" in resp.data
    assert b"Complete blood panel" not in resp.data


def test_current_prescription_plan_is_shown_for_adopter(client, app):
    login_agalya(client)
    pet = mochi()
    db.session.add(HealthPlan(
        pet_id=pet.id,
        title="Prescription · Doxycycline",
        prescribed_medicines="One deworming tablet every night for 14 days",
        prescription_start_on=date.today(),
        prescription_end_on=date.today() + timedelta(days=13),
    ))
    db.session.commit()

    response = client.get(f"/me/pets/{pet.id}/health")

    assert response.status_code == 200
    assert b"One deworming tablet every night for 14 days" in response.data


def test_adopter_health_overview_has_viewable_record_layout(client, app):
    login_agalya(client)
    pet = mochi()
    response = client.get(f"/me/pets/{pet.id}/health")
    assert response.status_code == 200
    assert b"Past checkups" in response.data
    assert b"Prescribed medicines - Past" in response.data
    assert b"Prescribed medicines" in response.data
    assert b"Lab reports" in response.data
    assert b"Past checkups / Medical reports" in response.data

    record = next(
        record for record in pet.medical_records
        if record.shared_with_owner
    )
    view_page = client.get(
        f"/me/pets/{pet.id}/health/records/{record.id}"
    )
    assert view_page.status_code == 200
    assert b"General check-up" in view_page.data
    assert b"Diagnosis / conclusion" in view_page.data
    assert b"Prescription" not in view_page.data


def test_record_pdf_download(client, app):
    login_agalya(client)
    pet = mochi()
    record = pet.medical_records[0]
    resp = client.get(f"/health/record/{record.id}.pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.headers["Content-Disposition"].startswith("inline;")
    assert resp.data[:4] == b"%PDF"


# ---- Vaccination tracker ----
def test_vaccination_tracker(client, app):
    login_agalya(client)
    pet = mochi()
    resp = client.get(f"/health/pet/{pet.id}/vaccinations")
    assert resp.status_code == 200
    assert b"Vaccination tracker" in resp.data
    assert b"Rabies" in resp.data


# ---- Vet-side record creation ----
def test_vet_creates_and_shares_record(client, app):
    seed_data()
    pet = db.session.scalar(db.select(OwnedPet).filter_by(name="Mochi"))
    vet = db.session.scalar(
        db.select(User).filter_by(email="ananya@demo.petship")
    )
    db.session.add(VetPatient(vet_id=vet.id, pet_id=pet.id))
    db.session.commit()
    client.post("/auth/login", data={"role": "vet", "email": "ananya@demo.petship", "password": "password123"})
    before = len(pet.medical_records)
    client.post(
        "/health/vet/record/new",
        data={
            "pet_id": pet.id, "record_type": "consultation",
            "title": "Ear check", "record_date": date.today().isoformat(),
            "findings": "Mild wax", "diagnosis": "Healthy",
            "summary": "Recheck in 2 weeks.",
        },
    )
    db.session.refresh(pet)
    assert len(pet.medical_records) == before + 1
    # And the owner can now see it.
    client.get("/auth/logout")
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    resp = client.get(f"/health/pet/{pet.id}/records")
    assert b"Ear check" in resp.data


def test_new_record_requires_vet(client, app):
    login_agalya(client)
    assert client.get("/health/vet/record/new").status_code == 403
