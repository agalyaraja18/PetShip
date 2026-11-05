"""Reminder centre + health reminders + notifications centre (Task 24)."""
from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta, timezone

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
from flask_login import current_user, login_required

from ..extensions import db
from ..models.application import Application, ApplicationStage, ReturnStatus
from ..models.appointment import Appointment, AppointmentKind, AppointmentStatus
from ..models.health import OwnedPet
from ..models.reminder import Notification, Recurrence, Reminder
from ..models.review import FollowUp, FollowUpStatus
from ..models.user import UserRole

reminders_bp = Blueprint("reminders", __name__, url_prefix="/lifestyle")


def _my_reminders():
    return db.session.scalars(
        db.select(Reminder)
        .filter_by(owner_id=current_user.id)
        .order_by(Reminder.next_due.asc().nullslast(), Reminder.at_time.asc().nullsfirst())
    ).all()


@reminders_bp.route("/reminders")
@login_required
def centre():
    from ..services.scheduler import run_due_reminders

    run_due_reminders(current_app._get_current_object())
    now = datetime.now(timezone.utc)
    today = now.astimezone().date()
    period_options = [
        ("all", "All"),
        ("today", "Today"),
        ("tomorrow", "Tomorrow"),
        ("this-week", "This Week"),
        ("this-month", "This Month"),
    ]
    selected_period = request.args.get("period", "all")
    if selected_period not in {key for key, _ in period_options}:
        selected_period = "all"
    is_shelter = current_user.role == UserRole.SHELTER
    category_names = (
        ["Today's tasks", "Home visits", "Follow ups", "Adoption applications", "Return pets"]
        if is_shelter
        else ["Vet appointments", "Follow ups", "Today's tasks", "Adoption applications", "Return pets"]
    )
    events = []

    def add_event(category, title, detail, due_at, href, reminder_id=None):
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        events.append({
            "category": category,
            "title": title,
            "detail": detail,
            "due_at": due_at,
            "href": href,
            "reminder_id": reminder_id,
        })

    reminders = _my_reminders()
    for reminder in reminders:
        if reminder.done or reminder.next_due is None:
            continue
        due_at = datetime.combine(
            reminder.next_due, reminder.at_time or dt_time.min
        ).astimezone()
        pet_name = reminder.pet.name if reminder.pet else None
        add_event(
            "Today's tasks",
            reminder.title,
            " · ".join(filter(None, [
                pet_name,
                reminder.recurrence.label,
                reminder.at_time.strftime("%I:%M %p") if reminder.at_time else None,
            ])),
            due_at,
            url_for("reminders.centre"),
            reminder.id,
        )

    appointments_query = db.select(Appointment).filter(
        Appointment.status.in_([AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING]),
    )
    if is_shelter:
        from .shelter import current_shelter

        shelter = current_shelter()
        appointments_query = appointments_query.filter(
            Appointment.shelter_id == (shelter.id if shelter else -1)
        )
    else:
        appointments_query = appointments_query.filter(
            Appointment.user_id == current_user.id
        )
    appointments = db.session.scalars(
        appointments_query.order_by(Appointment.scheduled_for.asc())
    ).all()
    for appointment in appointments:
        if is_shelter:
            if appointment.kind != AppointmentKind.HOME_VISIT:
                continue
            category = "Home visits"
            href = url_for("shelter_ops.appointments")
        elif appointment.kind == AppointmentKind.VET_VISIT:
            category = "Vet appointments"
            href = url_for("adopter.appointments")
        elif appointment.application_id is not None:
            category = "Adoption applications"
            href = url_for("adoption.track", app_id=appointment.application_id)
        else:
            continue
        add_event(
            category,
            f"{appointment.kind.label}: {appointment.pet.name if appointment.pet else appointment.service or 'Appointment'}",
            appointment.scheduled_for.strftime("%d %b %Y at %I:%M %p")
            + (f" · {appointment.location}" if appointment.location else ""),
            appointment.scheduled_for,
            href,
        )

    followup_query = (
        db.select(FollowUp)
        .join(Application, FollowUp.application_id == Application.id)
        .filter(
            FollowUp.status == FollowUpStatus.DUE,
            Application.stage == ApplicationStage.COMPLETE,
            Application.returned_at.is_(None),
        )
    )
    if is_shelter:
        from .shelter import current_shelter

        shelter = current_shelter()
        if shelter:
            followup_query = followup_query.filter(Application.pet.has(shelter_id=shelter.id))
        else:
            followup_query = followup_query.filter(Application.id == -1)
    else:
        followup_query = followup_query.filter(Application.applicant_id == current_user.id)
    followups = db.session.scalars(followup_query.order_by(FollowUp.due_on.asc())).all()
    for followup in followups:
        add_event(
            "Follow ups",
            f"{followup.milestone} check-in: {followup.application.pet.name}",
            f"{followup.application.applicant.full_name} · {followup.due_on.strftime('%d %b %Y at %I:%M %p')}"
            if is_shelter else followup.due_on.strftime("%d %b %Y at %I:%M %p"),
            followup.due_on,
            url_for("shelter_ops.followups") if is_shelter else url_for("adopter.followups"),
        )

    return_query = db.select(Application).filter(
        Application.return_status == ReturnStatus.RETURN_VISIT.value,
        Application.return_visit_at.is_not(None),
        Application.returned_at.is_(None),
    )
    if is_shelter:
        from .shelter import current_shelter

        shelter = current_shelter()
        return_query = return_query.filter(
            Application.pet.has(shelter_id=shelter.id if shelter else -1)
        )
    else:
        return_query = return_query.filter(Application.applicant_id == current_user.id)
    return_visits = db.session.scalars(
        return_query.order_by(Application.return_visit_at.asc())
    ).all()
    for application in return_visits:
        add_event(
            "Return pets",
            f"Home collection: {application.pet.name}",
            f"{application.applicant.full_name} · " if is_shelter else "",
            application.return_visit_at,
            url_for("shelter_ops.returns") if is_shelter else url_for("adopter.returns"),
        )

    matches_period = {
        "all": lambda due: True,
        "today": lambda due: due == today,
        "tomorrow": lambda due: due == today + timedelta(days=1),
        "this-week": lambda due: today + timedelta(days=1) < due <= today + timedelta(days=7),
        "this-month": lambda due: today + timedelta(days=7) < due <= today + timedelta(days=30),
    }
    periods = []
    for key, label in period_options:
        matches = matches_period[key]
        grouped = {category: [] for category in category_names}
        for event in events:
            event_date = event["due_at"].astimezone().date()
            if matches(event_date):
                grouped[event["category"]].append(event)
        periods.append({
            "key": key,
            "label": label,
            "categories": grouped,
            "count": sum(len(items) for items in grouped.values()),
        })
    selected = next(period for period in periods if period["key"] == selected_period)

    pets = db.session.scalars(
        db.select(OwnedPet).filter_by(owner_id=current_user.id)
    ).all() if not is_shelter else []

    return render_template(
        "lifestyle/reminders.html",
        periods=periods,
        selected_period=selected_period,
        selected=selected,
        category_names=category_names,
        pets=pets,
        recurrences=list(Recurrence),
        is_shelter=is_shelter,
        active_nav="reminders",
    )


@reminders_bp.route("/reminders/new")
@login_required
def new_reminder():
    is_shelter = current_user.role == UserRole.SHELTER
    pets = db.session.scalars(
        db.select(OwnedPet).filter_by(owner_id=current_user.id)
    ).all() if not is_shelter else []
    return render_template(
        "lifestyle/reminder_new.html",
        pets=pets,
        recurrences=list(Recurrence),
        is_shelter=is_shelter,
        active_nav="reminders",
    )


@reminders_bp.route("/reminders/add", methods=["POST"])
@login_required
def add():
    at = request.form.get("at_time")
    at_time = None
    if at:
        try:
            at_time = dt_time.fromisoformat(at if len(at) > 5 else at + ":00")
        except ValueError:
            flash("Choose a valid reminder time.", "warning")
            return redirect(url_for("reminders.centre"))
    due_on = request.form.get("next_due")
    try:
        next_due = date.fromisoformat(due_on) if due_on else date.today()
    except ValueError:
        flash("Choose a valid reminder date.", "warning")
        return redirect(url_for("reminders.centre"))
    try:
        recurrence = Recurrence(request.form.get("recurrence", "once"))
    except ValueError:
        flash("Choose a valid reminder repeat interval.", "warning")
        return redirect(url_for("reminders.centre"))
    pet_id = request.form.get("pet_id", type=int)
    reminder = Reminder(
        owner_id=current_user.id,
        pet_id=pet_id or None,
        title=(request.form.get("title") or "Reminder").strip(),
        category=request.form.get("category", "care"),
        recurrence=recurrence,
        at_time=at_time,
        next_due=next_due,
    )
    db.session.add(reminder)
    db.session.commit()
    flash("Reminder saved.", "success")
    return redirect(url_for("reminders.centre"))


@reminders_bp.route("/reminders/<int:reminder_id>/toggle", methods=["POST"])
@login_required
def toggle(reminder_id: int):
    reminder = db.session.get(Reminder, reminder_id)
    if reminder is None or reminder.owner_id != current_user.id:
        abort(404)
    if reminder.recurrence == Recurrence.ONCE:
        reminder.done = not reminder.done
    else:
        # Completing a recurring reminder rolls it to the next occurrence.
        reminder.advance()
    db.session.commit()
    if request.headers.get("HX-Request"):
        return ("", 204)
    return redirect(url_for("reminders.centre"))


# ---- Notifications centre + bell dropdown ----
@reminders_bp.route("/notifications")
@login_required
def notifications():
    category_options = [
        ("all", "All"),
        ("adoption", "Adoption"),
        ("health", "Health"),
        ("appointments", "Appointments"),
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
    items = db.session.scalars(query.order_by(Notification.created_at.desc())).all()
    notification_groups = [
        (
            key,
            label,
            [
                item for item in items
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
    ]
    return render_template(
        "lifestyle/notifications.html",
        notification_groups=notification_groups,
        category_options=category_options,
        category=category,
        active_nav="notifications",
    )


@reminders_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def read_all():
    db.session.query(Notification).filter_by(
        user_id=current_user.id, read=False
    ).update({"read": True})
    db.session.commit()
    return redirect(url_for("reminders.notifications"))
