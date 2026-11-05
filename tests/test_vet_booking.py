"""Task 19 tests: vet appointment booking and confirmation."""
from __future__ import annotations

from datetime import date, timedelta

from petship.extensions import db
from petship.models.appointment import Appointment, AppointmentKind, AppointmentStatus
from petship.models.user import User, UserRole
from petship.models.vet import VetProfile
from petship.seed import seed_data


def login_adopter(client):
    seed_data()
    u = User(email="booker@example.com", first_name="Booker", role=UserRole.ADOPTER,
             is_verified=True)
    u.set_password("password123")
    u.is_active = True
    db.session.add(u)
    db.session.commit()
    client.post("/auth/login", data={"role": "adopter", "email": "booker@example.com", "password": "password123"})
    return u


def ananya():
    return db.session.scalar(db.select(VetProfile).filter_by(slug="ananya-rao"))


def test_booking_requires_login(client, app):
    seed_data()
    resp = client.get("/book/ananya-rao", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_booking_page_renders(client, app):
    login_adopter(client)
    resp = client.get("/book/ananya-rao")
    assert resp.status_code == 200
    assert b"Book a vet visit" in resp.data
    assert b"Vaccination" in resp.data
    assert b"Confirm booking" in resp.data


def test_create_booking(client, app):
    login_adopter(client)
    when = (date.today() + timedelta(days=1)).isoformat()
    resp = client.post(
        "/book/ananya-rao",
        data={"pet_name": "Mochi", "service": "vaccination", "date": when, "slot": "11:00"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    appt = db.session.scalar(db.select(Appointment))
    assert appt is not None
    assert appt.kind is AppointmentKind.VET_VISIT
    assert appt.service == "Vaccination"
    assert appt.note == "Mochi"
    # Vaccination = consult_fee(500) + 750 = 1250.
    assert float(appt.price) == 1250


def test_booking_requires_date_and_slot(client, app):
    login_adopter(client)
    resp = client.post("/book/ananya-rao", data={"service": "general"})
    assert resp.status_code == 200
    assert b"choose a date and time" in resp.data
    assert db.session.scalar(db.select(Appointment)) is None


def test_double_booking_blocked(client, app):
    login_adopter(client)
    when = (date.today() + timedelta(days=2)).isoformat()
    data = {"pet_name": "Mochi", "service": "general", "date": when, "slot": "10:30"}
    client.post("/book/ananya-rao", data=data)
    # Second booking for the same vet/slot is rejected.
    resp = client.post("/book/ananya-rao", data=data)
    assert b"just taken" in resp.data
    count = db.session.scalar(db.select(db.func.count()).select_from(Appointment))
    assert count == 1


def test_video_consult_uses_video_fee(client, app):
    login_adopter(client)
    when = (date.today() + timedelta(days=3)).isoformat()
    client.post(
        "/book/ananya-rao",
        data={"pet_name": "Mochi", "service": "video", "date": when, "slot": "14:00"},
    )
    appt = db.session.scalar(db.select(Appointment))
    assert float(appt.price) == 350  # Ananya's video_fee


def test_confirmation_page(client, app):
    login_adopter(client)
    when = (date.today() + timedelta(days=1)).isoformat()
    client.post(
        "/book/ananya-rao",
        data={"pet_name": "Mochi", "service": "general", "date": when, "slot": "09:30"},
    )
    appt = db.session.scalar(db.select(Appointment))
    resp = client.get(f"/book/confirmation/{appt.id}")
    assert resp.status_code == 200
    assert b"You're booked" in resp.data
    assert appt.reference.encode() in resp.data


def test_cannot_view_others_confirmation(client, app):
    login_adopter(client)
    when = (date.today() + timedelta(days=1)).isoformat()
    client.post("/book/ananya-rao",
                data={"pet_name": "X", "service": "general", "date": when, "slot": "09:30"})
    appt = db.session.scalar(db.select(Appointment))
    # Another user logs in.
    other = User(email="other@example.com", first_name="O", role=UserRole.ADOPTER)
    other.set_password("password123")
    other.is_active = True
    db.session.add(other)
    db.session.commit()
    client.get("/auth/logout")
    client.post("/auth/login", data={"role": "adopter", "email": "other@example.com", "password": "password123"})
    assert client.get(f"/book/confirmation/{appt.id}").status_code == 404


def test_booking_404_unknown_vet(client, app):
    login_adopter(client)
    assert client.get("/book/nobody").status_code == 404
