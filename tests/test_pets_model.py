"""Task 9 tests: Pet and Shelter models plus the seed command."""
from __future__ import annotations

from petship.extensions import db
from petship.models.pet import AgeGroup, Pet, PetStatus, Sex, Size, Species
from petship.models.shelter import Shelter
from petship.models.user import User, UserRole
from petship.seed import seed_data


def make_shelter(name="Test Shelter", slug="test-shelter"):
    s = Shelter(name=name, slug=slug, city="Chennai", is_verified=True)
    db.session.add(s)
    db.session.commit()
    return s


def test_shelter_pet_relationship(app):
    s = make_shelter()
    p = Pet(
        shelter=s, name="Bruno", species=Species.DOG, age_group=AgeGroup.YOUNG,
        size=Size.MEDIUM, status=PetStatus.AVAILABLE,
    )
    db.session.add(p)
    db.session.commit()
    assert p.shelter.name == "Test Shelter"
    assert s.pets[0].name == "Bruno"
    assert s.available_count == 1


def test_status_transitions(app):
    s = make_shelter()
    p = Pet(shelter=s, name="Daisy", species=Species.DOG, age_group=AgeGroup.ADULT,
            size=Size.MEDIUM, status=PetStatus.DRAFT)
    db.session.add(p)
    db.session.commit()
    assert p.status is PetStatus.DRAFT
    p.publish()
    assert p.status is PetStatus.AVAILABLE
    p.reserve()
    assert p.status is PetStatus.RESERVED
    p.mark_adopted()
    assert p.status is PetStatus.ADOPTED


def test_status_badge_variant(app):
    assert PetStatus.AVAILABLE.badge_variant == "success"
    assert PetStatus.RESERVED.badge_variant == "warning"
    assert PetStatus.ADOPTED.badge_variant == "info"


def test_pet_helpers(app):
    s = make_shelter()
    p = Pet(
        shelter=s, name="Mochi", species=Species.CAT, breed="Tabby",
        age_group=AgeGroup.ADULT, age_text="3 yrs", size=Size.SMALL,
        sex=Sex.FEMALE, photos=["/a.jpg", "/b.jpg"],
    )
    db.session.add(p)
    db.session.commit()
    assert p.primary_photo == "/a.jpg"
    assert "Tabby" in p.summary
    assert "Female" in p.summary


def test_json_tag_fields_persist(app):
    s = make_shelter()
    p = Pet(
        shelter=s, name="Coco", species=Species.DOG, age_group=AgeGroup.ADULT,
        size=Size.SMALL, health_tags=["Vaccinated", "Trained"],
        good_with=["kids", "cats"],
    )
    db.session.add(p)
    db.session.commit()
    loaded = db.session.get(Pet, p.id)
    assert loaded.health_tags == ["Vaccinated", "Trained"]
    assert loaded.good_with == ["kids", "cats"]


def test_cascade_delete_removes_pets(app):
    s = make_shelter()
    db.session.add(Pet(shelter=s, name="X", species=Species.DOG,
                       age_group=AgeGroup.YOUNG, size=Size.SMALL))
    db.session.commit()
    db.session.delete(s)
    db.session.commit()
    assert db.session.query(Pet).count() == 0


# ---- Seed ----
def test_seed_populates_expected_counts(app):
    summary = seed_data()
    assert summary["shelters"] == 3
    assert summary["pets"] == 11
    assert summary["available"] == 9
    # Known pets exist.
    names = {p.name for p in db.session.scalars(db.select(Pet)).all()}
    assert {"Bruno", "Mochi", "Daisy", "Pixie", "Snow"} <= names


def test_seed_is_idempotent(app):
    seed_data()
    first = db.session.query(Pet).count()
    seed_data()
    second = db.session.query(Pet).count()
    assert first == second == 11


def test_seed_creates_roles(app):
    seed_data()
    roles = {
        u.email: u.role
        for u in db.session.scalars(db.select(User)).all()
        if u.email.endswith("@demo.petship")
    }
    assert roles["kavya@demo.petship"] is UserRole.SHELTER
    assert roles["ananya@demo.petship"] is UserRole.VET
    assert roles["admin@demo.petship"] is UserRole.ADMIN


def test_seed_draft_and_adopted_present(app):
    seed_data()
    statuses = {p.name: p.status for p in db.session.scalars(db.select(Pet)).all()}
    assert statuses["Rocky"] is PetStatus.DRAFT
    assert statuses["Luna"] is PetStatus.ADOPTED
