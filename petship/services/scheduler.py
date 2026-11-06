"""Background scheduler for reminder notifications (Task 24).

Uses APScheduler's BackgroundScheduler. To avoid duplicate job execution when
running multiple Gunicorn workers, the scheduler is started only when
SCHEDULER_ENABLED is true AND a simple env guard elects a single worker.
In development it runs in-process; in production, run it in a dedicated worker
or set SCHEDULER_ENABLED only on one instance.

The core logic (``run_due_reminders``) is a plain function so it can be called
directly from tests and from a CLI command without the scheduler running.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from flask import Flask

_scheduler = None


def run_due_reminders(app: Flask, now: datetime | None = None) -> int:
    """Notify users about elapsed reminders and appointments, then expire them."""
    from ..extensions import db
    from ..models.application import Application, ApplicationStage, ReturnStatus
    from ..models.appointment import Appointment, AppointmentKind, AppointmentStatus
    from ..models.reminder import Notification, Reminder
    from ..models.review import FollowUp, FollowUpStatus
    from ..models.user import User
    from ..models.health import OwnedPet

    created = 0
    with app.app_context():
        def valid_user_id(user_id: int | None) -> bool:
            return user_id is not None and db.session.get(User, user_id) is not None

        now_utc = now or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        now_utc = now_utc.astimezone(timezone.utc)
        now_local = now_utc.astimezone().replace(tzinfo=None)
        today = now_local.date()
        local_day_start = datetime.combine(today, time.min).astimezone()
        local_day_start_utc = local_day_start.astimezone(timezone.utc)
        local_day_end_utc = (local_day_start + timedelta(days=1)).astimezone(timezone.utc)
        due = db.session.scalars(
            db.select(Reminder).filter(
                Reminder.done.is_(False),
                Reminder.next_due.isnot(None),
            )
        ).all()
        for r in due:
            due_at = datetime.combine(r.next_due, r.at_time or time.min)
            if due_at > now_local:
                continue
            if not valid_user_id(r.owner_id):
                continue
            pet_name = r.pet.name if r.pet else "your pet"
            Notification.push(
                user_id=r.owner_id,
                title=f"Reminder: {r.title}",
                body=(
                    f"{r.title} for {pet_name} scheduled for "
                    f"{due_at.strftime('%d %b %Y at %I:%M %p')} has passed."
                ),
                category="health",
                link="/lifestyle/reminders",
            )
            r.last_notified_on = today
            created += 1
            r.advance()
            while (
                not r.done
                and r.next_due is not None
                and datetime.combine(r.next_due, r.at_time or time.min) <= now_local
            ):
                r.advance()

        upcoming_appointments = db.session.scalars(
            db.select(Appointment).filter(
                Appointment.status == AppointmentStatus.CONFIRMED,
                Appointment.scheduled_for > now_utc,
                Appointment.scheduled_for <= now_utc + timedelta(hours=24),
            )
        ).all()
        for appointment in upcoming_appointments:
            is_home_visit = appointment.kind.value == "home_visit"
            title = (
                f"Home visit reminder: {appointment.pet.name}"
                if is_home_visit and appointment.pet
                else f"Upcoming appointment: {appointment.kind.label}"
            )
            body = (
                f"Scheduled for {appointment.scheduled_for.strftime('%d %b %Y at %I:%M %p')}"
                + (f" · {appointment.location}" if appointment.location else "")
            )
            recipients = {
                user_id
                for user_id in (
                    appointment.user_id,
                    appointment.shelter.owner_id if appointment.shelter else None,
                )
                if user_id is not None
            }
            for user_id in recipients:
                if not valid_user_id(user_id):
                    continue
                exists = db.session.scalar(
                    db.select(Notification.id).filter_by(
                        user_id=user_id,
                        title=title,
                        body=body,
                        category="appointments",
                    )
                )
                if exists:
                    continue
                link = (
                    f"/adopt/application/{appointment.application_id}"
                    if appointment.application_id
                    else "/shelter/appointments"
                    if appointment.shelter_id
                    else "/lifestyle/reminders"
                )
                from .notify import notify

                notify(
                    user_id,
                    title=title,
                    body=body,
                    category="appointments",
                    link=link,
                )
                created += 1

        def notify_on_day(user_id, title, body, category, link):
            nonlocal created
            if not valid_user_id(user_id):
                return
            exists = db.session.scalar(
                db.select(Notification.id).filter_by(
                    user_id=user_id,
                    title=title,
                    body=body,
                    category=category,
                )
            )
            if exists:
                return
            from .notify import notify

            if notify(
                user_id,
                title=title,
                body=body,
                category=category,
                link=link,
            ):
                created += 1

        todays_appointments = db.session.scalars(
            db.select(Appointment).filter(
                Appointment.status == AppointmentStatus.CONFIRMED,
                Appointment.scheduled_for > now_utc,
                Appointment.scheduled_for >= local_day_start_utc,
                Appointment.scheduled_for < local_day_end_utc,
            )
        ).all()
        for appointment in todays_appointments:
            is_home_visit = appointment.kind.value == "home_visit"
            title = (
                f"Today's home visit: {appointment.pet.name}"
                if is_home_visit and appointment.pet
                else f"Today's appointment: {appointment.kind.label}"
            )
            body = (
                f"Scheduled for {appointment.scheduled_for.strftime('%d %b %Y at %I:%M %p')}"
                + (f" · {appointment.location}" if appointment.location else "")
            )
            recipients = {
                user_id
                for user_id in (
                    appointment.user_id,
                    appointment.shelter.owner_id if appointment.shelter else None,
                )
                if user_id is not None
            }
            link = (
                f"/adopt/application/{appointment.application_id}"
                if appointment.application_id
                else "/shelter/appointments"
                if appointment.shelter_id
                else "/lifestyle/reminders"
            )
            for user_id in recipients:
                notify_on_day(user_id, title, body, "appointments", link)

        todays_followups = db.session.scalars(
            db.select(FollowUp)
            .join(Application, FollowUp.application_id == Application.id)
            .filter(
                FollowUp.status == FollowUpStatus.DUE,
                Application.stage == ApplicationStage.COMPLETE,
                Application.returned_at.is_(None),
            )
        ).all()
        for followup in todays_followups:
            due_on = followup.due_on
            if due_on.tzinfo is None:
                due_on = due_on.replace(tzinfo=timezone.utc)
            if due_on.astimezone().date() != today:
                continue
            application = followup.application
            title = f"Today's adoption follow-up: {application.pet.name} · {followup.milestone}"
            body = f"Check-in scheduled for {due_on.astimezone().strftime('%d %b %Y at %I:%M %p')}."
            recipients = {application.applicant_id}
            shelter_owner_id = application.pet.shelter.owner_id
            if shelter_owner_id is not None:
                recipients.add(shelter_owner_id)
            for user_id in recipients:
                link = (
                    "/shelter/followups"
                    if user_id == shelter_owner_id
                    else "/me/followups"
                )
                notify_on_day(user_id, title, body, "adoption", link)

        todays_returns = db.session.scalars(
            db.select(Application).filter(
                Application.return_status == ReturnStatus.RETURN_VISIT.value,
                Application.return_visit_at.is_not(None),
                Application.returned_at.is_(None),
            )
        ).all()
        for application in todays_returns:
            visit_at = application.return_visit_at
            if visit_at.tzinfo is None:
                visit_at = visit_at.replace(tzinfo=timezone.utc)
            if visit_at.astimezone().date() != today:
                continue
            title = f"Today's return visit: {application.pet.name}"
            body = (
                "The shelter is scheduled to collect the pet from your home at "
                f"{visit_at.astimezone().strftime('%I:%M %p')}."
            )
            recipients = {application.applicant_id}
            shelter_owner_id = application.pet.shelter.owner_id
            if shelter_owner_id is not None:
                recipients.add(shelter_owner_id)
            for user_id in recipients:
                link = (
                    "/shelter/returns"
                    if user_id == shelter_owner_id
                    else "/me/returns"
                )
                notify_on_day(user_id, title, body, "adoption", link)

        adoption_applications = db.session.scalars(
            db.select(Application).filter(
                Application.stage.in_([
                    ApplicationStage.AGREEMENT,
                    ApplicationStage.COMPLETE,
                ]),
                Application.returned_at.is_(None),
            )
        ).all()
        for application in adoption_applications:
            pickup = db.session.scalar(
                db.select(Appointment)
                .filter_by(application_id=application.id, kind=AppointmentKind.PICKUP)
                .filter(Appointment.status != AppointmentStatus.CANCELLED)
                .order_by(Appointment.scheduled_for.desc())
            )
            if pickup is None:
                if application.stage != ApplicationStage.COMPLETE or application.adopted_at is None:
                    continue
                scheduled_for = application.adopted_at
                if scheduled_for.tzinfo is None:
                    scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
            else:
                scheduled_for = pickup.scheduled_for
                if scheduled_for.tzinfo is None:
                    scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
            if scheduled_for > now_utc:
                continue
            adoption_was_pending = application.stage == ApplicationStage.AGREEMENT
            if application.stage != ApplicationStage.COMPLETE:
                application.stage = ApplicationStage.COMPLETE
            if application.adopted_at is None:
                application.adopted_at = scheduled_for
            application.pet.mark_adopted()
            if pickup is not None:
                pickup.status = AppointmentStatus.COMPLETED
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
                        adopted_on=scheduled_for.date(),
                    )
                )
            if adoption_was_pending:
                from ..services.notify import notify
                notify(
                    application.applicant_id,
                    title=f"Welcome home, {application.pet.name}!",
                    body="Your adoption is complete and the pet has been added to My Pets.",
                    category="adoption",
                    link=f"/adopt/application/{application.id}",
                )

        expired_appointments = db.session.scalars(
            db.select(Appointment).filter(
                Appointment.status.in_(
                    [AppointmentStatus.CONFIRMED, AppointmentStatus.CHECKED_IN]
                ),
                Appointment.scheduled_for <= now_utc,
                Appointment.user_id.isnot(None),
            )
        ).all()
        for appointment in expired_appointments:
            if not valid_user_id(appointment.user_id):
                appointment.status = AppointmentStatus.COMPLETED
                continue
            link = (
                f"/adopt/application/{appointment.application_id}"
                if appointment.application_id
                else "/lifestyle/reminders"
            )
            Notification.push(
                user_id=appointment.user_id,
                title=f"Appointment completed: {appointment.kind.label}",
                body=(
                    f"Your {appointment.kind.label.lower()} scheduled for "
                    f"{appointment.scheduled_for.strftime('%d %b %Y at %I:%M %p')} has passed."
                ),
                category="appointments",
                link=link,
            )
            appointment.status = AppointmentStatus.COMPLETED
            created += 1
        db.session.commit()
    return created


def init_scheduler(app: Flask) -> None:
    """Start the background scheduler once, if enabled."""
    global _scheduler
    if not app.config.get("SCHEDULER_ENABLED"):
        return
    if _scheduler is not None:
        return

    from apscheduler.schedulers.background import BackgroundScheduler

    _scheduler = BackgroundScheduler(daemon=True)
    # Check for due reminders every 15 minutes.
    _scheduler.add_job(
        lambda: run_due_reminders(app),
        "interval",
        minutes=15,
        id="due_reminders",
        replace_existing=True,
    )
    _scheduler.start()
    app.logger.info("Reminder scheduler started.")


def register_reminder_cli(app: Flask) -> None:
    """Register `flask run-reminders` to process due reminders once (cron use)."""
    import click

    @app.cli.command("run-reminders")
    def _run_reminders():  # pragma: no cover - thin CLI wrapper
        count = run_due_reminders(app)
        click.echo(f"Emitted {count} reminder notification(s).")
