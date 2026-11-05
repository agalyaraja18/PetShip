"""Task 15 tests: shelter pet listing management (add/edit/list/publish)."""
from __future__ import annotations

from petship.extensions import db
from petship.models.pet import Pet, PetStatus
from petship.models.shelter import Shelter
from petship.seed import seed_data


def login_shelter(client):
    seed_data()
    client.post("/auth/login", data={"role": "shelter", "email": "kavya@demo.petship", "password": "password123"})


def happy_paws():
    return db.session.scalar(db.select(Shelter).filter_by(slug="happy-paws"))


def test_add_requires_shelter(client, app):
    seed_data()
    client.post("/auth/login", data={"role": "adopter", "email": "agalya@demo.petship", "password": "password123"})
    assert client.get("/shelter/pets/new").status_code == 403


def test_add_pet_as_draft(client, app):
    login_shelter(client)
    resp = client.post(
        "/shelter/pets/new",
        data={
            "name": "Rex", "species": "dog", "breed": "Boxer",
            "age_group": "adult", "age_text": "3 yrs", "size": "large",
            "sex": "male", "description": "Loyal guard dog.",
            "health_tags": ["Vaccinated"], "action": "draft",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    pet = db.session.scalar(db.select(Pet).filter_by(name="Rex"))
    assert pet is not None
    assert pet.status is PetStatus.DRAFT
    assert pet.health_tags == ["Vaccinated"]


def test_add_pet_published(client, app):
    login_shelter(client)
    client.post(
        "/shelter/pets/new",
        data={"name": "Bella", "species": "cat", "age_group": "young",
              "size": "small", "sex": "female", "action": "publish"},
    )
    pet = db.session.scalar(db.select(Pet).filter_by(name="Bella"))
    assert pet.status is PetStatus.AVAILABLE
    # And it shows up on public browse.
    resp = client.get("/browse")
    assert b"Bella" in resp.data


def test_edit_pet(client, app):
    login_shelter(client)
    pet = db.session.scalar(db.select(Pet).filter_by(name="Bruno"))
    client.post(
        f"/shelter/pets/{pet.id}/edit",
        data={"name": "Bruno", "species": "dog", "breed": "Beagle",
              "age_group": "young", "size": "medium", "sex": "male",
              "description": "Updated description.", "action": "save"},
    )
    db.session.refresh(pet)
    assert pet.description == "Updated description."


def test_publish_draft(client, app):
    login_shelter(client)
    # Create a draft pet owned by happy paws.
    shelter = happy_paws()
    from petship.models.pet import AgeGroup, Sex, Size, Species
    draft = Pet(shelter_id=shelter.id, name="Draftee", species=Species.DOG,
                age_group=AgeGroup.YOUNG, size=Size.SMALL, sex=Sex.MALE,
                status=PetStatus.DRAFT)
    db.session.add(draft)
    db.session.commit()
    client.post(f"/shelter/pets/{draft.id}/publish")
    db.session.refresh(draft)
    assert draft.status is PetStatus.AVAILABLE


def test_cannot_edit_other_shelters_pet(client, app):
    login_shelter(client)
    # A pet belonging to Purr House, not Happy Paws.
    other = db.session.scalar(db.select(Pet).filter_by(name="Ginger"))
    assert client.get(f"/shelter/pets/{other.id}/edit").status_code == 404


def test_listings_table_and_filters(client, app):
    login_shelter(client)
    pet = db.session.scalar(db.select(Pet).filter_by(name="Bruno"))
    pet.photos = ["/static/uploads/pets/bruno.jpg"]
    db.session.commit()
    resp = client.get("/shelter/pets")
    assert resp.status_code == 200
    assert b"Manage pet listings" in resp.data
    assert b"Bruno" in resp.data
    assert b'<img class="list-thumb" src="/static/uploads/pets/bruno.jpg" alt="Bruno"' in resp.data

    # Filter to drafts: Rocky is seeded as a draft but belongs to Second Chance,
    # so Happy Paws should have zero drafts initially.
    resp = client.get("/shelter/pets?status=draft")
    assert resp.status_code == 200


def test_listings_counts(client, app):
    login_shelter(client)
    resp = client.get("/shelter/pets")
    shelter = happy_paws()
    available = sum(1 for p in shelter.pets if p.status == PetStatus.AVAILABLE)
    assert ("Available (%d)" % available).encode() in resp.data
