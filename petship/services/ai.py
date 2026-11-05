"""AI provider wrapper backed by Google Gemini (fallback-first).

When ``GEMINI_API_KEY`` is configured, calls go to Gemini. Otherwise every
function returns a safe, deterministic templated response so the app runs with
no key. All model access is isolated here so the rest of the app never imports
the provider SDK directly.
"""
from __future__ import annotations

from flask import current_app


def ai_enabled() -> bool:
    return bool(current_app.config.get("GEMINI_API_KEY"))


def _generate(prompt: str, system: str | None = None) -> str | None:
    """Low-level call to Gemini. Returns text, or None on any failure."""
    if not ai_enabled():
        return None
    try:
        import google.generativeai as genai

        genai.configure(api_key=current_app.config["GEMINI_API_KEY"])
        model = genai.GenerativeModel(
            current_app.config.get("GEMINI_MODEL", "gemini-1.5-flash"),
            system_instruction=system,
        )
        resp = model.generate_content(prompt)
        return (resp.text or "").strip() or None
    except Exception:  # pragma: no cover - network/SDK errors degrade to fallback
        current_app.logger.exception("Gemini call failed; using fallback.")
        return None


def match_explanation(profile: dict, pet, score: int, fallback: str) -> str:
    """Return a short, friendly 'why this match' line. Uses Gemini when
    available, else the provided deterministic fallback."""
    if not ai_enabled():
        return fallback
    prompt = (
        "In one warm sentence (max 20 words), explain why this pet suits the "
        f"adopter. Adopter profile: {profile}. Pet: name={pet.name}, "
        f"species={pet.species.label}, energy={pet.energy}, "
        f"traits={(pet.personality_tags or []) + (pet.good_with or [])}. "
        f"Match score: {score}%."
    )
    text = _generate(prompt, system="You are a concise, kind pet adoption advisor.")
    return text or fallback


def care_chat(message: str, context: str, history: list[dict] | None = None) -> str:
    """Answer a pet-care question. Uses Gemini when configured; otherwise a
    keyword-based guidance responder so answers stay relevant without a key."""
    if ai_enabled():
        prompt = f"Context about the user's pets: {context}\n\nQuestion: {message}"
        system = (
            "You are Pawly, a friendly pet-care assistant for the PetShip "
            "platform. Give practical, general guidance. Always remind users you "
            "are not a substitute for a vet when health is involved. Keep answers "
            "concise."
        )
        result = _generate(prompt, system=system)
        if result:
            return result
    return _fallback_answer(message)


# Lightweight keyword responder used when no AI provider is configured. Keeps
# Pawly genuinely useful (relevant topical guidance) rather than one canned line.
_FALLBACK_TOPICS = [
    (("ear", "scratch", "itch", "mites"),
     "Frequent ear scratching is often caused by ear mites, allergies, or a "
     "yeast build-up. If you see dark discharge, redness, or a smell, book a vet "
     "visit soon. Keep the ears dry and avoid cotton buds inside the canal."),
    (("food", "feed", "diet", "eat", "nutrition"),
     "Feed an age-appropriate, complete food at consistent times, and measure "
     "portions to avoid overfeeding. Keep treats under 10% of daily calories and "
     "always provide fresh water. Introduce any new food gradually over a week."),
    (("vaccin", "shot", "booster"),
     "Core vaccines start young and need boosters on a schedule your vet sets. "
     "Keep a record of dates, and check the Vaccination tracker in your pet's "
     "health section so nothing lapses."),
    (("train", "bite", "chew", "behav", "hiding", "scared", "anxious"),
     "Use short, positive, reward-based sessions and keep routines predictable. "
     "For a nervous pet, give a quiet safe space and let them approach you. Most "
     "settle within a couple of weeks; persistent issues are worth a vet or "
     "trainer's input."),
    (("groom", "bath", "nail", "coat", "fur", "shed"),
     "Brush regularly to manage shedding, trim nails every few weeks, and bathe "
     "only when needed with a pet-safe shampoo. Short-haired pets need less "
     "frequent grooming than long-haired ones."),
    (("vomit", "sick", "diarr", "lethargic", "emergency", "blood", "breath"),
     "That could be a health concern. Please contact a veterinarian promptly — "
     "and if your pet is struggling to breathe, bleeding, or collapsed, use the "
     "Emergency vet finder to reach a 24/7 clinic right away."),
]

_FALLBACK_DEFAULT = (
    "I'm Pawly, your pet-care assistant. I can help with feeding, training, "
    "grooming, vaccinations, and general care questions. Could you tell me a "
    "bit more about what's going on? Remember, for anything urgent or health "
    "related, please contact a vet."
)


def _fallback_answer(message: str) -> str:
    text = (message or "").lower()
    for keywords, answer in _FALLBACK_TOPICS:
        if any(k in text for k in keywords):
            return answer
    return _FALLBACK_DEFAULT
