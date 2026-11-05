"""Public pet discovery: Home and Browse with live filtering (Task 10)."""
from __future__ import annotations

import random

from flask import Blueprint, render_template, request

from ..extensions import db
from ..models.pet import AgeGroup, Pet, PetStatus, Size, Species
from ..models.shelter import Shelter

pets_bp = Blueprint("pets", __name__)


# ---- Home ----
@pets_bp.route("/")
def home():
    discovery_pets = [
        {"name": "Milo", "photo": "/static/img/pets/milo.jpg", "alt": "A playful dog"},
        {"name": "Mochi", "photo": "/static/img/pets/mochi.jpg", "alt": "A calm cat"},
        {"name": "Snow", "photo": "/static/img/pets/snow.jpg", "alt": "A small rabbit"},
    ]
    featured = random.SystemRandom().sample(discovery_pets, k=len(discovery_pets))
    # All figures are real counts from the database, so they grow as the
    # platform is used (pets adopted, shelters verified, listings published).
    stats = {
        "pets_matched": db.session.scalar(
            db.select(db.func.count()).select_from(Pet).filter_by(
                status=PetStatus.ADOPTED
            )
        )
        or 0,
        "verified_shelters": db.session.scalar(
            db.select(db.func.count()).select_from(Shelter).filter_by(is_verified=True)
        )
        or 0,
        "available": db.session.scalar(
            db.select(db.func.count()).select_from(Pet).filter_by(
                status=PetStatus.AVAILABLE
            )
        )
        or 0,
    }

    # Fetch recent community content for the homepage Community Corner.
    from ..models.content import BlogPost, SuccessStory
    blog_posts = db.session.scalars(
        db.select(BlogPost).filter_by(published=True)
        .order_by(BlogPost.created_at.desc()).limit(3)
    ).all()
    stories = db.session.scalars(
        db.select(SuccessStory).order_by(SuccessStory.created_at.desc()).limit(3)
    ).all()

    return render_template(
        "pets/home.html",
        featured=featured,
        stats=stats,
        blog_posts=blog_posts,
        stories=stories,
        active_nav="",
    )


# ---- Browse ----
def _apply_filters(query, args):
    species = args.getlist("species")
    if species:
        query = query.filter(Pet.species.in_([Species(s) for s in species if s in Species._value2member_map_]))

    ages = args.getlist("age")
    if ages:
        query = query.filter(Pet.age_group.in_([AgeGroup(a) for a in ages if a in AgeGroup._value2member_map_]))

    sizes = args.getlist("size")
    if sizes:
        query = query.filter(Pet.size.in_([Size(s) for s in sizes if s in Size._value2member_map_]))

    max_distance = args.get("distance", type=float)
    if max_distance:
        query = query.filter(Pet.distance_km <= max_distance)

    # `good_with` is a JSON array; filtered in Python after fetch for portable
    # behaviour across SQLite and PostgreSQL (see browse()).
    return query


def _apply_sort(query, sort):
    if sort == "nearest":
        return query.order_by(Pet.distance_km.asc().nullslast())
    if sort == "popular":
        return query.order_by(Pet.views.desc())
    # default: newest
    return query.order_by(Pet.created_at.desc())


@pets_bp.route("/browse")
def browse():
    query = db.select(Pet).filter_by(status=PetStatus.AVAILABLE)
    query = _apply_filters(query, request.args)
    query = _apply_sort(query, request.args.get("sort", "newest"))
    results = db.session.scalars(query).all()

    # good_with JSON filter applied in Python (portable across DB backends).
    good_with = request.args.getlist("good_with")
    if good_with:
        results = [
            p for p in results if all(g in (p.good_with or []) for g in good_with)
        ]

    context = {
        "results": results,
        "count": len(results),
        "selected": {
            "species": request.args.getlist("species"),
            "age": request.args.getlist("age"),
            "size": request.args.getlist("size"),
            "good_with": request.args.getlist("good_with"),
            "distance": request.args.get("distance", ""),
            "sort": request.args.get("sort", "newest"),
        },
        "active_nav": "adopt",
    }

    # htmx requests get just the results grid partial for live updates.
    if request.headers.get("HX-Request"):
        return render_template("pets/_results.html", **context)
    return render_template("pets/browse.html", **context)


# ---- Pet details ----
@pets_bp.route("/pets/<int:pet_id>")
def detail(pet_id: int):
    from flask import abort

    pet = db.session.get(Pet, pet_id)
    if pet is None or pet.status in (PetStatus.DRAFT, PetStatus.REMOVED):
        abort(404)
    # Count a view (best-effort, non-blocking for the response).
    pet.views = (pet.views or 0) + 1
    db.session.commit()

    similar = db.session.scalars(
        db.select(Pet)
        .filter(
            Pet.species == pet.species,
            Pet.id != pet.id,
            Pet.status == PetStatus.AVAILABLE,
        )
        .limit(3)
    ).all()
    return render_template("pets/detail.html", pet=pet, similar=similar, active_nav="adopt")


# ---- Search ----
@pets_bp.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    location = (request.args.get("location") or "").strip()

    query = db.select(Pet).filter_by(status=PetStatus.AVAILABLE)
    results = db.session.scalars(query).all()

    # Lightweight text match over name, breed, species, and tags.
    if q:
        needle = q.lower()
        def matches(p):
            haystack = " ".join(
                filter(
                    None,
                    [
                        p.name,
                        p.breed,
                        p.species.label,
                        p.description,
                        " ".join(p.personality_tags or []),
                        " ".join(p.health_tags or []),
                        " ".join(p.good_with or []),
                    ],
                )
            ).lower()
            return needle in haystack
        results = [p for p in results if matches(p)]

    return render_template(
        "pets/search.html",
        results=results,
        count=len(results),
        q=q,
        location=location,
        active_nav="adopt",
    )
