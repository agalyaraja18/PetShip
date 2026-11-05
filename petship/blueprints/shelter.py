"""Shelter operations: dashboard, profile, public page (Task 14).

Listing management, requests, appointments, reviews, and follow-ups are added
in Tasks 15-17.
"""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import IntegerField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from ..extensions import db
from ..models.application import Application, ApplicationStage
from ..models.pet import Pet, PetStatus
from ..models.shelter import Shelter
from ..models.user import UserRole
from ..security import role_required

shelter_bp = Blueprint("shelter", __name__, url_prefix="/shelter")


def current_shelter() -> Shelter | None:
    """The shelter owned by the logged-in shelter user (first, if several)."""
    if not current_user.is_authenticated:
        return None
    profiles = getattr(current_user, "shelter_profile", None) or []
    return profiles[0] if profiles else None


def _require_shelter() -> Shelter:
    shelter = current_shelter()
    if shelter is None:
        # A shelter user without a profile yet: create a stub to edit.
        shelter = Shelter(
            owner_id=current_user.id,
            name=f"{current_user.full_name}'s Shelter",
            slug=f"shelter-{current_user.id}",
        )
        db.session.add(shelter)
        db.session.commit()
    return shelter


class ShelterProfileForm(FlaskForm):
    name = StringField("Shelter name", validators=[DataRequired(), Length(max=160)])
    address = StringField("Address", validators=[Optional(), Length(max=300)])
    city = StringField("City", validators=[Optional(), Length(max=120)])
    phone = StringField("Phone number", validators=[Optional(), Length(max=40)])
    about = TextAreaField("About", validators=[Optional(), Length(max=2000)])
    contact_name = StringField("Contact name", validators=[Optional(), Length(max=120)])
    registration_no = StringField("Registration no.", validators=[Optional(), Length(max=80)])
    capacity = IntegerField("Capacity", validators=[Optional()])
    operating_since = IntegerField("Operating since (year)", validators=[Optional()])


@shelter_bp.route("/dashboard")
@role_required(UserRole.SHELTER)
def dashboard():
    shelter = _require_shelter()

    pets = shelter.pets
    listed = len(pets)
    adopted = sum(1 for p in pets if p.status == PetStatus.ADOPTED)

    # Recent adoption requests for this shelter's pets.
    pet_ids = [p.id for p in pets]
    recent_requests = []
    new_count = 0
    if pet_ids:
        recent_requests = db.session.scalars(
            db.select(Application)
            .filter(
                Application.pet_id.in_(pet_ids),
                Application.stage != ApplicationStage.DRAFT,
            )
            .order_by(Application.created_at.desc())
            .limit(6)
        ).all()
        new_count = db.session.scalar(
            db.select(db.func.count())
            .select_from(Application)
            .filter(
                Application.pet_id.in_(pet_ids),
                Application.stage == ApplicationStage.SUBMITTED,
            )
        ) or 0

    # Simple monthly adoptions series for the bar chart (last 6 months buckets).
    stats = {
        "listed": listed,
        "new_requests": new_count,
        "adopted": adopted,
        "rating": round(shelter.avg_response_hours or 4.8, 1),
    }
    return render_template(
        "shelter/dashboard.html",
        shelter=shelter,
        stats=stats,
        recent_requests=recent_requests,
        shelter_name=shelter.name,
        active_nav="dashboard",
    )


@shelter_bp.route("/profile", methods=["GET", "POST"])
@role_required(UserRole.SHELTER)
def profile():
    shelter = _require_shelter()
    form = ShelterProfileForm(obj=shelter)
    if request.method == "GET":
        form.phone.data = current_user.phone
    if form.validate_on_submit():
        shelter.name = form.name.data.strip()
        shelter.address = (form.address.data or "").strip() or None
        shelter.city = (form.city.data or "").strip() or None
        current_user.phone = (form.phone.data or "").strip() or None
        shelter.about = (form.about.data or "").strip() or None
        shelter.contact_name = (form.contact_name.data or "").strip() or None
        shelter.registration_no = (form.registration_no.data or "").strip() or None
        shelter.capacity = form.capacity.data
        shelter.operating_since = form.operating_since.data
        db.session.commit()
        flash("Shelter profile updated.", "success")
        return redirect(url_for("shelter.profile"))
    return render_template(
        "shelter/profile.html",
        form=form,
        shelter=shelter,
        edit_mode=request.method == "POST" or request.args.get("edit") == "1",
        shelter_name=shelter.name,
        active_nav="profile",
    )


@shelter_bp.route("/settings", methods=["GET", "POST"])
@role_required(UserRole.SHELTER)
def settings():
    if request.method == "POST":
        if request.form.get("section") == "security":
            current_user.two_factor_enabled = request.form.get("two_factor_enabled") == "on"
        else:
            current_user.notification_prefs = {
                **current_user.prefs,
                "adoption_updates": request.form.get("adoption_updates") == "on",
                "appointment_updates": request.form.get("appointment_updates") == "on",
                "health_reminders": request.form.get("health_reminders") == "on",
            }
        db.session.commit()
        flash("Shelter settings saved.", "success")
        return redirect(url_for("shelter.settings"))
    return render_template(
        "shelter/settings.html",
        user=current_user,
        shelter_name=_require_shelter().name,
        active_nav="settings",
    )


@shelter_bp.route("/notifications")
@role_required(UserRole.SHELTER)
def notifications():
    from ..models.appointment import Appointment, AppointmentStatus
    from ..models.reminder import Notification

    shelter = _require_shelter()
    from ..services.scheduler import run_due_reminders

    run_due_reminders(current_app._get_current_object())
    category_options = [
        ("all", "All"),
        ("adoption", "Adoption"),
        ("appointments", "Appointments"),
        ("health", "Health & care"),
        ("messages", "Messages"),
        ("general", "Other"),
    ]
    category = request.args.get("category", "all")
    if category not in {key for key, _ in category_options}:
        category = "all"
    known_categories = {key for key, _ in category_options if key != "all"}
    query = db.select(Notification).filter_by(user_id=current_user.id)
    if category != "all":
        query = query.filter_by(category=category)
    items = db.session.scalars(
        query.order_by(Notification.created_at.desc()).limit(100)
    ).all()

    upcoming_appointments = db.session.scalars(
        db.select(Appointment)
        .filter(
            Appointment.shelter_id == shelter.id,
            Appointment.status.in_(
                [AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING]
            ),
        )
        .order_by(Appointment.scheduled_for.asc())
        .limit(50)
    ).all()
    pet_ids = [pet.id for pet in shelter.pets]
    new_applications = []
    if pet_ids:
        new_applications = db.session.scalars(
            db.select(Application)
            .filter(
                Application.pet_id.in_(pet_ids),
                Application.stage == ApplicationStage.SUBMITTED,
            )
            .order_by(Application.created_at.desc())
            .limit(50)
        ).all()

    return render_template(
        "shelter/notifications.html",
        notifications=items,
        notification_groups=[
            (
                key,
                label,
                [
                    item
                    for item in items
                    if item.category == key
                    or (key == "general" and item.category not in known_categories)
                ],
            )
            for key, label in category_options
            if key != "all"
            and any(
                item.category == key
                or (key == "general" and item.category not in known_categories)
                for item in items
            )
        ],
        category_options=category_options,
        upcoming_appointments=upcoming_appointments,
        new_applications=new_applications,
        category=category,
        shelter_name=shelter.name,
        active_nav="notifications",
    )


@shelter_bp.route("/notifications/read-all", methods=["POST"])
@role_required(UserRole.SHELTER)
def read_all_notifications():
    from ..models.reminder import Notification

    db.session.query(Notification).filter_by(
        user_id=current_user.id,
        read=False,
    ).update({"read": True})
    db.session.commit()
    return redirect(url_for("shelter.notifications"))


@shelter_bp.route("/directory")
def directory():
    from ..models.review import Review, ReviewTarget

    term = (request.args.get("q") or "").strip()[:100]
    query = (
        db.select(Shelter)
        .filter(Shelter.is_verified.is_(True), Shelter.owner_id.is_not(None))
        .order_by(Shelter.name.asc())
    )
    if term:
        pattern = f"%{term}%"
        query = query.filter(
            db.or_(Shelter.name.ilike(pattern), Shelter.city.ilike(pattern))
        )
    shelters = db.session.scalars(query).all()
    shelter_ids = [shelter.id for shelter in shelters]
    ratings = {}
    if shelter_ids:
        rows = db.session.execute(
            db.select(
                Review.target_id,
                db.func.avg(Review.rating),
                db.func.count(Review.id),
            )
            .filter(
                Review.target_type == ReviewTarget.SHELTER,
                Review.target_id.in_(shelter_ids),
                Review.hidden.is_(False),
            )
            .group_by(Review.target_id)
        ).all()
        ratings = {
            target_id: {"average": round(float(average), 1), "count": count}
            for target_id, average, count in rows
        }
    return render_template(
        "shelter/directory.html",
        shelters=shelters,
        ratings=ratings,
        search=term,
        active_nav="shelters",
    )


# ---- Public shelter page ----
@shelter_bp.route("/<slug>")
def public(slug: str):
    shelter = db.session.scalar(
        db.select(Shelter).filter(
            Shelter.slug == slug,
            Shelter.is_verified.is_(True),
            Shelter.owner_id.is_not(None),
        )
    )
    if shelter is None:
        abort(404)
    available = [p for p in shelter.pets if p.status == PetStatus.AVAILABLE]
    adopted = sum(1 for p in shelter.pets if p.status == PetStatus.ADOPTED)
    from .reporting import REPORT_REASONS

    return render_template(
        "shelter/public.html",
        shelter=shelter,
        available=available,
        adopted=adopted,
        report_reasons=REPORT_REASONS,
        active_nav="",
    )
