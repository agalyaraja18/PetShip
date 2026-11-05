"""Shelter pet listing management: add, edit, list, publish (Task 15)."""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from ..extensions import db
from ..models.application import Application, ApplicationStage
from ..models.pet import AgeGroup, Pet, PetStatus, Sex, Size, Species
from ..models.user import UserRole
from ..security import role_required
from ..services.storage import save_image
from .shelter import current_shelter

shelter_pets_bp = Blueprint("shelter_pets", __name__, url_prefix="/shelter/pets")

HEALTH_OPTIONS = ["Vaccinated", "Neutered", "Microchipped", "Special needs"]
PERSONALITY_OPTIONS = ["Playful", "Good with kids", "Good with cats", "Energetic", "Calm"]
GOOD_WITH_OPTIONS = ["kids", "cats", "dogs"]


def _owned_pet_or_404(pet_id: int) -> Pet:
    shelter = current_shelter()
    pet = db.session.get(Pet, pet_id)
    if pet is None or shelter is None or pet.shelter_id != shelter.id:
        abort(404)
    return pet


def _apply_form(pet: Pet, form) -> None:
    pet.name = (form.get("name") or "").strip()
    pet.species = Species(form.get("species", "dog"))
    pet.breed = (form.get("breed") or "").strip() or None
    pet.age_group = AgeGroup(form.get("age_group", "young"))
    pet.age_text = (form.get("age_text") or "").strip() or None
    pet.size = Size(form.get("size", "medium"))
    pet.sex = Sex(form.get("sex", "unknown"))
    pet.description = (form.get("description") or "").strip() or None
    pet.health_tags = [t for t in form.getlist("health_tags") if t in HEALTH_OPTIONS]
    pet.personality_tags = [
        t for t in form.getlist("personality_tags") if t in PERSONALITY_OPTIONS
    ]
    pet.good_with = [t for t in form.getlist("good_with") if t in GOOD_WITH_OPTIONS]
    fee = form.get("adoption_fee")
    pet.adoption_fee = float(fee) if fee else None


@shelter_pets_bp.route("/new", methods=["GET", "POST"])
@role_required(UserRole.SHELTER)
def add():
    from .shelter import _require_shelter

    shelter = _require_shelter()
    if request.method == "POST":
        if not (request.form.get("name") or "").strip():
            flash("Please give the pet a name.", "warning")
            return render_template(
                "shelter/pet_form.html", pet=None, shelter_name=shelter.name,
                options=_options(), active_nav="addpet",
            )
        pet = Pet(shelter_id=shelter.id, species=Species.DOG,
                  age_group=AgeGroup.YOUNG, size=Size.MEDIUM)
        _apply_form(pet, request.form)

        # Photos via storage wrapper (Firebase or local fallback).
        urls = []
        for f in request.files.getlist("photos"):
            url = save_image(f, folder="pets")
            if url:
                urls.append(url)
        pet.photos = urls

        pet.status = (
            PetStatus.AVAILABLE
            if request.form.get("action") == "publish"
            else PetStatus.DRAFT
        )
        db.session.add(pet)
        db.session.commit()
        flash(
            f"{pet.name} {'published' if pet.status == PetStatus.AVAILABLE else 'saved as draft'}.",
            "success",
        )
        return redirect(url_for("shelter_pets.listings"))

    return render_template(
        "shelter/pet_form.html", pet=None, shelter_name=shelter.name,
        options=_options(), active_nav="addpet",
    )


@shelter_pets_bp.route("/<int:pet_id>/edit", methods=["GET", "POST"])
@role_required(UserRole.SHELTER)
def edit(pet_id: int):
    pet = _owned_pet_or_404(pet_id)
    if request.method == "POST":
        _apply_form(pet, request.form)
        new_photos = []
        for f in request.files.getlist("photos"):
            url = save_image(f, folder="pets")
            if url:
                new_photos.append(url)
        if new_photos:
            pet.photos = (pet.photos or []) + new_photos
        if request.form.get("action") == "publish":
            pet.status = PetStatus.AVAILABLE
        db.session.commit()
        flash(f"{pet.name} updated.", "success")
        return redirect(url_for("shelter_pets.listings"))
    return render_template(
        "shelter/pet_form.html", pet=pet, shelter_name=pet.shelter.name,
        options=_options(), active_nav="listings",
    )


@shelter_pets_bp.route("/<int:pet_id>/publish", methods=["POST"])
@role_required(UserRole.SHELTER)
def publish(pet_id: int):
    pet = _owned_pet_or_404(pet_id)
    pet.publish()
    db.session.commit()
    flash(f"{pet.name} is now live.", "success")
    return redirect(url_for("shelter_pets.listings"))


@shelter_pets_bp.route("")
@role_required(UserRole.SHELTER)
def listings():
    from .shelter import _require_shelter

    shelter = _require_shelter()
    status_filter = request.args.get("status", "all")
    pets = list(shelter.pets)
    if status_filter != "all":
        pets = [p for p in pets if p.status.value == status_filter]
    pets.sort(key=lambda p: p.created_at, reverse=True)

    # Application counts per pet.
    app_counts = {}
    pet_ids = [p.id for p in shelter.pets]
    if pet_ids:
        rows = db.session.execute(
            db.select(Application.pet_id, db.func.count())
            .filter(
                Application.pet_id.in_(pet_ids),
                Application.stage != ApplicationStage.DRAFT,
            )
            .group_by(Application.pet_id)
        ).all()
        app_counts = {pid: c for pid, c in rows}

    counts = {
        "all": len(shelter.pets),
        "available": sum(1 for p in shelter.pets if p.status == PetStatus.AVAILABLE),
        "reserved": sum(1 for p in shelter.pets if p.status == PetStatus.RESERVED),
        "adopted": sum(1 for p in shelter.pets if p.status == PetStatus.ADOPTED),
        "draft": sum(1 for p in shelter.pets if p.status == PetStatus.DRAFT),
    }
    return render_template(
        "shelter/listings.html",
        pets=pets,
        counts=counts,
        app_counts=app_counts,
        status_filter=status_filter,
        PetStatus=PetStatus,
        shelter_name=shelter.name,
        active_nav="listings",
    )


def _options():
    return {
        "species": list(Species),
        "ages": list(AgeGroup),
        "sizes": list(Size),
        "sexes": list(Sex),
        "health": HEALTH_OPTIONS,
        "personality": PERSONALITY_OPTIONS,
        "good_with": GOOD_WITH_OPTIONS,
    }
