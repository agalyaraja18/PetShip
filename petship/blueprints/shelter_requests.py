"""Shelter adoption request management + applicant details (Task 16)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

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
    from .shelter import _require_shelter

    shelter = _require_shelter()
    pet_ids = [p.id for p in shelter.pets]
    status = request.args.get("status", "open")

    applications = []
    if pet_ids:
        query = db.select(Application).filter(
            Application.pet_id.in_(pet_ids),
            Application.stage != ApplicationStage.DRAFT,
        )
        if status == "open":
            query = query.filter(
                Application.stage.notin_(
                    [ApplicationStage.COMPLETE, ApplicationStage.DECLINED]
                )
            )
        elif status != "all":
            query = query.filter(Application.stage == ApplicationStage(status))
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
        shelter_name=shelter.name,
        active_nav="requests",
    )


@shelter_requests_bp.route("/<int:app_id>")
@role_required(UserRole.SHELTER)
def detail(app_id: int):
    application = _owned_application_or_404(app_id)
    home_visit = db.session.scalar(
        db.select(Appointment)
        .filter_by(application_id=application.id, kind=AppointmentKind.HOME_VISIT)
        .order_by(Appointment.scheduled_for.desc())
    )
    return render_template(
        "shelter/applicant.html",
        application=application,
        home_visit=home_visit,
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

    if what == "review" and application.stage == ApplicationStage.SUBMITTED:
        application.stage = ApplicationStage.REVIEW
        flash("Application moved to review.", "success")
    elif what == "confirm" and application.stage == ApplicationStage.REVIEW:
        application.stage = ApplicationStage.CONFIRMED
        flash("Application confirmed.", "success")
    elif what == "home_visit" and application.stage == ApplicationStage.CONFIRMED:
        requested = request.form.get("scheduled_for", "")
        try:
            scheduled_for = datetime.fromisoformat(requested)
        except ValueError:
            flash("Choose a valid date and time for the home visit.", "warning")
            return redirect(url_for("shelter_requests.detail", app_id=application.id))
        if scheduled_for.tzinfo is None:
            scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
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
        visit = db.session.scalar(
            db.select(Appointment)
            .filter_by(
                application_id=application.id,
                kind=AppointmentKind.HOME_VISIT,
                status=AppointmentStatus.COMPLETED,
            )
        )
        if visit is None:
            flash("Mark the home visit complete before moving to the agreement.", "warning")
            return redirect(url_for("shelter_requests.detail", app_id=application.id))
        application.stage = ApplicationStage.AGREEMENT
        flash("Moved to adoption agreement.", "success")
    elif what == "complete" and application.stage == ApplicationStage.AGREEMENT:
        if application.agreement is None or not application.agreement.is_fully_signed:
            flash("Both parties must sign the adoption agreement before completing the adoption.", "warning")
            return redirect(url_for("shelter_requests.detail", app_id=application.id))
        application.stage = ApplicationStage.COMPLETE
        application.adopted_at = datetime.now(timezone.utc)
        application.pet.mark_adopted()
        # Schedule the standard post-adoption follow-up milestones.
        from .shelter_ops import create_followups_for

        create_followups_for(application)
        flash(f"{application.pet.name} adopted! 🎉", "success")
    elif what == "decline" and application.stage not in (
        ApplicationStage.COMPLETE,
        ApplicationStage.DECLINED,
    ):
        application.stage = ApplicationStage.DECLINED
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
