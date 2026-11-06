"""Adoption application wizard + status tracking (Task 13).

A 4-step wizard (About you -> Experience -> References -> Review) with draft
autosave. Each step POST persists answers to the Application's JSON `answers`
so a draft can be resumed. Submitting moves the application into the staged
status timeline shown on the tracking page.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from html import escape
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
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from ..extensions import db
from ..models.application import (
    AdoptionAgreement,
    Application,
    ApplicationStage,
    TIMELINE_STAGES,
)
from ..models.appointment import Appointment, AppointmentKind, AppointmentStatus
from ..models.pet import Pet, PetStatus
from ..models.user import UserRole

adoption_bp = Blueprint("adoption", __name__, url_prefix="/adopt")

TOTAL_STEPS = 4
STEP_TITLES = {
    1: "About you",
    2: "Experience",
    3: "References",
    4: "Review",
}


def _generate_reference() -> str:
    return "PS-" + str(secrets.randbelow(90000) + 10000)


def _get_or_create_draft(pet: Pet) -> Application:
    active_app = db.session.scalar(
        db.select(Application)
        .filter(
            Application.applicant_id == current_user.id,
            Application.pet_id == pet.id,
            Application.returned_at.is_(None),
            Application.stage.notin_([
                ApplicationStage.DRAFT,
                ApplicationStage.COMPLETE,
                ApplicationStage.DECLINED,
            ]),
        )
        .order_by(Application.updated_at.desc(), Application.created_at.desc())
    )
    if active_app is not None:
        return active_app
    app_row = db.session.scalar(
        db.select(Application).filter_by(
            applicant_id=current_user.id,
            pet_id=pet.id,
            stage=ApplicationStage.DRAFT,
        )
    )
    if app_row is None:
        app_row = Application(
            reference=_generate_reference(),
            applicant_id=current_user.id,
            pet_id=pet.id,
            stage=ApplicationStage.DRAFT,
            answers={},
            step=1,
        )
        db.session.add(app_row)
        db.session.commit()
    return app_row


@adoption_bp.route("/start/<int:pet_id>")
@login_required
def start(pet_id: int):
    pet = db.session.get(Pet, pet_id)
    if pet is None or pet.status not in (PetStatus.AVAILABLE, PetStatus.RESERVED):
        abort(404)
    app_row = _get_or_create_draft(pet)
    if app_row.stage == ApplicationStage.DRAFT:
        return redirect(url_for("adoption.wizard", app_id=app_row.id, step=app_row.step))
    return redirect(url_for("adoption.track", app_id=app_row.id))


@adoption_bp.route("/application/<int:app_id>/step/<int:step>", methods=["GET", "POST"])
@login_required
def wizard(app_id: int, step: int):
    app_row = db.session.get(Application, app_id)
    if app_row is None or app_row.applicant_id != current_user.id:
        abort(404)
    if app_row.stage != ApplicationStage.DRAFT:
        # Already submitted; send to tracking.
        return redirect(url_for("adoption.track", app_id=app_row.id))
    step = max(1, min(step, TOTAL_STEPS))

    if request.method == "POST":
        action = request.form.get("action", "next")
        # Persist this step's fields into the JSON answers (draft autosave).
        answers = dict(app_row.answers or {})
        if step == 2:
            answers.pop("other_pets", None)
        for key in request.form.keys():
            if key == "csrf_token" or key == "action":
                continue
            values = request.form.getlist(key)
            if key == "other_pets":
                answers[key] = ", ".join(values)
            elif len(values) == 1:
                answers[key] = values[0]
            else:
                answers[key] = values
        if step == 1 and action == "next" and not all(
            (answers.get(key) or "").strip()
            for key in ("applicant_name", "applicant_phone", "applicant_address")
        ):
            app_row.answers = answers
            db.session.commit()
            flash("Enter your name, phone number, and address to continue.", "warning")
            return redirect(url_for("adoption.wizard", app_id=app_row.id, step=step))
        app_row.answers = answers
        app_row.step = max(app_row.step, step)
        db.session.commit()

        if action == "save":
            flash("Draft saved. You can finish later.", "info")
            return redirect(url_for("adoption.wizard", app_id=app_row.id, step=step))
        if action == "back":
            return redirect(url_for("adoption.wizard", app_id=app_row.id, step=step - 1))
        if action == "submit" and step == TOTAL_STEPS:
            missing_contact = not all(
                (answers.get(key) or "").strip()
                for key in ("applicant_name", "applicant_phone", "applicant_address")
            )
            try:
                current_pets_count = int(answers.get("current_pets_count", ""))
                valid_pet_count = 0 <= current_pets_count <= 99
            except (TypeError, ValueError):
                valid_pet_count = False
            if missing_contact or not valid_pet_count:
                flash("Complete your contact details and current pet count before submitting.", "warning")
                return redirect(url_for(
                    "adoption.wizard",
                    app_id=app_row.id,
                    step=1 if missing_contact else 2,
                ))
            app_row.stage = ApplicationStage.SUBMITTED
            db.session.commit()
            from ..services.notify import notify

            notify(
                app_row.applicant,
                title=f"Application submitted for {app_row.pet.name}",
                body=f"Your application {app_row.reference} was sent to {app_row.pet.shelter.name}.",
                category="adoption",
                link=url_for("adoption.track", app_id=app_row.id),
            )
            notify(
                app_row.pet.shelter.owner,
                title=f"New application for {app_row.pet.name}",
                body=f"{app_row.applicant.full_name} submitted application {app_row.reference}.",
                category="adoption",
                link=url_for("shelter_requests.detail", app_id=app_row.id),
            )
            db.session.commit()
            flash("Your application has been submitted!", "success")
            return redirect(url_for("adoption.track", app_id=app_row.id))
        # Default: advance to the next step.
        return redirect(url_for("adoption.wizard", app_id=app_row.id, step=step + 1))

    # Record the furthest step reached so drafts resume where the user left off.
    if step > app_row.step:
        app_row.step = step
        db.session.commit()

    return render_template(
        "adoption/wizard.html",
        app_row=app_row,
        pet=app_row.pet,
        step=step,
        total_steps=TOTAL_STEPS,
        step_titles=STEP_TITLES,
        answers=app_row.answers or {},
    )


@adoption_bp.route("/application/<int:app_id>")
@login_required
def track(app_id: int):
    from ..services.scheduler import run_due_reminders
    run_due_reminders(current_app._get_current_object())
    app_row = db.session.get(Application, app_id)
    if app_row is None or app_row.applicant_id != current_user.id:
        abort(404)
    appointment = db.session.scalar(
        db.select(Appointment)
        .filter_by(application_id=app_row.id, kind=AppointmentKind.HOME_VISIT)
        .filter(Appointment.status != AppointmentStatus.CANCELLED)
        .order_by(Appointment.scheduled_for.desc())
    )
    welcome_home = db.session.scalar(
        db.select(Appointment)
        .filter_by(application_id=app_row.id, kind=AppointmentKind.PICKUP)
        .filter(Appointment.status != AppointmentStatus.CANCELLED)
        .order_by(Appointment.scheduled_for.desc())
    )
    return render_template(
        "adoption/track.html",
        app_row=app_row,
        pet=app_row.pet,
        appointment=appointment,
        welcome_home=welcome_home,
        shelter_user_id=app_row.pet.shelter.owner_id,
        timeline=TIMELINE_STAGES,
        active_nav="applications",
    )


@adoption_bp.route("/application/<int:app_id>/cancel", methods=["POST"])
@login_required
def cancel_application(app_id: int):
    app_row = db.session.get(Application, app_id)
    if app_row is None or app_row.applicant_id != current_user.id:
        abort(404)
    if app_row.stage in (
        ApplicationStage.DRAFT,
        ApplicationStage.COMPLETE,
        ApplicationStage.DECLINED,
    ):
        flash("This adoption application can no longer be cancelled.", "warning")
        return redirect(url_for("adopter.adoptions", tab="cancelled"))

    app_row.stage = ApplicationStage.DECLINED
    app_row.applicant_cancelled = True

    linked_appointments = db.session.scalars(
        db.select(Appointment)
        .filter_by(application_id=app_row.id)
        .filter(Appointment.status != AppointmentStatus.CANCELLED)
    ).all()
    for appointment in linked_appointments:
        appointment.status = AppointmentStatus.CANCELLED

    if app_row.pet.status == PetStatus.RESERVED:
        app_row.pet.publish()

    db.session.commit()

    from ..services.notify import notify

    notify(
        current_user,
        title=f"Adoption cancelled for {app_row.pet.name}",
        body=f"Application {app_row.reference} was cancelled by you.",
        category="adoption",
        link=url_for("adopter.adoptions", tab="cancelled"),
    )
    if app_row.pet.shelter.owner:
        notify(
            app_row.pet.shelter.owner,
            title=f"Adoption cancelled for {app_row.pet.name}",
            body=f"{current_user.full_name} cancelled application {app_row.reference}.",
            category="adoption",
            link=url_for("shelter_requests.detail", app_id=app_row.id),
        )
    db.session.commit()

    flash(f"Adoption cancelled for {app_row.pet.name}.", "success")
    return redirect(url_for("adopter.adoptions", tab="cancelled"))


@adoption_bp.route("/application/<int:app_id>/visit/reschedule", methods=["POST"])
@login_required
def reschedule_visit(app_id: int):
    app_row = db.session.get(Application, app_id)
    if app_row is None or app_row.applicant_id != current_user.id:
        abort(404)
    if app_row.stage != ApplicationStage.HOME_VISIT:
        flash("A home visit can only be rescheduled while it is in progress.", "warning")
        return redirect(url_for("adoption.track", app_id=app_row.id))

    requested = request.form.get("scheduled_for", "")
    try:
        scheduled_for = datetime.fromisoformat(requested)
    except ValueError:
        flash("Choose a valid date and time for the visit.", "warning")
        return redirect(url_for("adoption.track", app_id=app_row.id))
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
    if scheduled_for <= datetime.now(timezone.utc):
        flash("Choose a future date and time for the visit.", "warning")
        return redirect(url_for("adoption.track", app_id=app_row.id))

    visit = db.session.scalar(
        db.select(Appointment)
        .filter_by(application_id=app_row.id, kind=AppointmentKind.HOME_VISIT)
        .filter(Appointment.status != AppointmentStatus.CANCELLED)
        .order_by(Appointment.scheduled_for.desc())
    )
    if visit and visit.status in (
        AppointmentStatus.CHECKED_IN,
        AppointmentStatus.COMPLETED,
    ):
        flash("This home visit has already taken place and cannot be rescheduled.", "warning")
        return redirect(url_for("adoption.track", app_id=app_row.id))
    if visit is None:
        visit = Appointment(
            application_id=app_row.id,
            kind=AppointmentKind.HOME_VISIT,
            shelter_id=app_row.pet.shelter_id,
            user_id=current_user.id,
            pet_id=app_row.pet_id,
            location=None,
        )
        db.session.add(visit)
    visit.scheduled_for = scheduled_for
    visit.status = AppointmentStatus.PENDING
    visit.adopter_confirmed = False
    db.session.commit()
    from ..services.notify import notify

    notify(
        app_row.pet.shelter.owner,
        title=f"Home visit reschedule requested for {app_row.pet.name}",
        body=scheduled_for.strftime("%d %b %Y at %I:%M %p"),
        category="appointments",
        link=url_for("shelter_requests.detail", app_id=app_row.id),
    )
    db.session.commit()
    flash("Your visit reschedule request was sent to the shelter.", "success")
    return redirect(url_for("adoption.track", app_id=app_row.id))


@adoption_bp.route("/application/<int:app_id>/visit/confirm", methods=["POST"])
@login_required
def confirm_visit(app_id: int):
    app_row = db.session.get(Application, app_id)
    if app_row is None or app_row.applicant_id != current_user.id:
        abort(404)
    if app_row.stage != ApplicationStage.HOME_VISIT:
        flash("A visit can only be confirmed while it is being scheduled.", "warning")
        return redirect(url_for("adoption.track", app_id=app_row.id))

    visit = db.session.scalar(
        db.select(Appointment)
        .filter_by(
            application_id=app_row.id,
            kind=AppointmentKind.HOME_VISIT,
        )
        .filter(Appointment.status != AppointmentStatus.CANCELLED)
        .order_by(Appointment.scheduled_for.desc())
    )
    if visit is None or visit.status != AppointmentStatus.CONFIRMED:
        flash("The shelter must confirm a visit time before you can confirm availability.", "warning")
        return redirect(url_for("adoption.track", app_id=app_row.id))
    scheduled_for = visit.scheduled_for
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
    if scheduled_for <= datetime.now(timezone.utc):
        flash("This visit time has passed. Please contact the shelter to arrange another time.", "warning")
        return redirect(url_for("adoption.track", app_id=app_row.id))
    if visit.adopter_confirmed:
        flash("You have already confirmed that you are available for this visit.", "info")
        return redirect(url_for("adoption.track", app_id=app_row.id))

    visit.adopter_confirmed = True
    db.session.commit()
    from ..services.notify import notify

    notify(
        app_row.pet.shelter.owner,
        title=f"Adopter confirmed home visit for {app_row.pet.name}",
        body=(
            f"{app_row.applicant.full_name} is available on "
            f"{scheduled_for.strftime('%d %b %Y at %I:%M %p')}."
        ),
        category="appointments",
        link=url_for("shelter_requests.detail", app_id=app_row.id),
    )
    db.session.commit()
    flash("Your availability has been shared with the shelter.", "success")
    return redirect(url_for("adoption.track", app_id=app_row.id))


@adoption_bp.route("/application/<int:app_id>/agreement/sign", methods=["POST"])
@login_required
def sign_agreement(app_id: int):
    app_row = db.session.get(Application, app_id)
    if app_row is None or app_row.applicant_id != current_user.id:
        abort(404)
    agreement = app_row.agreement
    if (
        app_row.stage != ApplicationStage.AGREEMENT
        or agreement is None
        or not agreement.shelter_signature
    ):
        abort(404)
    if agreement.adopter_signature:
        flash("This agreement has already been signed.", "info")
        return redirect(url_for("adoption.track", app_id=app_row.id))
    signature = (request.form.get("signature") or "").strip()
    if not signature or len(signature) > 120:
        flash("Enter your full name to sign the adoption agreement.", "warning")
        return redirect(url_for("adoption.track", app_id=app_row.id))
    agreement.adopter_signature = signature
    agreement.adopter_signed_at = datetime.now(timezone.utc)
    db.session.commit()
    from ..services.notify import notify

    notify(
        app_row.pet.shelter.owner,
        title=f"Agreement signed for {app_row.pet.name}",
        body=f"{current_user.full_name} signed the adoption agreement.",
        category="adoption",
        link=url_for("shelter_requests.detail", app_id=app_row.id),
    )
    db.session.commit()
    flash("Your signature has been saved. You can now download the signed agreement.", "success")
    return redirect(url_for("adoption.track", app_id=app_row.id))


@adoption_bp.route("/application/<int:app_id>/agreement/download")
@login_required
def download_agreement(app_id: int):
    app_row = db.session.get(Application, app_id)
    is_applicant = app_row is not None and app_row.applicant_id == current_user.id
    is_shelter = (
        app_row is not None
        and current_user.role == UserRole.SHELTER
        and app_row.pet.shelter.owner_id == current_user.id
    )
    if app_row is None or not (is_applicant or is_shelter):
        abort(404)
    agreement = app_row.agreement
    if agreement is None:
        abort(404)
    source_path = Path(current_app.instance_path) / "agreements" / agreement.file_name
    if not source_path.is_file():
        abort(404)
    if not agreement.is_fully_signed:
        return send_file(
            source_path,
            mimetype="application/pdf",
            as_attachment=request.args.get("view") != "1",
            download_name=agreement.original_filename,
        )

    from pypdf import PdfReader, PdfWriter
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    signature_page = BytesIO()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        signature_page,
        pagesize=letter,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )
    signed_at = agreement.adopter_signed_at
    signed_at_text = (
        signed_at.strftime("%d %B %Y %H:%M UTC") if signed_at else "—"
    )
    story = [
        Paragraph("PetShip adoption agreement — signatures", styles["Title"]),
        Spacer(1, 0.3 * inch),
        Paragraph(
            f"Pet: {escape(app_row.pet.name)} · Application: {escape(app_row.reference)}",
            styles["BodyText"],
        ),
        Paragraph(
            f"Uploaded document: {escape(agreement.original_filename)}",
            styles["BodyText"],
        ),
        Spacer(1, 0.4 * inch),
    ]
    signature_table = Table(
        [
            ["Shelter representative", "Adopter"],
            [
                escape(agreement.shelter_signature or ""),
                escape(agreement.adopter_signature or ""),
            ],
            [
                agreement.shelter_signed_at.strftime("%d %B %Y %H:%M UTC")
                if agreement.shelter_signed_at
                else "—",
                signed_at_text,
            ],
        ],
        colWidths=[3 * inch, 3 * inch],
    )
    signature_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(signature_table)
    doc.build(story)

    writer = PdfWriter()
    writer.append(PdfReader(str(source_path)))
    writer.append(PdfReader(signature_page))
    signed_pdf = BytesIO()
    writer.write(signed_pdf)
    signed_pdf.seek(0)
    return send_file(
        signed_pdf,
        mimetype="application/pdf",
        as_attachment=request.args.get("view") != "1",
        download_name=f"petship-agreement-{app_row.reference}-signed.pdf",
    )


@adoption_bp.route("/applications")
@login_required
def my_applications():
    apps = db.session.scalars(
        db.select(Application)
        .filter(
            Application.applicant_id == current_user.id,
            Application.stage != ApplicationStage.DRAFT,
        )
        .order_by(Application.created_at.desc())
    ).all()
    return render_template(
        "adoption/list.html", applications=apps, active_nav="adoptions"
    )
