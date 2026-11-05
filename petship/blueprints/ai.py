"""AI-powered pages: recommendation questionnaire + match results (Task 26).

The compatibility quiz (Task 27) and chatbot (Task 28) are added next.
"""
from __future__ import annotations

import random

from flask import Blueprint, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models.pet import Pet, PetStatus
from ..services.recommender import recommend

ai_bp = Blueprint("ai", __name__, url_prefix="/ai")

QUIZ_SESSION_KEY = "ai_quiz"
BEST_TYPE_IMAGES = {
    "Adult cats": ("img/pets/mochi.jpg", "Adult cat"),
    "Small calm dogs": ("img/pets/pixie.jpg", "Small calm dog"),
    "Rabbits": ("img/pets/snow.jpg", "Rabbit"),
    "Family dogs": ("img/pets/daisy.jpg", "Family dog"),
    "Medium dogs": ("img/pets/max.jpg", "Medium dog"),
    "Bonded pairs": ("img/pets/storymax.jpg", "Pair of dogs"),
    "Active dogs": ("img/pets/bruno.jpg", "Active dog"),
    "Working breeds": ("img/pets/max.jpg", "Working breed dog"),
    "Young dogs": ("img/pets/milo.jpg", "Young dog"),
    "Adult dogs": ("img/pets/bruno.jpg", "Adult dog"),
    "Cats": ("img/pets/ginger.jpg", "Cat"),
    "Small dogs": ("img/pets/pixie.jpg", "Small dog"),
}

LOCAL_PET_FALLBACKS = {
    "dog": ("img/pets/milo.jpg", "Dog"),
    "cat": ("img/pets/mochi.jpg", "Cat"),
    "rabbit": ("img/pets/snow.jpg", "Rabbit"),
    "bird": ("img/pets/bird.jpg", "Bird"),
}


def _safe_pet_photo(pet) -> str | None:
    """Return a local pet image and never expose fish or other non-pet artwork."""
    photo = pet.primary_photo if pet else None
    if photo and "img/learning/fish" not in photo.lower() and "fish.png" not in photo.lower():
        return photo
    species = pet.species.value if pet and hasattr(pet.species, "value") else "dog"
    fallback = LOCAL_PET_FALLBACKS.get(
        species, LOCAL_PET_FALLBACKS["dog"]
    )[0]
    return "/static/" + fallback


def _record_match_usage() -> None:
    from flask_login import current_user

    from ..models.platform import PlatformMetricEvent

    db.session.add(
        PlatformMetricEvent(
            event_type="ai_match",
            user_id=current_user.id if current_user.is_authenticated else None,
        )
    )
    db.session.commit()


@ai_bp.route("/recommendations")
def teaser():
    """Public teaser page that kicks off the compatibility quiz."""
    # AI art cards use rotating local pet photos, independent of shelter listings.
    discovery = [
        {"name": "Milo", "species": "dog", "photo": "/static/img/pets/milo.jpg"},
        {"name": "Mochi", "species": "cat", "photo": "/static/img/pets/mochi.jpg"},
        {"name": "Snow", "species": "rabbit", "photo": "/static/img/pets/snow.jpg"},
    ]
    hero_pets = random.SystemRandom().sample(discovery, k=2)
    return render_template("ai/teaser.html", hero_pets=hero_pets, active_nav="aimatch")


def _quiz_to_profile(answers: dict) -> dict:
    """Map the compatibility quiz answers to a recommender profile."""
    household = answers.get("household")
    other = answers.get("other_pets")
    return {
        "home": answers.get("space", "house"),
        "activity": answers.get("activity", "moderate"),
        "experience": answers.get("experience", "first_time"),
        "time_at_home": answers.get("time", "medium"),
        "has_kids": household == "kids",
        "other_pets": {"none": "none", "one": "dogs", "many": "both"}.get(other, "none"),
        "species_pref": "any",
    }


@ai_bp.route("/results")
def results():
    """Pet matches computed from the quiz answers."""
    answers = session.get(QUIZ_SESSION_KEY, {})
    profile = _quiz_to_profile(answers)
    pets = db.session.scalars(
        db.select(Pet).filter_by(status=PetStatus.AVAILABLE)
    ).all()
    from ..services.ai import ai_enabled

    matches = recommend(profile, pets, limit=3, enrich=ai_enabled())
    _record_match_usage()
    return render_template(
        "ai/results.html",
        matches=matches,
        profile=profile,
        safe_pet_photo=_safe_pet_photo,
        local_fallbacks=LOCAL_PET_FALLBACKS,
        active_nav="aimatch",
    )


# ---------------------------------------------------------------------------
# Compatibility quiz (10 questions) — the single AI-match entry point.
# ---------------------------------------------------------------------------
@ai_bp.route("/quiz", methods=["GET", "POST"])
@ai_bp.route("/quiz/<int:step>", methods=["GET", "POST"])
def quiz(step: int = 1):
    from ..services.compatibility import QUIZ_QUESTIONS

    total = len(QUIZ_QUESTIONS)
    step = max(1, min(step, total))
    answers = dict(session.get(QUIZ_SESSION_KEY, {}))

    if request.method == "POST":
        question = QUIZ_QUESTIONS[step - 1]
        value = request.form.get(question["id"])
        if value:
            answers[question["id"]] = value
            session[QUIZ_SESSION_KEY] = answers
        action = request.form.get("action", "next")
        if action == "back":
            return redirect(url_for("ai.quiz", step=step - 1))
        if step >= total:
            return redirect(url_for("ai.quiz_results"))
        return redirect(url_for("ai.quiz", step=step + 1))

    return render_template(
        "ai/quiz.html",
        question=QUIZ_QUESTIONS[step - 1],
        step=step,
        total=total,
        answers=answers,
        active_nav="aimatch",
    )


# ---------------------------------------------------------------------------
# Pawly AI care chatbot (Task 28)
# ---------------------------------------------------------------------------
def _pet_context(user) -> str:
    """Build a short context string about the user's pets for the model."""
    from ..models.health import OwnedPet

    pets = db.session.scalars(
        db.select(OwnedPet).filter_by(owner_id=user.id)
    ).all()
    if not pets:
        return "The user has no pets on file."
    return "; ".join(
        f"{p.name} ({p.species or 'pet'}, {p.age_text})" for p in pets
    )


@ai_bp.route("/chat")
@ai_bp.route("/chat/<int:conversation_id>")
def chat(conversation_id: int | None = None):
    from flask_login import current_user

    if not current_user.is_authenticated:
        from flask import redirect as _redirect

        return _redirect(url_for("auth.login", next=url_for("ai.chat")))

    from ..models.chat import Conversation

    convo = None
    if conversation_id:
        convo = db.session.get(Conversation, conversation_id)
        if convo is None or convo.user_id != current_user.id:
            from flask import abort

            abort(404)

    from ..services.ai import ai_enabled

    return render_template(
        "ai/chat.html",
        convo=convo,
        messages=convo.messages if convo else [],
        ai_live=ai_enabled(),
        active_nav="aichat",
    )


@ai_bp.route("/chat/send", methods=["POST"])
def chat_send():
    from flask_login import current_user

    if not current_user.is_authenticated:
        from flask import abort

        abort(403)

    from ..models.chat import ChatMessage, Conversation
    from ..services.ai import care_chat

    message = (request.form.get("message") or "").strip()
    conversation_id = request.form.get("conversation_id", type=int)
    if not message:
        return ("", 204)

    convo = db.session.get(Conversation, conversation_id) if conversation_id else None
    if convo is None or convo.user_id != current_user.id:
        convo = Conversation(
            user_id=current_user.id,
            title=message[:60],
            topic=request.form.get("topic"),
        )
        db.session.add(convo)
        db.session.flush()

    db.session.add(ChatMessage(conversation_id=convo.id, role="user", content=message))

    answer = care_chat(message, _pet_context(current_user))
    db.session.add(ChatMessage(conversation_id=convo.id, role="assistant", content=answer))
    db.session.commit()

    # htmx: return the two new message bubbles plus an OOB conversation id.
    if request.headers.get("HX-Request"):
        return render_template(
            "ai/_chat_exchange.html",
            user_message=message,
            answer=answer,
            conversation_id=convo.id,
        )
    return redirect(url_for("ai.chat", conversation_id=convo.id))


@ai_bp.route("/chat/history")
def chat_history():
    from flask_login import current_user

    if not current_user.is_authenticated:
        from flask import redirect as _redirect

        return _redirect(url_for("auth.login", next=url_for("ai.chat_history")))

    from ..models.chat import Conversation

    convos = db.session.scalars(
        db.select(Conversation)
        .filter_by(user_id=current_user.id)
        .order_by(Conversation.created_at.desc())
    ).all()
    return render_template(
        "ai/chat_history.html", conversations=convos, active_nav="aichat"
    )


@ai_bp.route("/quiz/results")
def quiz_results():
    from ..services.compatibility import (
        AXIS_LABELS,
        archetype,
        axis_label,
        score_axes,
    )

    answers = session.get(QUIZ_SESSION_KEY, {})
    axes = score_axes(answers)
    result = archetype(axes)
    bars = [
        {"axis": a, "label": AXIS_LABELS[a][0], "value": axes[a],
         "text": axis_label(a, axes[a])}
        for a in ("activity", "space", "time", "experience")
    ]
    answered = len([k for k in answers if answers.get(k)])
    _record_match_usage()
    return render_template(
        "ai/quiz_results.html",
        result=result,
        bars=bars,
        answered=answered,
        best_type_images=BEST_TYPE_IMAGES,
        active_nav="aimatch",
    )
