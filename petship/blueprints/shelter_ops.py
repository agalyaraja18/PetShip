"""Shelter appointments, reviews, and post-adoption follow-ups (Task 17)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from ..extensions import db
from ..models.application import Application, ApplicationStage, ReturnStatus
from ..models.appointment import Appointment, AppointmentKind, AppointmentStatus
from ..models.review import FollowUp, FollowUpStatus, Review, ReviewTarget
from ..models.user import UserRole
from ..security import role_required
from .shelter import current_shelter, _require_shelter

shelter_ops_bp = Blueprint("shelter_ops", __name__, url_prefix="/shelter")

# Standard post-adoption check-ins.
FOLLOWUP_MILESTONES = [
    ("7 days", 7),
    ("15 days", 15),
    ("30 days", 30),
]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def create_followups_for(application) -> None:
    """Create the standard follow-up schedule for a completed adoption."""
    adopted_at = application.adopted_at or datetime.now(timezone.utc)
    for milestone, days in FOLLOWUP_MILESTONES:
        db.session.add(
            FollowUp(
                application_id=application.id,
                milestone=milestone,
                due_on=adopted_at + timedelta(days=days),
                status=FollowUpStatus.DUE,
            )
        )


# ---- Appointments ----
@shelter_ops_bp.route("/appointments")
@role_required(UserRole.SHELTER)
def appointments():
    shelter = _require_shelter()
    appts = db.session.scalars(
        db.select(Appointment)
        .filter_by(shelter_id=shelter.id)
        .order_by(Appointment.scheduled_for.asc())
    ).all()
    return render_template(
        "shelter/appointments.html",
        appointments=appts,
        AppointmentStatus=AppointmentStatus,
        shelter_name=shelter.name,
        active_nav="appointments",
    )


@shelter_ops_bp.route("/appointments/new", methods=["POST"])
@role_required(UserRole.SHELTER)
def create_appointment():
    shelter = _require_shelter()
    kind = request.form.get("kind", "meet_greet")
    when = request.form.get("scheduled_for")
    try:
        scheduled = datetime.fromisoformat(when) if when else datetime.now(timezone.utc)
    except ValueError:
        scheduled = datetime.now(timezone.utc)
    appt = Appointment(
        kind=AppointmentKind(kind),
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=scheduled,
        shelter_id=shelter.id,
        note=request.form.get("note"),
        location=request.form.get("location"),
    )
    db.session.add(appt)
    db.session.commit()
    flash("Appointment scheduled.", "success")
    return redirect(url_for("shelter_ops.appointments"))


@shelter_ops_bp.route("/appointments/<int:appt_id>/checkin", methods=["POST"])
@role_required(UserRole.SHELTER)
def checkin_appointment(appt_id: int):
    shelter = current_shelter()
    appt = db.session.get(Appointment, appt_id)
    if appt is None or shelter is None or appt.shelter_id != shelter.id:
        abort(404)
    appt.status = AppointmentStatus.CHECKED_IN
    db.session.commit()
    flash("Checked in.", "success")
    return redirect(url_for("shelter_ops.appointments"))


@shelter_ops_bp.route("/appointments/<int:appt_id>/confirm", methods=["POST"])
@role_required(UserRole.SHELTER)
def confirm_appointment(appt_id: int):
    shelter = current_shelter()
    appt = db.session.get(Appointment, appt_id)
    if (
        appt is None
        or shelter is None
        or appt.shelter_id != shelter.id
        or appt.status != AppointmentStatus.PENDING
    ):
        abort(404)
    appt.status = AppointmentStatus.CONFIRMED
    db.session.commit()
    if appt.user_id:
        from ..services.notify import notify

        notify(
            appt.user_id,
            title=f"Home visit confirmed for {appt.pet.name if appt.pet else 'your pet'}",
            body=appt.scheduled_for.strftime("%d %b %Y at %I:%M %p"),
            category="appointments",
            link=(
                url_for("adoption.track", app_id=appt.application_id)
                if appt.application_id
                else url_for("adopter.appointments")
            ),
        )
        db.session.commit()
    flash("Visit time confirmed.", "success")
    return redirect(url_for("shelter_ops.appointments"))


@shelter_ops_bp.route("/appointments/<int:appt_id>/complete-visit", methods=["POST"])
@role_required(UserRole.SHELTER)
def complete_home_visit(appt_id: int):
    shelter = current_shelter()
    appt = db.session.get(Appointment, appt_id)
    if (
        appt is None
        or shelter is None
        or appt.shelter_id != shelter.id
        or appt.application_id is None
        or appt.kind != AppointmentKind.HOME_VISIT
        or appt.status not in (AppointmentStatus.CONFIRMED, AppointmentStatus.CHECKED_IN)
    ):
        abort(404)
    scheduled_for = appt.scheduled_for
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
    if scheduled_for > datetime.now(timezone.utc):
        flash("The visit cannot be completed before its scheduled date and time.", "warning")
        return redirect(url_for("shelter_ops.appointments"))
    appt.status = AppointmentStatus.COMPLETED
    db.session.commit()
    from ..services.notify import notify

    notify(
        appt.user_id,
        title=f"Appointment completed: {appt.kind.label}",
        body=(
            f"Your {appt.kind.label.lower()} scheduled for "
            f"{appt.scheduled_for.strftime('%d %b %Y at %I:%M %p')} has passed."
        ),
        category="appointments",
        link=url_for("adoption.track", app_id=appt.application_id),
    )
    db.session.commit()
    flash("Home visit marked complete.", "success")
    return redirect(url_for("shelter_ops.appointments"))


# ---- Reviews ----
@shelter_ops_bp.route("/reviews")
@role_required(UserRole.SHELTER)
def reviews():
    shelter = _require_shelter()
    items = db.session.scalars(
        db.select(Review)
        .filter_by(target_type=ReviewTarget.SHELTER, target_id=shelter.id)
        .order_by(Review.created_at.desc())
    ).all()
    avg = round(sum(r.rating for r in items) / len(items), 1) if items else 0
    reply_rate = (
        round(100 * sum(1 for r in items if r.reply) / len(items)) if items else 0
    )
    return render_template(
        "shelter/reviews.html",
        reviews=items,
        avg=avg,
        total=len(items),
        reply_rate=reply_rate,
        shelter_name=shelter.name,
        active_nav="reviews",
    )


@shelter_ops_bp.route("/reviews/<int:review_id>/reply", methods=["POST"])
@role_required(UserRole.SHELTER)
def reply_review(review_id: int):
    shelter = current_shelter()
    review = db.session.get(Review, review_id)
    if (
        review is None
        or shelter is None
        or review.target_type != ReviewTarget.SHELTER
        or review.target_id != shelter.id
    ):
        abort(404)
    review.reply = (request.form.get("reply") or "").strip() or None
    db.session.commit()
    flash("Reply posted.", "success")
    return redirect(url_for("shelter_ops.reviews"))


# ---- Follow-ups ----
@shelter_ops_bp.route("/followups")
@role_required(UserRole.SHELTER)
def followups():
    shelter = _require_shelter()
    pet_ids = [p.id for p in shelter.pets]

    items = []
    if pet_ids:
        items = db.session.scalars(
            db.select(FollowUp)
            .join(Application, FollowUp.application_id == Application.id)
            .filter(
                Application.pet_id.in_(pet_ids),
                Application.returned_at.is_(None),
                FollowUp.milestone.in_(("7 days", "15 days", "30 days")),
            )
            .order_by(FollowUp.due_on.asc())
        ).all()

    now = datetime.now(timezone.utc)

    due_soon = [f for f in items if f.status == FollowUpStatus.DUE]
    responses = [f for f in items if f.status != FollowUpStatus.DUE]
    stats = {
        "due_this_week": len(due_soon),
        "overdue": sum(1 for f in items if f.status == FollowUpStatus.DUE and _aware(f.due_on) < now),
        "needs_support": sum(1 for f in items if f.status == FollowUpStatus.NEEDS_SUPPORT),
        "completion": round(
            100 * sum(1 for f in items if f.status == FollowUpStatus.DONE) / len(items)
        ) if items else 0,
    }
    return render_template(
        "shelter/followups.html",
        due_soon=due_soon,
        responses=responses,
        stats=stats,
        shelter_name=shelter.name,
        active_nav="followups",
    )


@shelter_ops_bp.route("/returns")
@role_required(UserRole.SHELTER)
def returns():
    shelter = _require_shelter()
    pet_ids = [pet.id for pet in shelter.pets]
    status_options = [
        (ReturnStatus.SUBMITTED.value, "New"),
        (ReturnStatus.SHELTER_REVIEW.value, "Reviewed"),
        (ReturnStatus.SHELTER_CONFIRMED.value, "Confirmed"),
        (ReturnStatus.RETURN_VISIT.value, "Return visit"),
        (ReturnStatus.RETURNED_SHELTER.value, "Returned"),
    ]
    status = request.args.get("status", ReturnStatus.SUBMITTED.value)
    if status not in {key for key, _ in status_options}:
        status = ReturnStatus.SUBMITTED.value

    status_counts = {key: 0 for key, _ in status_options}
    if pet_ids:
        return_status_counts = db.session.execute(
            db.select(Application.return_status, db.func.count(Application.id))
            .filter(
                Application.pet_id.in_(pet_ids),
                Application.return_status.is_not(None),
            )
            .group_by(Application.return_status)
        ).all()
        counts_by_status = {
            return_status: count for return_status, count in return_status_counts
        }
        status_counts.update({
            key: counts_by_status.get(key, 0)
            for key, _ in status_options
        })

    return_requests = []
    returned_applications = []
    if pet_ids:
        if status != ReturnStatus.RETURNED_SHELTER.value:
            query = db.select(Application).filter(
                Application.pet_id.in_(pet_ids),
                Application.return_status == status,
            )
            return_requests = db.session.scalars(
                query.order_by(Application.return_requested_at.desc())
            ).all()
        else:
            returned_applications = db.session.scalars(
                db.select(Application)
                .filter(
                    Application.pet_id.in_(pet_ids),
                    Application.return_status == ReturnStatus.RETURNED_SHELTER.value,
                )
                .order_by(Application.returned_at.desc())
            ).all()
    return render_template(
        "shelter/returns.html",
        return_requests=return_requests,
        returned_applications=returned_applications,
        status=status,
        status_options=status_options,
        status_counts=status_counts,
        ReturnStatus=ReturnStatus,
        shelter_name=shelter.name,
        active_nav="returns",
    )


@shelter_ops_bp.route("/followups/<int:fu_id>/schedule", methods=["POST"])
@role_required(UserRole.SHELTER)
def schedule_followup(fu_id: int):
    shelter = current_shelter()
    fu = db.session.get(FollowUp, fu_id)
    if (
        fu is None
        or shelter is None
        or fu.application.pet.shelter_id != shelter.id
        or fu.application.returned_at is not None
        or fu.status != FollowUpStatus.DUE
    ):
        abort(404)

    try:
        scheduled_for = datetime.fromisoformat(request.form.get("scheduled_for", ""))
    except ValueError:
        flash("Choose a valid date and time for the check-in.", "warning")
        return redirect(url_for("shelter_ops.followups"))
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
    if scheduled_for <= datetime.now(timezone.utc):
        flash("Choose a future date and time for the check-in.", "warning")
        return redirect(url_for("shelter_ops.followups"))

    milestone_days = {"7 days": 7, "15 days": 15, "30 days": 30}
    offset = milestone_days.get(fu.milestone)
    adopted_at = fu.application.adopted_at
    expected_date = (
        (_aware(adopted_at) + timedelta(days=offset)).astimezone(timezone.utc).date()
        if adopted_at is not None and offset is not None
        else None
    )
    if expected_date is None or scheduled_for.astimezone(timezone.utc).date() != expected_date:
        flash("Keep the check-in on its scheduled adoption milestone date.", "warning")
        return redirect(url_for("shelter_ops.followups"))

    fu.due_on = scheduled_for
    db.session.commit()
    from ..services.notify import notify

    notify(
        fu.application.applicant,
        title=f"{fu.milestone} adoption check-in scheduled",
        body=f"{fu.application.pet.name}: {scheduled_for.strftime('%d %b %Y at %I:%M %p UTC')}",
        category="adoption",
        link=url_for("adopter.followups"),
    )
    db.session.commit()
    flash("Check-in date and time saved and shared with the adopter.", "success")
    return redirect(url_for("shelter_ops.followups"))


@shelter_ops_bp.route("/followups/<int:fu_id>/remind", methods=["POST"])
@role_required(UserRole.SHELTER)
def remind_followup(fu_id: int):
    shelter = current_shelter()
    fu = db.session.get(FollowUp, fu_id)
    if (
        fu is None
        or shelter is None
        or fu.application.pet.shelter_id != shelter.id
        or fu.application.returned_at is not None
    ):
        abort(404)
    from ..services.notify import notify

    notify(
        fu.application.applicant,
        title=f"{fu.milestone} adoption check-in reminder",
        body=f"Please share how {fu.application.pet.name} is settling in.",
        category="adoption",
        link=url_for("adopter.followups"),
    )
    db.session.commit()
    flash("Reminder sent to the adopter.", "success")
    return redirect(url_for("shelter_ops.followups"))


@shelter_ops_bp.route("/followups/<int:fu_id>/return", methods=["POST"])
@role_required(UserRole.SHELTER)
def return_after_followup(fu_id: int):
    shelter = current_shelter()
    fu = db.session.get(FollowUp, fu_id)
    if (
        fu is None
        or shelter is None
        or fu.application.pet.shelter_id != shelter.id
        or fu.application.stage != ApplicationStage.COMPLETE
        or fu.application.returned_at is not None
        or fu.application.return_status is not None
        or fu.milestone != "30 days"
        or fu.status != FollowUpStatus.NEEDS_SUPPORT
    ):
        abort(404)

    reason = (request.form.get("reason") or "").strip()
    if not reason or len(reason) > 1000:
        flash("Enter a return note of 1 to 1,000 characters.", "warning")
        return redirect(url_for("shelter_ops.returns"))
    now = datetime.now(timezone.utc)
    due_on = fu.due_on if fu.due_on.tzinfo else fu.due_on.replace(tzinfo=timezone.utc)
    adopted_at = fu.application.adopted_at
    if (
        adopted_at is None
        or now < _aware(adopted_at) + timedelta(days=30)
        or due_on > now
    ):
        flash("The 30-day check-in must be due before recording a return.", "warning")
        return redirect(url_for("shelter_ops.returns"))

    application = fu.application
    application.submit_return(reason, now)
    db.session.commit()
    from ..services.notify import notify

    notify(
        application.applicant,
        title=f"Return process started for {application.pet.name}",
        body="Following the 30-day check-in, the shelter has started a return request.",
        category="adoption",
        link=url_for("adopter.returns"),
    )
    db.session.commit()
    flash(f"Return process started for {application.pet.name}.", "success")
    return redirect(url_for("shelter_ops.returns"))


@shelter_ops_bp.route("/applications/<int:app_id>/return/action", methods=["POST"])
@role_required(UserRole.SHELTER)
def return_action(app_id: int):
    shelter = current_shelter()
    application = db.session.get(Application, app_id)
    if (
        application is None
        or shelter is None
        or application.pet.shelter_id != shelter.id
        or application.return_status is None
        or application.returned_at is not None
    ):
        abort(404)

    action = request.form.get("action")
    next_status = {
        (ReturnStatus.SUBMITTED.value, "review"): ReturnStatus.SHELTER_REVIEW,
        (ReturnStatus.SHELTER_REVIEW.value, "confirm"): ReturnStatus.SHELTER_CONFIRMED,
    }.get((application.return_status, action))

    if next_status is not None:
        application.return_status = next_status.value
        db.session.commit()
        from ..services.notify import notify

        notify(
            application.applicant,
            title=f"Return update for {application.pet.name}",
            body=f"Your return request is now: {next_status.label}.",
            category="adoption",
            link=url_for("adopter.returns"),
        )
        db.session.commit()
        flash(f"Return request moved to {next_status.label}.", "success")
        return redirect(url_for("shelter_ops.returns"))

    if action == "schedule" and application.return_status in (
        ReturnStatus.SHELTER_CONFIRMED.value,
        ReturnStatus.RETURN_VISIT.value,
    ):
        try:
            visit_at = datetime.fromisoformat(request.form.get("scheduled_for", ""))
        except ValueError:
            flash("Choose a valid date and time for the return visit.", "warning")
            return redirect(url_for("shelter_ops.returns"))
        if visit_at.tzinfo is None:
            try:
                local_timezone = ZoneInfo(request.form.get("browser_timezone") or "UTC")
            except ZoneInfoNotFoundError:
                flash("Could not determine your time zone. Please reload and try again.", "warning")
                return redirect(url_for("shelter_ops.returns"))
            visit_at = visit_at.replace(tzinfo=local_timezone).astimezone(timezone.utc)
            application.return_visit_timezone = local_timezone.key
        else:
            application.return_visit_timezone = str(visit_at.tzinfo)
        if visit_at <= datetime.now(timezone.utc):
            flash("Choose a future date and time for the return visit.", "warning")
            return redirect(url_for("shelter_ops.returns"))
        application.return_visit_at = visit_at
        application.return_status = ReturnStatus.RETURN_VISIT.value
        db.session.commit()
        from ..services.notify import notify

        notify(
            application.applicant,
            title=f"Return visit scheduled for {application.pet.name}",
            body=f"The shelter will visit your home on {visit_at.strftime('%d %b %Y at %I:%M %p UTC')}.",
            category="adoption",
            link=url_for("adopter.returns"),
        )
        db.session.commit()
        flash("Return visit scheduled and shared with the adopter.", "success")
        return redirect(url_for("shelter_ops.returns"))

    if action == "complete" and application.return_status == ReturnStatus.RETURN_VISIT.value:
        visit_at = application.return_visit_at
        if visit_at is None:
            flash("The return visit can be completed only after its scheduled time.", "warning")
            return redirect(url_for("shelter_ops.returns"))
        if application.return_visit_timezone:
            visit_at_utc = _aware(visit_at)
        else:
            try:
                local_timezone = ZoneInfo(
                    request.form.get("browser_timezone") or "Asia/Kolkata"
                )
            except ZoneInfoNotFoundError:
                flash("Could not determine your time zone. Please reload and try again.", "warning")
                return redirect(url_for("shelter_ops.returns"))
            visit_at_utc = visit_at.replace(tzinfo=local_timezone).astimezone(timezone.utc)
        if visit_at_utc > datetime.now(timezone.utc):
            flash("The return visit can be completed only after its scheduled time.", "warning")
            return redirect(url_for("shelter_ops.returns"))
        application.mark_returned(datetime.now(timezone.utc))
        db.session.commit()
        from ..services.notify import notify

        notify(
            application.applicant,
            title=f"{application.pet.name} returned to shelter",
            body="The shelter has completed the return visit and received your pet.",
            category="adoption",
            link=url_for("adopter.returns"),
        )
        db.session.commit()
        flash(f"{application.pet.name} is now marked as returned to the shelter.", "success")
        return redirect(url_for("shelter_ops.returns"))

    flash("That return status transition is not available.", "warning")
    return redirect(url_for("shelter_ops.returns"))
