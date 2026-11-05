"""Reviews & ratings — writing and display (Task 31).

Shelter reply handling lives in shelter_ops (Task 17). Here we let users write
reviews for shelters and vets, and expose aggregate helpers used by their
public pages.
"""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models.review import Review, ReviewTarget
from ..models.shelter import Shelter
from ..models.user import UserRole
from ..models.vet import VetProfile

reviews_bp = Blueprint("reviews", __name__, url_prefix="/reviews")


def review_summary(target_type: ReviewTarget, target_id: int) -> dict:
    """Aggregate rating, count, and star distribution for a target."""
    items = db.session.scalars(
        db.select(Review).filter_by(
            target_type=target_type, target_id=target_id, hidden=False
        )
    ).all()
    count = len(items)
    avg = round(sum(r.rating for r in items) / count, 1) if count else 0.0
    dist = {star: 0 for star in range(5, 0, -1)}
    for r in items:
        dist[r.rating] = dist.get(r.rating, 0) + 1
    return {"items": items, "count": count, "avg": avg, "dist": dist}


@reviews_bp.route("/<target_type>/<int:target_id>")
def show(target_type: str, target_id: int):
    try:
        ttype = ReviewTarget(target_type)
    except ValueError:
        abort(404)

    if ttype == ReviewTarget.SHELTER:
        target = db.session.get(Shelter, target_id)
        name = target.name if target else None
    else:
        target = db.session.get(VetProfile, target_id)
        name = target.display_name if target else None
    if target is None:
        abort(404)

    summary = review_summary(ttype, target_id)
    sort = request.args.get("sort", "recent")
    items = list(summary["items"])
    if sort == "helpful":
        items.sort(key=lambda r: r.rating, reverse=True)
    else:
        items.sort(key=lambda r: r.created_at, reverse=True)

    return render_template(
        "community/reviews.html",
        target_type=target_type,
        target_id=target_id,
        target_name=name,
        summary=summary,
        items=items,
        sort=sort,
        active_nav="",
    )


@reviews_bp.route("/<target_type>/<int:target_id>/write", methods=["POST"])
@login_required
def write(target_type: str, target_id: int):
    if current_user.role != UserRole.ADOPTER:
        abort(403)
    try:
        ttype = ReviewTarget(target_type)
    except ValueError:
        abort(404)
    target_model = Shelter if ttype == ReviewTarget.SHELTER else VetProfile
    if db.session.get(target_model, target_id) is None:
        abort(404)
    rating = request.form.get("rating", type=int)
    if rating not in range(1, 6):
        flash("Choose a rating from 1 to 5 stars.", "warning")
        return redirect(url_for("reviews.show", target_type=target_type, target_id=target_id))

    review = db.session.scalar(
        db.select(Review).filter_by(
            author_id=current_user.id, target_type=ttype, target_id=target_id
        )
    )
    if review is None:
        review = Review(
            author_id=current_user.id,
            target_type=ttype,
            target_id=target_id,
            rating=rating,
        )
        db.session.add(review)
    review.rating = rating
    review.body = (request.form.get("body") or "").strip() or None
    review.hidden = False
    db.session.commit()

    # Keep the shelter/vet aggregate rating fresh.
    summary = review_summary(ttype, target_id)
    if ttype == ReviewTarget.VET:
        vet = db.session.get(VetProfile, target_id)
        if vet:
            vet.rating = summary["avg"]
            vet.reviews_count = summary["count"]
            db.session.commit()

    flash("Thanks for your review!", "success")
    return redirect(url_for("reviews.show", target_type=target_type, target_id=target_id))
