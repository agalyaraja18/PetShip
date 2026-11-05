"""Admin moderation + adoption oversight (Task 36)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models.application import Application, ApplicationStage
from ..models.community import Comment, Post
from ..models.pet import Pet, PetStatus
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
    query = db.select(Pet)
    if status == "draft":
        query = query.filter_by(status=PetStatus.DRAFT)
    elif status == "available":
        query = query.filter_by(status=PetStatus.AVAILABLE)
    elif status == "removed":
        query = query.filter_by(status=PetStatus.REMOVED)
    pets = db.session.scalars(query.order_by(Pet.created_at.desc())).all()
    counts = {
        "all": db.session.scalar(db.select(db.func.count()).select_from(Pet)) or 0,
        "available": db.session.scalar(db.select(db.func.count()).select_from(Pet).filter_by(status=PetStatus.AVAILABLE)) or 0,
        "draft": db.session.scalar(db.select(db.func.count()).select_from(Pet).filter_by(status=PetStatus.DRAFT)) or 0,
        "removed": db.session.scalar(db.select(db.func.count()).select_from(Pet).filter_by(status=PetStatus.REMOVED)) or 0,
    }
    return render_template(
        "admin/listings.html", pets=pets, counts=counts, status=status,
        PetStatus=PetStatus, active_nav="moderation",
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


# ---- Adoption oversight (kanban) ----
@admin_mod_bp.route("/adoptions")
@role_required(UserRole.ADMIN)
def adoptions():
    stages = [
        ApplicationStage.SUBMITTED, ApplicationStage.REVIEW,
        ApplicationStage.CONFIRMED,
        ApplicationStage.HOME_VISIT, ApplicationStage.AGREEMENT,
        ApplicationStage.COMPLETE,
    ]
    now = datetime.now(timezone.utc)

    def _aware(dt):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    board = {}
    for stage in stages:
        apps = db.session.scalars(
            db.select(Application).filter_by(stage=stage)
            .order_by(Application.created_at.desc())
        ).all()
        # SLA flag: stuck more than 7 days in a non-complete stage.
        cards = [
            {"app": a, "over_sla": stage != ApplicationStage.COMPLETE
             and (now - _aware(a.created_at)) > timedelta(days=7)}
            for a in apps
        ]
        board[stage] = cards
    return render_template(
        "admin/adoptions.html", board=board, stages=stages, active_nav="adoptions",
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
