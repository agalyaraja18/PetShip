"""Admin moderation + adoption oversight (Task 36)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models.application import Application, ApplicationStage
from ..models.community import Comment, Post
from ..models.pet import Pet, PetStatus, Species
from ..models.report import AbuseReport, AbuseStatus
from ..models.review import Review
from ..models.user import UserRole
from ..security import role_required

admin_mod_bp = Blueprint("admin_mod", __name__, url_prefix="/admin")


# ---- Listing moderation ----
@admin_mod_bp.route("/listings")
@role_required(UserRole.ADMIN)
def listings():
    status = request.args.get("status", "all")
    if status not in {"all", "available", "draft", "removed", "adopted", "returned"}:
        status = "all"
    species = request.args.get("species", "all")
    if species not in {"all", *[item.value for item in Species]}:
        species = "all"
    query = db.select(Pet)
    if status == "returned":
        query = query.filter(
            db.select(Application.id)
            .where(Application.pet_id == Pet.id, Application.returned_at.is_not(None))
            .exists()
        )
    elif status != "all":
        query = query.filter_by(status=PetStatus(status))
    if species != "all":
        query = query.filter_by(species=Species(species))
    pets = db.session.scalars(query.order_by(Pet.created_at.desc())).all()
    returned_pet_ids = set(db.session.scalars(
        db.select(Application.pet_id).where(Application.returned_at.is_not(None))
    ).all())

    def count_listings(listing_status):
        count_query = db.select(db.func.count()).select_from(Pet)
        if listing_status == "returned":
            count_query = count_query.filter(
                db.select(Application.id)
                .where(Application.pet_id == Pet.id, Application.returned_at.is_not(None))
                .exists()
            )
        elif listing_status != "all":
            count_query = count_query.filter_by(status=PetStatus(listing_status))
        return db.session.scalar(count_query) or 0

    counts = {
        key: count_listings(key)
        for key in ("all", "available", "draft", "removed", "adopted", "returned")
    }
    return render_template(
        "admin/listings.html", pets=pets, counts=counts, status=status,
        species=species,
        species_options=[
            (Species.DOG, "Dogs"),
            (Species.CAT, "Cats"),
            (Species.RABBIT, "Rabbits"),
            (Species.HAMSTER, "Hamsters"),
            (Species.BIRD, "Birds"),
            (Species.FISH, "Fish"),
            (Species.OTHER, "Others"),
        ],
        returned_pet_ids=returned_pet_ids,
        PetStatus=PetStatus,
        active_nav="moderation",
    )


@admin_mod_bp.route("/listings/<int:pet_id>/action", methods=["POST"])
@role_required(UserRole.ADMIN)
def listing_action(pet_id: int):
    pet = db.session.get(Pet, pet_id)
    if pet is None:
        abort(404)
    action = request.form.get("action")
    if action == "remove":
        pet.status = PetStatus.REMOVED
        flash(f"{pet.name} removed from listings.", "info")
    elif action == "approve":
        pet.status = PetStatus.AVAILABLE
        flash(f"{pet.name} approved.", "success")
    elif action == "adopted":
        pet.status = PetStatus.ADOPTED
        flash(f"{pet.name} marked adopted.", "info")
    db.session.commit()
    return redirect(url_for("admin_mod.listings"))


# ---- Adoption oversight ----
@admin_mod_bp.route("/adoptions")
@role_required(UserRole.ADMIN)
def adoptions():
    stages = [
        (ApplicationStage.SUBMITTED, "Application Submitted"),
        (ApplicationStage.REVIEW, "Application Reviewed"),
        (ApplicationStage.CONFIRMED, "Application Confirmed"),
        (ApplicationStage.HOME_VISIT, "Home Visit"),
        (ApplicationStage.AGREEMENT, "Adoption approved"),
        (ApplicationStage.COMPLETE, "Welcome home"),
    ]
    selected_stage = request.args.get("stage", ApplicationStage.SUBMITTED.value)
    valid_stages = {stage.value for stage, _ in stages}
    if selected_stage not in valid_stages:
        selected_stage = ApplicationStage.SUBMITTED.value
    stage = ApplicationStage(selected_stage)
    now = datetime.now(timezone.utc)

    apps = db.session.scalars(
        db.select(Application).filter_by(stage=stage)
        .order_by(Application.created_at.desc())
    ).all()
    counts = {
        item.value: db.session.scalar(
            db.select(db.func.count()).select_from(Application).filter_by(stage=item)
        ) or 0
        for item, _ in stages
    }
    cards = []
    for application in apps:
        created_at = application.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        cards.append({
            "app": application,
            "over_sla": stage != ApplicationStage.COMPLETE
            and (now - created_at) > timedelta(days=7),
        })
    return render_template(
        "admin/adoptions.html", cards=cards, stages=stages, counts=counts,
        selected_stage=selected_stage, active_nav="adoptions",
    )


# ---- Reports & complaints ----
@admin_mod_bp.route("/reports")
@role_required(UserRole.ADMIN)
def reports():
    status = request.args.get("status", "open")
    query = db.select(AbuseReport)
    if status in {s.value for s in AbuseStatus}:
        query = query.filter_by(status=AbuseStatus(status))
    items = db.session.scalars(query.order_by(AbuseReport.created_at.desc())).all()
    return render_template(
        "admin/reports.html", reports=items, status=status,
        AbuseStatus=AbuseStatus, active_nav="reports",
    )


@admin_mod_bp.route("/reports/<int:report_id>/resolve", methods=["POST"])
@role_required(UserRole.ADMIN)
def resolve_report(report_id: int):
    report = db.session.get(AbuseReport, report_id)
    if report is None:
        abort(404)
    report.status = (
        AbuseStatus.DISMISSED if request.form.get("decision") == "dismiss"
        else AbuseStatus.RESOLVED
    )
    db.session.commit()
    flash("Report updated.", "info")
    return redirect(url_for("admin_mod.reports"))


# ---- Community moderation ----
@admin_mod_bp.route("/community")
@role_required(UserRole.ADMIN)
def community():
    posts = db.session.scalars(
        db.select(Post).order_by(Post.created_at.desc()).limit(50)
    ).all()
    return render_template("admin/community.html", posts=posts, active_nav="community")


@admin_mod_bp.route("/community/post/<int:post_id>/action", methods=["POST"])
@role_required(UserRole.ADMIN)
def community_action(post_id: int):
    post = db.session.get(Post, post_id)
    if post is None:
        abort(404)
    action = request.form.get("action")
    if action == "hide":
        post.hidden = True
        flash("Post hidden.", "info")
    elif action == "keep":
        post.hidden = False
        flash("Post kept.", "info")
    db.session.commit()
    return redirect(url_for("admin_mod.community"))


# ---- Review moderation ----
@admin_mod_bp.route("/reviews")
@role_required(UserRole.ADMIN)
def reviews():
    items = db.session.scalars(
        db.select(Review).order_by(Review.created_at.desc()).limit(50)
    ).all()
    return render_template("admin/reviews.html", reviews=items, active_nav="reviews")


@admin_mod_bp.route("/reviews/<int:review_id>/action", methods=["POST"])
@role_required(UserRole.ADMIN)
def review_action(review_id: int):
    review = db.session.get(Review, review_id)
    if review is None:
        abort(404)
    review.hidden = request.form.get("action") == "hide"
    db.session.commit()
    flash("Review updated.", "info")
    return redirect(url_for("admin_mod.reviews"))
