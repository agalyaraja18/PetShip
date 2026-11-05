"""Veterinary directory, vet detail, and vet profile management (Task 18)."""
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
from ..models.user import UserRole
from ..models.vet import SPECIALTY_OPTIONS, VetProfile
from ..security import role_required
from ..services.storage import save_image

vet_bp = Blueprint("vet", __name__, url_prefix="/vets")


def current_vet_profile() -> VetProfile | None:
    if not current_user.is_authenticated:
        return None
    profiles = getattr(current_user, "vet_profile", None) or []
    return profiles[0] if profiles else None


def _require_vet_profile() -> VetProfile:
    profile = current_vet_profile()
    if profile is None:
        profile = VetProfile(
            user_id=current_user.id,
            display_name=f"Dr. {current_user.full_name}",
            slug=f"vet-{current_user.id}",
        )
        db.session.add(profile)
        db.session.commit()
    return profile


# ---- Public directory ----
@vet_bp.route("/")
def directory():
    q = (request.args.get("q") or "").strip().lower()
    specialty = request.args.get("specialty")
    video_only = request.args.get("video") == "1"

    query = db.select(VetProfile).filter_by(is_verified=True)
    vets = db.session.scalars(query.order_by(VetProfile.rating.desc().nullslast())).all()

    if q:
        vets = [
            v for v in vets
            if q in v.display_name.lower()
            or q in (v.clinic_name or "").lower()
            or any(q in s.lower() for s in (v.specialties or []))
        ]
    if specialty and specialty != "All":
        vets = [v for v in vets if specialty in (v.specialties or [])]
    if video_only:
        vets = [v for v in vets if v.offers_video]

    return render_template(
        "vet/directory.html",
        vets=vets,
        specialties=["All"] + SPECIALTY_OPTIONS,
        active_specialty=specialty or "All",
        q=q,
        active_nav="vets",
    )


@vet_bp.route("/<slug>")
def detail(slug: str):
    profile = db.session.scalar(db.select(VetProfile).filter_by(slug=slug))
    if profile is None:
        abort(404)
    from .reporting import REPORT_REASONS

    return render_template(
        "vet/detail.html",
        vet=profile,
        report_reasons=REPORT_REASONS,
        active_nav="vets",
    )


# ---- Vet's own profile management ----
@vet_bp.route("/manage/profile", methods=["GET", "POST"])
@role_required(UserRole.VET)
def manage_profile():
    profile = _require_vet_profile()
    editing = request.args.get("edit") == "1"
    if request.method == "POST":
        if not editing:
            abort(400)
        profile.display_name = (request.form.get("display_name") or profile.display_name).strip()
        profile.qualifications = (request.form.get("qualifications") or "").strip() or None
        profile.clinic_name = (request.form.get("clinic_name") or "").strip() or None
        profile.clinic_address = (request.form.get("clinic_address") or "").strip() or None
        profile.city = (request.form.get("city") or "").strip() or None
        profile.experience_years = _int(request.form.get("experience_years"))
        profile.bio = (request.form.get("bio") or "").strip() or None
        profile.specialties = [
            s for s in request.form.getlist("specialties") if s in SPECIALTY_OPTIONS
        ]
        profile.languages = [
            s.strip() for s in (request.form.get("languages") or "").split(",") if s.strip()
        ]
        profile.consult_fee = _float(request.form.get("consult_fee"))
        profile.video_fee = _float(request.form.get("video_fee"))
        profile.offers_video = request.form.get("offers_video") == "on"
        profile.offers_home_visits = request.form.get("offers_home_visits") == "on"
        profile.offers_emergency = request.form.get("offers_emergency") == "on"

        photo = request.files.get("photo")
        if photo and photo.filename:
            url = save_image(photo, folder="vets")
            if url:
                profile.photo_url = url

        db.session.commit()
        flash("Profile saved.", "success")
        return redirect(url_for("vet.manage_profile"))

    return render_template(
        "vet/profile_manage.html",
        vet=profile,
        specialties=SPECIALTY_OPTIONS,
        clinic_name=profile.clinic_name or "CareVet Clinic",
        editing=editing,
        active_nav="profile",
    )


def _int(val):
    try:
        return int(val) if val else None
    except (TypeError, ValueError):
        return None


def _float(val):
    try:
        return float(val) if val else None
    except (TypeError, ValueError):
        return None
