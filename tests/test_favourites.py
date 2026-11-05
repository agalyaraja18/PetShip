"""Task 12 tests: favourites/wishlist toggle and page."""
from __future__ import annotations

from petship.extensions import db
from petship.models.favourite import Favourite
from petship.models.pet import Pet, PetStatus
from petship.models.user import User, UserRole
from petship.seed import seed_data


def make_adopter(email="a@example.com"):
    u = User(email=email, first_name="A", role=UserRole.ADOPTER)
    u.set_password("password123")
    u.is_active = True
    db.session.add(u)
    db.session.commit()
    return u


def login(client, email="a@example.com"):
    client.post("/auth/login", data={"email": email, "password": "password123"})


def a_pet():
    return db.session.scalar(db.select(Pet).filter_by(name="Bruno"))


def test_toggle_requires_login(client, app):
    seed_data()
    pet = a_pet()
    resp = client.post(f"/favourites/toggle/{pet.id}", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_toggle_adds_then_removes(client, app):
    seed_data()
    make_adopter()
    login(client)
    pet = a_pet()

    client.post(f"/favourites/toggle/{pet.id}", headers={"HX-Request": "true"})
    assert db.session.scalar(
        db.select(Favourite).filter_by(pet_id=pet.id)
    ) is not None

    client.post(f"/favourites/toggle/{pet.id}", headers={"HX-Request": "true"})
    assert db.session.scalar(
        db.select(Favourite).filter_by(pet_id=pet.id)
    ) is None


def test_toggle_htmx_returns_button(client, app):
    seed_data()
    make_adopter()
    login(client)
    pet = a_pet()
    resp = client.post(f"/favourites/toggle/{pet.id}", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert b"pet-fav" in resp.data
    assert b"is-fav" in resp.data  # now favourited


def test_favourites_page_lists_saved(client, app):
    seed_data()
    make_adopter()
    login(client)
    pet = a_pet()
    client.post(f"/favourites/toggle/{pet.id}", headers={"HX-Request": "true"})
    resp = client.get("/favourites/")
    assert resp.status_code == 200
    assert b"Bruno" in resp.data


def test_favourites_empty_state(client, app):
    make_adopter()
    login(client)
    resp = client.get("/favourites/")
    assert b"No favourites yet" in resp.data


def test_unavailable_pet_shows_notify(client, app):
    seed_data()
    adopter = make_adopter()
    login(client)
    # Favourite an adopted pet (Luna) for this adopter.
    luna = db.session.scalar(db.select(Pet).filter_by(name="Luna"))
    assert luna.status is PetStatus.ADOPTED
    db.session.add(Favourite(user_id=adopter.id, pet_id=luna.id))
    db.session.commit()
    resp = client.get("/favourites/")
    assert b"Notify me" in resp.data


def test_duplicate_favourite_not_created(client, app):
    seed_data()
    make_adopter()
    login(client)
    pet = a_pet()
    # Two adds in a row should net to removed (toggle), never a duplicate row.
    client.post(f"/favourites/toggle/{pet.id}", headers={"HX-Request": "true"})
    count = db.session.scalar(
        db.select(db.func.count()).select_from(Favourite).filter_by(pet_id=pet.id)
    )
    assert count == 1


def test_browse_shows_heart(client, app):
    seed_data()
    make_adopter()
    login(client)
    resp = client.get("/browse")
    assert b"pet-fav" in resp.data
