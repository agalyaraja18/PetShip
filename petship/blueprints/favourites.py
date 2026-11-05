"""Favourites / wishlist (Task 12).

A heart toggle appears on every pet card. Toggling requires login; htmx swaps
just the heart button. The Favourites page lists saved pets with availability
badges and a "Notify me" affordance for unavailable pets.
"""
from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models.favourite import Favourite
from ..models.pet import Pet, PetStatus

favourites_bp = Blueprint("favourites", __name__, url_prefix="/favourites")


def favourite_pet_ids(user) -> set[int]:
    if not user or not user.is_authenticated:
        return set()
    rows = db.session.scalars(
        db.select(Favourite.pet_id).filter_by(user_id=user.id)
    ).all()
    return set(rows)


@favourites_bp.route("/toggle/<int:pet_id>", methods=["POST"])
@login_required
def toggle(pet_id: int):
    pet = db.session.get(Pet, pet_id)
    if pet is None:
        abort(404)

    existing = db.session.scalar(
        db.select(Favourite).filter_by(user_id=current_user.id, pet_id=pet_id)
    )
    if existing:
        db.session.delete(existing)
        is_fav = False
    else:
        db.session.add(Favourite(user_id=current_user.id, pet_id=pet_id))
        is_fav = True
    db.session.commit()

    # htmx: return just the heart button in its new state.
    if request.headers.get("HX-Request"):
        return render_template("pets/_fav_button.html", pet=pet, is_fav=is_fav)
    return redirect(request.referrer or url_for("pets.browse"))


@favourites_bp.route("/")
@login_required
def index():
    favs = db.session.scalars(
        db.select(Favourite)
        .filter_by(user_id=current_user.id)
        .order_by(Favourite.created_at.desc())
    ).all()
    pets = [f.pet for f in favs if f.pet is not None]
    return render_template(
        "pets/favourites.html",
        pets=pets,
        PetStatus=PetStatus,
        active_nav="favourites",
    )
