"""Task 26 tests: deterministic recommender + questionnaire + results."""
from __future__ import annotations

from petship.extensions import db
from petship.models.pet import AgeGroup, Pet, PetStatus, Sex, Size, Species
from petship.models.shelter import Shelter
from petship.seed import seed_data
from petship.services.recommender import recommend


def _shelter():
    s = Shelter(name="S", slug="s", is_verified=True)
    db.session.add(s)
    db.session.commit()
    return s


def _pet(shelter, **kw):
    kw.setdefault("status", PetStatus.AVAILABLE)
    kw.setdefault("age_group", AgeGroup.ADULT)
    p = Pet(shelter_id=shelter.id, **kw)
    db.session.add(p)
    db.session.commit()
    return p


# ---- Deterministic scoring ----
def test_apartment_prefers_small_pets(app):
    s = _shelter()
    small = _pet(s, name="Small", species=Species.CAT, size=Size.SMALL, energy="low")
    large = _pet(s, name="Large", species=Species.DOG, size=Size.LARGE, energy="high")
    profile = {"home": "apartment", "activity": "relaxed", "experience": "first_time"}
    matches = recommend(profile, [small, large], limit=2)
    assert matches[0]["pet"].name == "Small"
    assert matches[0]["space"] > matches[1]["space"]


def test_active_owner_prefers_high_energy(app):
    s = _shelter()
    calm = _pet(s, name="Calm", species=Species.CAT, size=Size.MEDIUM, energy="low")
    zoomy = _pet(s, name="Zoomy", species=Species.DOG, size=Size.MEDIUM, energy="high")
    profile = {"home": "house", "activity": "very_active", "experience": "experienced"}
    matches = recommend(profile, [calm, zoomy], limit=2)
    assert matches[0]["pet"].name == "Zoomy"


def test_scoring_is_deterministic(app):
    s = _shelter()
    pets = [_pet(s, name=f"P{i}", species=Species.DOG, size=Size.MEDIUM, energy="medium")
            for i in range(3)]
    profile = {"home": "house", "activity": "moderate"}
    first = [(m["pet"].id, m["score"]) for m in recommend(profile, pets, limit=3)]
    second = [(m["pet"].id, m["score"]) for m in recommend(profile, pets, limit=3)]
    assert first == second


def test_species_preference_filters(app):
    s = _shelter()
    dog = _pet(s, name="Dog", species=Species.DOG, size=Size.MEDIUM)
    cat = _pet(s, name="Cat", species=Species.CAT, size=Size.SMALL)
    matches = recommend({"species_pref": "cat"}, [dog, cat], limit=5)
    names = {m["pet"].name for m in matches}
    assert names == {"Cat"}


def test_excludes_unavailable(app):
    s = _shelter()
    avail = _pet(s, name="Avail", species=Species.DOG, size=Size.MEDIUM)
    adopted = _pet(s, name="Adopted", species=Species.DOG, size=Size.MEDIUM,
                   status=PetStatus.ADOPTED)
    matches = recommend({}, [avail, adopted], limit=5)
    names = {m["pet"].name for m in matches}
    assert "Adopted" not in names


def test_kids_compatibility_boost(app):
    s = _shelter()
    kid_ok = _pet(s, name="KidOK", species=Species.DOG, size=Size.MEDIUM,
                  energy="medium", good_with=["kids"])
    not_kid = _pet(s, name="NotKid", species=Species.DOG, size=Size.MEDIUM,
                   energy="medium", good_with=[])
    profile = {"home": "house", "activity": "moderate", "has_kids": True}
    matches = recommend(profile, [kid_ok, not_kid], limit=2)
    assert matches[0]["pet"].name == "KidOK"


def test_reason_is_present(app):
    s = _shelter()
    p = _pet(s, name="Bruno", species=Species.DOG, size=Size.SMALL, energy="low")
    matches = recommend({"home": "apartment", "experience": "first_time"}, [p])
    assert matches[0]["reason"]
    assert matches[0]["reason"].endswith(".")


# ---- Quiz -> results flow (the questionnaire was removed) ----
def test_teaser_renders(client, app):
    resp = client.get("/ai/recommendations")
    assert resp.status_code == 200
    assert b"fits your life" in resp.data


def test_quiz_drives_results(client, app):
    seed_data()
    from petship.services.compatibility import QUIZ_QUESTIONS

    # Answer the quiz, then results are computed from those answers.
    for i, q in enumerate(QUIZ_QUESTIONS, start=1):
        client.post(f"/ai/quiz/{i}",
                    data={q["id"]: q["options"][0][0], "action": "next"})
    results = client.get("/ai/results")
    assert results.status_code == 200
    assert b"Lifestyle fit" in results.data
    from petship.models.platform import PlatformMetricEvent

    assert db.session.scalar(
        db.select(db.func.count()).select_from(PlatformMetricEvent)
        .filter_by(event_type="ai_match")
    ) == 1


def test_results_without_profile(client, app):
    seed_data()
    # Hitting results with no questionnaire still renders (empty profile).
    resp = client.get("/ai/results")
    assert resp.status_code == 200
