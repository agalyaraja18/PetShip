"""Shelter adoption request management + applicant details (Task 16)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

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
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models.application import AdoptionAgreement, Application, ApplicationStage
from ..models.appointment import Appointment, AppointmentKind, AppointmentStatus
from ..models.health import OwnedPet
from ..models.user import UserRole
from ..security import role_required
from .shelter import current_shelter

shelter_requests_bp = Blueprint(
    "shelter_requests", __name__, url_prefix="/shelter/requests"
)


def _match_score(application: Application) -> int:
    """A simple, deterministic applicant/pet fit score (0-100).

    A transparent heuristic until the AI scoring in Task 26: rewards matching
    lifestyle tags, relevant home type, and completeness of answers.
    """
    pet = application.pet
    user = application.applicant
    answers = application.answers or {}
    score = 60  # base

    user_tags = set(user.tags or [])
    good_with = set(pet.good_with or [])

    if "kids" in good_with and "Has kids" in user_tags:
        score += 10
    if answers.get("home_type") == "Apartment" and pet.size and pet.size.value == "small":
        score += 8
    if answers.get("ownership", "").startswith("Own"):
        score += 8
    if answers.get("prior_experience"):
        score += 8
    if answers.get("ref_name"):
        score += 6
    return max(0, min(100, score))


def _owned_application_or_404(app_id: int) -> Application:
    shelter = current_shelter()
    application = db.session.get(Application, app_id)
    if application is None or shelter is None:
        abort(404)
    if application.pet is None or application.pet.shelter_id != shelter.id:
        abort(404)
    return application


@shelter_requests_bp.route("")
@role_required(UserRole.SHELTER)
def index():
    from ..services.scheduler import run_due_reminders
    run_due_reminders(current_app._get_current_object())
    from .shelter import _require_shelter

    shelter = _require_shelter()
    pet_ids = [p.id for p in shelter.pets]
    status = request.args.get("status", "new")
    if status not in {"new", "review", "home_visit", "approved", "adopted", "declined"}:
        status = "new"

    applications = []
    status_counts = {
        "new": 0,
        "review": 0,
        "home_visit": 0,
        "approved": 0,
        "adopted": 0,
        "declined": 0,
    }
    if pet_ids:
        stage_counts = db.session.execute(
            db.select(Application.stage, db.func.count(Application.id))
            .filter(
                Application.pet_id.in_(pet_ids),
                Application.stage != ApplicationStage.DRAFT,
            )
            .group_by(Application.stage)
        ).all()
        counts_by_stage = {stage: count for stage, count in stage_counts}
        status_counts.update({
            "new": counts_by_stage.get(ApplicationStage.SUBMITTED, 0),
            "review": (
                counts_by_stage.get(ApplicationStage.REVIEW, 0)
                + counts_by_stage.get(ApplicationStage.CONFIRMED, 0)
            ),
            "home_visit": counts_by_stage.get(ApplicationStage.HOME_VISIT, 0),
            "approved": counts_by_stage.get(ApplicationStage.AGREEMENT, 0),
            "adopted": counts_by_stage.get(ApplicationStage.COMPLETE, 0),
            "declined": counts_by_stage.get(ApplicationStage.DECLINED, 0),
        })
        query = db.select(Application).filter(
            Application.pet_id.in_(pet_ids),
            Application.stage != ApplicationStage.DRAFT,
        )
        if status == "new":
            query = query.filter(Application.stage == ApplicationStage.SUBMITTED)
        elif status == "review":
            query = query.filter(
                Application.stage.in_(
                    [ApplicationStage.REVIEW, ApplicationStage.CONFIRMED]
                )
            )
        elif status == "home_visit":
            query = query.filter(Application.stage == ApplicationStage.HOME_VISIT)
        elif status == "approved":
            query = query.filter(Application.stage == ApplicationStage.AGREEMENT)
        elif status == "adopted":
            query = query.filter(Application.stage == ApplicationStage.COMPLETE)
        elif status == "declined":
            query = query.filter(Application.stage == ApplicationStage.DECLINED)
        applications = db.session.scalars(
            query.order_by(Application.created_at.desc())
        ).all()

    scored = sorted(
        ((a, _match_score(a)) for a in applications),
        key=lambda t: t[1],
        reverse=True,
    )
    return render_template(
        "shelter/requests.html",
        scored=scored,
        status=status,
        status_counts=status_counts,
        shelter_name=shelter.name,
        active_nav="requests",
    )


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_local_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    browser_timezone = request.form.get("browser_timezone", "Asia/Kolkata")
    try:
        local_timezone = ZoneInfo(browser_timezone)
    except Exception:
        local_timezone = ZoneInfo("Asia/Kolkata")
    return parsed.replace(tzinfo=local_timezone).astimezone(timezone.utc)


@shelter_requests_bp.route("/<int:app_id>")
@role_required(UserRole.SHELTER)
def detail(app_id: int):
    from ..services.scheduler import run_due_reminders
    run_due_reminders(current_app._get_current_object())
    application = _owned_application_or_404(app_id)
    home_visit = db.session.scalar(
        db.select(Appointment)
        .filter_by(application_id=application.id, kind=AppointmentKind.HOME_VISIT)
        .order_by(Appointment.scheduled_for.desc())
    )
    welcome_home = db.session.scalar(
        db.select(Appointment)
        .filter_by(
            application_id=application.id,
            kind=AppointmentKind.PICKUP,
        )
        .filter(Appointment.status != AppointmentStatus.CANCELLED)
        .order_by(Appointment.scheduled_for.desc())
    )
    return render_template(
        "shelter/applicant.html",
        application=application,
        home_visit=home_visit,
        welcome_home=welcome_home,
        agreement=application.agreement,
        score=_match_score(application),
        shelter_name=application.pet.shelter.name,
        active_nav="requests",
    )


@shelter_requests_bp.route("/<int:app_id>/action", methods=["POST"])
@role_required(UserRole.SHELTER)
def action(app_id: int):
    application = _owned_application_or_404(app_id)
    what = request.form.get("action")
    welcome_home_rescheduled = False

    if what == "review" and application.stage == ApplicationStage.SUBMITTED:
        application.stage = ApplicationStage.REVIEW
        flash("Application moved to review.", "success")
    elif what == "confirm" and application.stage == ApplicationStage.REVIEW:
        application.stage = ApplicationStage.CONFIRMED
        flash("Application confirmed.", "success")
    elif what == "home_visit" and application.stage == ApplicationStage.CONFIRMED:
        requested = request.form.get("scheduled_for", "")
        scheduled_for = _parse_local_datetime(requested)
        if scheduled_for is None:
            flash("Choose a valid date and time for the home visit.", "warning")
            return redirect(url_for("shelter_requests.detail", app_id=application.id))
        if scheduled_for <= datetime.now(timezone.utc):
            flash("Choose a future date and time for the home visit.", "warning")
            return redirect(url_for("shelter_requests.detail", app_id=application.id))

        application.stage = ApplicationStage.HOME_VISIT
        application.home_visit_note = (request.form.get("note") or "").strip() or None
        appointment = Appointment(
            application_id=application.id,
            kind=AppointmentKind.HOME_VISIT,
            status=AppointmentStatus.CONFIRMED,
            scheduled_for=scheduled_for,
            shelter_id=application.pet.shelter_id,
            user_id=application.applicant_id,
            pet_id=application.pet_id,
            location=(request.form.get("location") or "").strip() or None,
            note=application.home_visit_note,
        )
        db.session.add(appointment)
        flash("Home visit scheduled.", "success")
    elif what == "agreement" and application.stage == ApplicationStage.HOME_VISIT:
        application.stage = ApplicationStage.AGREEMENT
        flash("Adoption approved. You can now schedule the welcome-home date and time.", "success")
    elif what == "schedule_welcome_home" and application.stage == ApplicationStage.AGREEMENT:
        requested = request.form.get("scheduled_for", "")
        if not requested:
            flash("Choose a welcome-home date and time.", "warning")
            return redirect(url_for("shelter_requests.detail", app_id=application.id))
        scheduled_for = _parse_local_datetime(requested)
        if scheduled_for is None:
            flash("Choose a valid welcome-home date and time.", "warning")
            return redirect(url_for("shelter_requests.detail", app_id=application.id))
        if scheduled_for <= datetime.now(timezone.utc):
            flash("Choose a future welcome-home date and time.", "warning")
            return redirect(url_for("shelter_requests.detail", app_id=application.id))
        pickup = db.session.scalar(
            db.select(Appointment)
            .filter_by(application_id=application.id, kind=AppointmentKind.PICKUP)
            .order_by(Appointment.scheduled_for.desc())
        )
        welcome_home_rescheduled = (
            pickup is not None and pickup.status != AppointmentStatus.CANCELLED
        )
        if pickup is None:
            pickup = Appointment(
                application_id=application.id,
                kind=AppointmentKind.PICKUP,
                shelter_id=application.pet.shelter_id,
                user_id=application.applicant_id,
                pet_id=application.pet_id,
                note="Welcome-home adoption date",
            )
            db.session.add(pickup)
        pickup.status = AppointmentStatus.CONFIRMED
        pickup.scheduled_for = scheduled_for
        pickup.location = (
            (request.form.get("location") or "").strip()
            or pickup.location
            or application.applicant.city
        )
        pickup.adopter_confirmed = False
        flash(
            "Welcome-home date and time updated and shared with the adopter."
            if welcome_home_rescheduled
            else "Welcome-home date and time scheduled and shared with the adopter.",
            "success",
        )
    elif what == "complete" and application.stage == ApplicationStage.AGREEMENT:
        pickup = db.session.scalar(
            db.select(Appointment)
            .filter_by(application_id=application.id, kind=AppointmentKind.PICKUP)
            .filter(Appointment.status != AppointmentStatus.CANCELLED)
            .order_by(Appointment.scheduled_for.desc())
        )
        legacy_signed_agreement = application.agreement is not None and application.agreement.is_fully_signed
        if (
            pickup is None
            and not legacy_signed_agreement
        ):
            flash("Schedule a welcome-home date and approve the adoption before completing it.", "warning")
            return redirect(url_for("shelter_requests.detail", app_id=application.id))
        application.stage = ApplicationStage.COMPLETE
        application.adopted_at = datetime.now(timezone.utc)
        if pickup is not None:
            pickup.status = AppointmentStatus.COMPLETED
        application.pet.mark_adopted()
        if application.owned_pet is None:
            listed_pet = application.pet
            db.session.add(
                OwnedPet(
                    owner_id=application.applicant_id,
                    application_id=application.id,
                    name=listed_pet.name,
                    species=listed_pet.species.label if listed_pet.species else None,
                    breed=listed_pet.breed,
                    sex=listed_pet.sex.label if listed_pet.sex else None,
                    weight_kg=listed_pet.weight_kg,
                    photo_url=listed_pet.primary_photo,
                    personality_tags=list(listed_pet.personality_tags or []),
                    adopted_on=application.adopted_at.date(),
                )
            )
        # Schedule the standard post-adoption follow-up milestones.
        from .shelter_ops import create_followups_for

        create_followups_for(application)
        flash(f"{application.pet.name} adopted! 🎉", "success")
    elif what == "decline" and application.stage not in (
        ApplicationStage.COMPLETE,
        ApplicationStage.DECLINED,
    ):
        application.stage = ApplicationStage.DECLINED
        application.applicant_cancelled = False
        flash("Application declined.", "info")
    else:
        flash("That application step is not available at this stage.", "warning")
        return redirect(url_for("shelter_requests.detail", app_id=application.id))
    db.session.commit()

    # Notify the applicant of the status change (respects their preferences,
    # emails them too). Skipped silently if they've opted out of adoption updates.
    from ..services.notify import notify

    notify(
        application.applicant,
        title=f"Update on your application for {application.pet.name}",
        body=f"Status: {application.stage.label}.",
        category="adoption",
        link=url_for("adoption.track", app_id=application.id),
        email=True,
        email_subject=f"PetShip: your application for {application.pet.name}",
    )
    if what == "schedule_welcome_home":
        pickup = db.session.scalar(
            db.select(Appointment)
            .filter_by(application_id=application.id, kind=AppointmentKind.PICKUP)
            .order_by(Appointment.scheduled_for.desc())
        )
        if pickup is not None:
            schedule_action = (
                "rescheduled" if welcome_home_rescheduled else "set"
            )
            notify(
                application.applicant,
                title=f"Welcome-home date {schedule_action} for {application.pet.name}",
                body=(
                    f"{'Updated to' if welcome_home_rescheduled else 'Scheduled for'} "
                    f"{pickup.scheduled_for.strftime('%d %b %Y at %I:%M %p')}"
                    + (f" · {pickup.location}" if pickup.location else "")
                ),
                category="adoption",
                link=url_for("adoption.track", app_id=application.id),
                email=True,
                email_subject=(
                    f"PetShip: welcome-home date {schedule_action} "
                    f"for {application.pet.name}"
                ),
            )
    if what == "home_visit":
        appointment = db.session.scalar(
            db.select(Appointment)
            .filter_by(application_id=application.id, kind=AppointmentKind.HOME_VISIT)
            .order_by(Appointment.id.desc())
        )
        notify(
            application.applicant,
            title=f"Home visit scheduled for {application.pet.name}",
            body=(
                f"{appointment.scheduled_for.strftime('%d %b %Y at %I:%M %p')}"
                + (f" · {appointment.location}" if appointment.location else "")
            ),
            category="appointments",
            link=url_for("adoption.track", app_id=application.id),
        )
    db.session.commit()

    return redirect(url_for("shelter_requests.detail", app_id=application.id))


@shelter_requests_bp.route("/<int:app_id>/agreement", methods=["POST"])
@role_required(UserRole.SHELTER)
def share_agreement(app_id: int):
    application = _owned_application_or_404(app_id)
    if application.stage != ApplicationStage.AGREEMENT:
        flash("The adoption agreement can be shared after the home visit is complete.", "warning")
        return redirect(url_for("shelter_requests.detail", app_id=application.id))

    signature = (request.form.get("signature") or "").strip()
    upload = request.files.get("agreement")
    if not signature or len(signature) > 120:
        flash("Enter the shelter representative's full name to sign the agreement.", "warning")
        return redirect(url_for("shelter_requests.detail", app_id=application.id))
    if upload is None or not upload.filename:
        flash("Choose the adoption agreement PDF to share.", "warning")
        return redirect(url_for("shelter_requests.detail", app_id=application.id))
    original_filename = secure_filename(upload.filename)
    if not original_filename.lower().endswith(".pdf"):
        flash("The agreement must be a PDF file.", "warning")
        return redirect(url_for("shelter_requests.detail", app_id=application.id))
    if application.agreement and application.agreement.adopter_signature:
        flash("An agreement cannot be replaced after the adopter has signed it.", "warning")
        return redirect(url_for("shelter_requests.detail", app_id=application.id))

    pdf_data = upload.read()
    try:
        reader = PdfReader(BytesIO(pdf_data), strict=True)
        if not reader.pages:
            raise PdfReadError("PDF has no pages")
    except (PdfReadError, EOFError, ValueError):
        flash("The uploaded file is not a readable PDF.", "warning")
        return redirect(url_for("shelter_requests.detail", app_id=application.id))

    agreement_dir = Path(current_app.instance_path) / "agreements"
    agreement_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{uuid.uuid4().hex}.pdf"
    (agreement_dir / file_name).write_bytes(pdf_data)

    agreement = application.agreement
    if agreement is None:
        agreement = AdoptionAgreement(
            application_id=application.id,
            file_name=file_name,
            original_filename=original_filename,
        )
        db.session.add(agreement)
    else:
        agreement.file_name = file_name
        agreement.original_filename = original_filename
    agreement.shelter_signature = signature
    agreement.shelter_signed_at = datetime.now(timezone.utc)
    application.stage = ApplicationStage.AGREEMENT
    db.session.commit()
    from ..services.notify import notify

    notify(
        application.applicant,
        title=f"Adoption agreement for {application.pet.name}",
        body="The shelter shared an agreement for you to review and sign.",
        category="adoption",
        link=url_for("adoption.track", app_id=application.id),
    )
    db.session.commit()
    flash("The signed agreement has been shared with the adopter.", "success")
    return redirect(url_for("shelter_requests.detail", app_id=application.id))
