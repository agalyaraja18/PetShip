"""Deterministic pet recommendation scoring (Task 26).

Pure Python, transparent, and unit-testable — no AI provider required. Given a
questionnaire ``profile`` dict, scores available pets and returns ranked
matches with an overall score plus lifestyle-fit and space-fit sub-scores and
a human-readable reason. OpenAI/Gemini is only used (optionally) to rephrase
the reason, never to compute the score.

Profile keys (all optional, with sensible defaults):
    home: "apartment" | "house" | "villa"
    activity: "relaxed" | "moderate" | "active" | "very_active"
    experience: "first_time" | "some" | "experienced"
    time_at_home: "low" | "medium" | "high"
    has_kids: bool
    other_pets: "none" | "dogs" | "cats" | "both"
    species_pref: "any" | "dog" | "cat" | "rabbit" | "bird"
"""
from __future__ import annotations

from ..models.pet import PetStatus, Size, Species

ENERGY_RANK = {"low": 1, "medium": 2, "high": 3}
ACTIVITY_RANK = {"relaxed": 1, "moderate": 2, "active": 3, "very_active": 3}


def _space_fit(profile: dict, pet) -> int:
    """0-100 how well the pet's size suits the adopter's home."""
    home = profile.get("home", "house")
    size = pet.size
    # Apartments favour small pets; villas/houses handle any size.
    table = {
        "apartment": {Size.SMALL: 100, Size.MEDIUM: 75, Size.LARGE: 45},
        "house": {Size.SMALL: 90, Size.MEDIUM: 95, Size.LARGE: 90},
        "villa": {Size.SMALL: 85, Size.MEDIUM: 95, Size.LARGE: 100},
    }
    return table.get(home, table["house"]).get(size, 80)


def _lifestyle_fit(profile: dict, pet) -> int:
    """0-100 how well the pet's energy/traits suit the adopter's lifestyle."""
    score = 70
    activity = ACTIVITY_RANK.get(profile.get("activity", "moderate"), 2)
    energy = ENERGY_RANK.get((pet.energy or "medium"), 2)

    # Reward matching energy to activity; penalise large mismatches.
    diff = abs(activity - energy)
    score += {0: 25, 1: 10, 2: -15}.get(diff, -15)

    # First-time owners do better with calm/low-energy pets.
    if profile.get("experience") == "first_time" and energy <= 1:
        score += 8
    # Lots of time at home suits higher-need pets; little time suits independent ones.
    if profile.get("time_at_home") == "high" and energy >= 2:
        score += 5
    if profile.get("time_at_home") == "low" and energy <= 1:
        score += 5

    # Kids compatibility.
    if profile.get("has_kids") and "kids" in (pet.good_with or []):
        score += 10
    elif profile.get("has_kids") and "kids" not in (pet.good_with or []):
        score -= 5

    # Existing pets compatibility.
    other = profile.get("other_pets", "none")
    gw = pet.good_with or []
    if other in ("dogs", "both") and "dogs" in gw:
        score += 5
    if other in ("cats", "both") and "cats" in gw:
        score += 5

    return max(0, min(100, score))


def _reason(profile: dict, pet, lifestyle: int, space: int) -> str:
    """A short templated explanation (deterministic)."""
    bits = []
    if profile.get("experience") == "first_time" and (pet.energy or "medium") == "low":
        bits.append("great for first-time owners")
    if profile.get("home") == "apartment" and pet.size == Size.SMALL:
        bits.append("adapts well to apartments")
    if profile.get("has_kids") and "kids" in (pet.good_with or []):
        bits.append("loves kids")
    if (pet.energy or "medium") == "high" and profile.get("activity") in ("active", "very_active"):
        bits.append("a perfect match for an active home")
    if not bits:
        if lifestyle >= space:
            bits.append("fits your daily routine well")
        else:
            bits.append("suits your living space")
    return ", ".join(bits).capitalize() + "."


def recommend(profile: dict, pets, limit: int = 3, enrich: bool = False) -> list[dict]:
    """Rank ``pets`` for the given profile. Returns a list of dicts:
    {pet, score, lifestyle, space, reason}. Highest score first."""
    species_pref = profile.get("species_pref", "any")

    scored = []
    for pet in pets:
        if pet.status != PetStatus.AVAILABLE:
            continue
        if species_pref not in ("any", None) and pet.species != Species(species_pref):
            # Soft filter: skip when a specific species is requested.
            continue

        lifestyle = _lifestyle_fit(profile, pet)
        space = _space_fit(profile, pet)
        overall = round(0.6 * lifestyle + 0.4 * space)
        reason = _reason(profile, pet, lifestyle, space)
        scored.append(
            {
                "pet": pet,
                "score": overall,
                "lifestyle": lifestyle,
                "space": space,
                "reason": reason,
            }
        )

    scored.sort(key=lambda m: m["score"], reverse=True)
    top = scored[:limit]

    if enrich:
        from .ai import match_explanation

        for m in top:
            m["reason"] = match_explanation(profile, m["pet"], m["score"], m["reason"])
    return top
