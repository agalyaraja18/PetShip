"""Task 40: end-to-end smoke test of the core adopter -> shelter -> vet journey.

Exercises the integrated system across blueprints using the seeded demo data,
the same way a real deployment smoke check would.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from petship.extensions import db
from petship.models.application import AdoptionAgreement, Application, ApplicationStage
from petship.models.appointment import Appointment, AppointmentStatus
from petship.models.pet import Pet, PetStatus
from petship.models.review import FollowUp
from petship.seed import seed_data


def test_full_adoption_and_vet_journey(client, app):
    # --- Seed the platform ---
    summary = seed_data()
    assert summary["pets"] >= 10 and summary["vets"] == 3

    # --- Adopter logs in and browses ---
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    assert client.get("/browse").status_code == 200

    bruno = db.session.scalar(db.select(Pet).filter_by(name="Bruno"))
    assert bruno.status is PetStatus.AVAILABLE

    # --- Adopter applies for Bruno (wizard: start -> submit) ---
    client.get(f"/adopt/start/{bruno.id}")
    draft = db.session.scalar(
        db.select(Application).filter_by(pet_id=bruno.id, stage=ApplicationStage.DRAFT)
    )
    assert draft is not None
    client.post(f"/adopt/application/{draft.id}/step/1",
                data={"applicant_name": "Agalya R",
                      "applicant_phone": "+91 98400 12345",
                      "applicant_address": "12 Marina Road, Chennai",
                      "home_type": "Apartment", "ownership": "Own",
                      "sleep_location": "Living room", "hours_alone": "2 to 4",
                      "action": "next"})
    client.post(f"/adopt/application/{draft.id}/step/2",
                data={"current_pets_count": "2", "other_pets": "Cats",
                      "prior_experience": "I care for two cats.", "action": "next"})
    client.post(f"/adopt/application/{draft.id}/step/3",
                data={"ref_name": "Meera", "ref_phone": "555-0123",
                      "action": "next"})
    client.post(f"/adopt/application/{draft.id}/step/4",
                data={"action": "submit"})
    db.session.refresh(draft)
    assert draft.stage is ApplicationStage.SUBMITTED
    client.get("/auth/logout")

    # --- Shelter moves the application through its ordered stages ---
    client.post("/auth/login", data={"role": "shelter", "email": "kavya@demo.petship", "password": "password123"})
    client.post(f"/shelter/requests/{draft.id}/action", data={"action": "review"})
    client.post(f"/shelter/requests/{draft.id}/action", data={"action": "confirm"})
    client.post(
        f"/shelter/requests/{draft.id}/action",
        data={
            "action": "home_visit",
            "scheduled_for": (
                datetime.now(timezone.utc) + timedelta(days=2)
            ).isoformat(),
            "location": "Applicant home",
        },
    )
    visit = db.session.scalar(
        db.select(Appointment).filter_by(application_id=draft.id)
    )
    assert visit.status is AppointmentStatus.CONFIRMED
    visit.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.session.commit()
    client.post(f"/shelter/appointments/{visit.id}/complete-visit")
    client.post(f"/shelter/requests/{draft.id}/action", data={"action": "agreement"})
    db.session.add(AdoptionAgreement(
        application_id=draft.id,
        file_name="agreement.pdf",
        original_filename="agreement.pdf",
        shelter_signature="Kavya",
        adopter_signature="Agalya",
    ))
    db.session.commit()
    client.post(f"/shelter/requests/{draft.id}/action", data={"action": "complete"})
    db.session.refresh(draft)
    assert draft.stage is ApplicationStage.COMPLETE
    db.session.refresh(bruno)
    assert bruno.status is PetStatus.ADOPTED

    # Follow-up schedule was created on completion.
    fus = db.session.scalars(
        db.select(FollowUp).filter_by(application_id=draft.id)
    ).all()
    assert len(fus) == 3
    client.get("/auth/logout")

    # --- Adopter books a vet visit ---
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    when = (date.today() + timedelta(days=1)).isoformat()
    client.post("/book/ananya-rao",
                data={"pet_name": "Mochi", "service": "vaccination",
                      "date": when, "slot": "11:00"})
    appt = db.session.scalar(db.select(Appointment).filter_by(service="Vaccination"))
    assert appt is not None
    assert float(appt.price) == 1250  # consult 500 + vaccination 750

    # --- The adopter can reach their health + notifications surfaces ---
    assert client.get("/health/").status_code == 200
    assert client.get("/lifestyle/notifications").status_code == 200


def test_health_check_and_key_public_pages(client, app):
    seed_data()
    # Liveness probe (used by container healthcheck).
    assert client.get("/healthz").get_json()["status"] == "ok"
    # Core public surfaces render.
    for path in ("/", "/browse", "/vets/", "/community/", "/ai/recommendations",
                 "/about", "/help", "/privacy", "/terms"):
        assert client.get(path).status_code == 200, path


def test_vet_sees_the_booking(client, app):
    seed_data()
    # Adopter books.
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    when = (date.today()).isoformat()
    client.post("/book/ananya-rao",
                data={"pet_name": "Mochi", "service": "general",
                      "date": when, "slot": "10:30"})
    client.get("/auth/logout")
    # Vet sees it on their dashboard.
    client.post("/auth/login", data={"role": "vet", "email": "ananya@demo.petship", "password": "password123"})
    resp = client.get("/vet/dashboard")
    assert resp.status_code == 200
    assert b"Mochi" in resp.data
