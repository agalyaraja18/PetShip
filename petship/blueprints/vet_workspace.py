"""Vet workspace: dashboard, appointment management, patient details (Task 20)."""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, time, timedelta, timezone
import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..models.appointment import (
    Appointment,
    AppointmentKind,
    AppointmentStatus,
)
from ..models.health import (
    HealthPlan,
    MedicalRecord,
    OwnedPet,
    RecordType,
    Vaccination,
    VetPatient,
)
from ..models.pet import Pet
from ..models.reminder import Notification, Reminder
from ..models.user import User, UserRole
from ..security import role_required
from ..services.storage import save_image

vet_workspace_bp = Blueprint("vet_workspace", __name__, url_prefix="/vet")


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _my_appointments():
    return db.session.scalars(
        db.select(Appointment)
        .filter(Appointment.vet_id == current_user_id())
        .order_by(Appointment.scheduled_for.asc())
    ).all()


def _appointment_pet_labels(appointments):
    labels = {}
    for appointment in appointments:
        name = (appointment.note or (appointment.pet.name if appointment.pet else "")).strip()
        owned_pet = None
        if appointment.user_id and name:
            owned_pet = db.session.scalar(
                db.select(OwnedPet)
                .filter(
                    OwnedPet.owner_id == appointment.user_id,
                    db.func.lower(OwnedPet.name) == name.casefold(),
                )
                .order_by(OwnedPet.id)
            )
        labels[appointment.id] = (
            f"{owned_pet.name} · {owned_pet.public_pet_id}"
            if owned_pet
            else (name or "Patient")
        )
    return labels


def current_user_id():
    from flask_login import current_user

    return current_user.id


@vet_workspace_bp.route("/dashboard")
@role_required(UserRole.VET)
def dashboard():
    appts = _my_appointments()
    now = datetime.now(timezone.utc)
    today = now.date()

    # Show today's appointments if any; otherwise show upcoming ones so a newly
    # booked (future) appointment is immediately visible on the dashboard.
    todays = [a for a in appts if _aware(a.scheduled_for).date() == today]
    upcoming = [a for a in appts if _aware(a.scheduled_for).date() > today]
    schedule = todays if todays else upcoming[:8]
    schedule_label = "Today's schedule" if todays else "Upcoming appointments"

    week_count = sum(
        1 for a in appts
        if today <= _aware(a.scheduled_for).date() <= today + timedelta(days=7)
    )
    patients = len({a.pet_id or a.note for a in appts if (a.pet_id or a.note)})

    needs_attention = [
        a for a in appts
        if a.status == AppointmentStatus.CONFIRMED and _aware(a.scheduled_for) >= now
    ][:3]

    return render_template(
        "vet/dashboard.html",
        todays=schedule,
        schedule_label=schedule_label,
        week_count=week_count,
        patients=patients,
        needs_attention=needs_attention,
        pet_labels=_appointment_pet_labels(schedule + needs_attention),
        now=now,
        active_nav="dashboard",
    )


@vet_workspace_bp.route("/settings", methods=["GET", "POST"])
@role_required(UserRole.VET)
def settings():
    if request.method == "POST":
        if request.form.get("section") == "notifications":
            prefs = dict(current_user.prefs)
            for key in ("health_reminders", "vet_appointments", "messages"):
                prefs[key] = request.form.get(key) == "on"
            current_user.notification_prefs = prefs
            db.session.commit()
            flash("Notification preferences saved.", "success")
            return redirect(url_for("vet_workspace.settings"))
        current_user.two_factor_enabled = request.form.get("two_factor_enabled") == "on"
        db.session.commit()
        state = "enabled" if current_user.two_factor_enabled else "disabled"
        flash(f"Two-factor authentication {state}.", "info")
        return redirect(url_for("vet_workspace.settings"))

    profile = current_user.vet_profile[0] if current_user.vet_profile else None
    return render_template(
        "vet/settings.html",
        user=current_user,
        clinic_name=(profile.clinic_name if profile else None) or "Vet account",
        active_prefs=current_user.prefs,
        active_nav="settings",
    )


@vet_workspace_bp.route("/notifications")
@role_required(UserRole.VET)
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
    items = db.session.scalars(
        query.order_by(Notification.created_at.desc()).limit(100)
    ).all()
    groups = [
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
        "vet/notifications.html",
        notifications=items,
        notification_groups=groups,
        category_options=category_options,
        category=category,
        active_nav="notifications",
    )


@vet_workspace_bp.route("/notifications/read-all", methods=["POST"])
@role_required(UserRole.VET)
def read_all_notifications():
    db.session.query(Notification).filter_by(
        user_id=current_user.id, read=False
    ).update({"read": True})
    db.session.commit()
    return redirect(url_for("vet_workspace.notifications"))


@vet_workspace_bp.route("/appointments")
@role_required(UserRole.VET)
def appointments():
    categories = [
        ("all", "All"),
        ("vaccination", "Vaccinations"),
        ("general", "General check-up"),
        ("dental", "Dental"),
        ("surgery", "Surgery"),
        ("other", "Other"),
    ]
    periods = [
        ("all", "All"),
        ("today", "Today"),
        ("tomorrow", "Tomorrow"),
        ("this-week", "This week"),
        ("this-month", "This month"),
    ]
    category = request.args.get("category", "all")
    period = request.args.get("period", "all")
    if category not in {key for key, _ in categories}:
        category = "all"
    if period not in {key for key, _ in periods}:
        period = "all"
    today = date.today()

    def appointment_category(appointment):
        service = (appointment.service or "").casefold()
        if "vaccin" in service:
            return "vaccination"
        if "dental" in service:
            return "dental"
        if "surg" in service:
            return "surgery"
        if "general" in service or "check-up" in service or "check up" in service:
            return "general"
        return "other"

    def in_period(appointment):
        scheduled = _aware(appointment.scheduled_for).astimezone().date()
        if period == "today":
            return scheduled == today
        if period == "tomorrow":
            return scheduled == today + timedelta(days=1)
        if period == "this-week":
            return today <= scheduled <= today + timedelta(days=7)
        if period == "this-month":
            return scheduled.year == today.year and scheduled.month == today.month
        return True

    appts = [
        appointment for appointment in _my_appointments()
        if in_period(appointment)
        and (category == "all" or appointment_category(appointment) == category)
    ]
    grouped = OrderedDict()
    for key, label in categories:
        if key == "all":
            continue
        matching = [
            appointment for appointment in appts
            if appointment_category(appointment) == key
        ]
        if matching:
            grouped[label] = matching

    return render_template(
        "vet/appointments.html",
        grouped=grouped,
        categories=categories,
        periods=periods,
        category=category,
        period=period,
        AppointmentStatus=AppointmentStatus,
        pet_labels=_appointment_pet_labels(appts),
        active_nav="appointments",
    )


@vet_workspace_bp.route("/vaccinations")
@role_required(UserRole.VET)
def vaccinations():
    """Vaccinations across all owned pets, grouped by status, for the vet to
    track and follow up."""
    from ..models.health import OwnedPet, Vaccination, VaccineStatus

    vaccs = db.session.scalars(
        db.select(Vaccination).join(OwnedPet, Vaccination.pet_id == OwnedPet.id)
        .order_by(Vaccination.due_on.asc().nullslast())
    ).all()
    overdue = [v for v in vaccs if v.status == VaccineStatus.OVERDUE]
    due_soon = [v for v in vaccs if v.status == VaccineStatus.DUE]
    upcoming = [v for v in vaccs if v.status == VaccineStatus.UPCOMING]
    done = [v for v in vaccs if v.status == VaccineStatus.DONE]
    return render_template(
        "vet/vaccinations.html",
        overdue=overdue, due_soon=due_soon, upcoming=upcoming, done=done,
        total=len(vaccs), active_nav="vaccinations",
    )


@vet_workspace_bp.route("/patients")
@role_required(UserRole.VET)
def patients():
    orphan_links = [
        link for link in db.session.scalars(db.select(VetPatient)).all()
        if link.pet is None or link.pet.owner is None
    ]
    for link in orphan_links:
        db.session.delete(link)
    if orphan_links:
        db.session.commit()
    pets = {
        link.pet.id: link.pet
        for link in db.session.scalars(
            db.select(VetPatient)
            .filter_by(vet_id=current_user.id)
            .join(OwnedPet, VetPatient.pet_id == OwnedPet.id)
            .order_by(OwnedPet.name)
        ).all()
        if link.pet is not None and link.pet.owner is not None
    }

    appointments = _my_appointments()
    for appointment in appointments:
        name = (appointment.note or (appointment.pet.name if appointment.pet else "")).strip()
        if not appointment.user_id or not name:
            continue
        pet = db.session.scalar(
            db.select(OwnedPet)
            .filter(
                OwnedPet.owner_id == appointment.user_id,
                db.func.lower(OwnedPet.name) == name.casefold(),
            )
            .order_by(OwnedPet.id)
        )
        if pet is not None and pet.owner is not None:
            pets[pet.id] = pet

    vet_names = {current_user.full_name.strip().casefold()}
    profiles = current_user.vet_profile or []
    if profiles and profiles[0].display_name:
        vet_names.add(profiles[0].display_name.strip().casefold())
    assigned_pets = db.session.scalars(
        db.select(OwnedPet).filter(OwnedPet.primary_vet.is_not(None))
    ).all()
    for pet in assigned_pets:
        primary_vet = (pet.primary_vet or "").casefold()
        if pet.owner is not None and any(name and name in primary_vet for name in vet_names):
            pets[pet.id] = pet

    existing_pet_ids = set(
        db.session.scalars(
            db.select(VetPatient.pet_id).filter_by(vet_id=current_user.id)
        ).all()
    )
    for pet in pets.values():
        if pet.id not in existing_pet_ids:
            db.session.add(VetPatient(vet_id=current_user.id, pet_id=pet.id))
    if any(pet.id not in existing_pet_ids for pet in pets.values()):
        db.session.commit()

    patient_rows = []
    for pet in sorted(pets.values(), key=lambda item: item.name.casefold()):
        patient_rows.append({
            "name": pet.name,
            "breed": pet.breed or "—",
            "owner": pet.owner.full_name,
            "pet": pet,
            "appointment": None,
            "health_record_count": len(pet.medical_records),
        })

    return render_template(
        "vet/patients.html", patients=patient_rows, active_nav="patients"
    )


@vet_workspace_bp.route("/patients/new", methods=["GET", "POST"])
@role_required(UserRole.VET)
def new_patient():
    if request.method == "POST":
        public_id = (request.form.get("pet_id") or "").strip().upper()
        match = re.fullmatch(r"PET-(\d{8})", public_id)
        pet = db.session.get(OwnedPet, int(match.group(1))) if match else None
        if pet is None or pet.public_pet_id != public_id:
            flash("Enter a valid pet ID shared by the adopter.", "warning")
        elif pet.application and pet.application.returned_at is not None:
            flash("Returned pets cannot be added as active patients.", "warning")
        elif db.session.scalar(
            db.select(VetPatient).filter_by(vet_id=current_user.id, pet_id=pet.id)
        ):
            flash("This pet is already in your patient list.", "info")
        else:
            db.session.add(VetPatient(vet_id=current_user.id, pet_id=pet.id))
            Notification.push(
                pet.owner_id,
                f"{pet.name} added to a veterinary patient list",
                f"{current_user.full_name} can now share health records and plans for {pet.name}.",
                category="health",
                link=url_for("health.dashboard", pet_id=pet.id),
            )
            db.session.commit()
            flash(f"{pet.name} added to your patients.", "success")
            return redirect(url_for("vet_workspace.patients"))

    return render_template("vet/new_patient.html", active_nav="newpatient")


def _linked_patient_or_404(pet_id: int) -> OwnedPet:
    link = db.session.scalar(
        db.select(VetPatient).filter_by(vet_id=current_user.id, pet_id=pet_id)
    )
    if link is None:
        abort(404)
    return link.pet


@vet_workspace_bp.route("/patients/<int:pet_id>/health-record")
@role_required(UserRole.VET)
def patient_health_record(pet_id: int):
    pet = _linked_patient_or_404(pet_id)
    records = db.session.scalars(
        db.select(MedicalRecord)
        .filter_by(pet_id=pet.id)
        .order_by(MedicalRecord.record_date.desc(), MedicalRecord.created_at.desc())
    ).all()
    records = _unique_medical_records(records)
    today = date.today()
    vaccinations = db.session.scalars(
        db.select(Vaccination)
        .filter_by(pet_id=pet.id)
        .order_by(Vaccination.due_on.asc().nullslast())
    ).all()
    vaccinations = _unique_vaccinations(vaccinations)
    reminders = db.session.scalars(
        db.select(Reminder)
        .filter(
            Reminder.pet_id == pet.id,
            Reminder.owner_id == pet.owner_id,
            Reminder.done.is_(False),
            Reminder.next_due >= today,
        )
        .order_by(Reminder.next_due.asc(), Reminder.at_time.asc().nullslast())
    ).all()
    current_plans = db.session.scalars(
        db.select(HealthPlan)
        .filter(
            HealthPlan.pet_id == pet.id,
            db.or_(
                HealthPlan.next_visit_on.is_(None),
                HealthPlan.next_visit_on >= today,
            ),
        )
        .order_by(HealthPlan.created_at.desc())
    ).all()
    today_plans = db.session.scalars(
        db.select(HealthPlan)
        .filter(
            HealthPlan.pet_id == pet.id,
            HealthPlan.next_visit_on == today,
        )
        .order_by(HealthPlan.created_at.desc())
    ).all()
    plans = db.session.scalars(
        db.select(HealthPlan)
        .filter(
            HealthPlan.pet_id == pet.id,
            HealthPlan.next_visit_on > today,
        )
        .order_by(HealthPlan.next_visit_on.asc().nullslast())
    ).all()
    today_reminders = [reminder for reminder in reminders if reminder.next_due == today]
    upcoming_reminders = [reminder for reminder in reminders if reminder.next_due > today]
    past_prescriptions = [
        record for record in records
        if record.record_type == RecordType.PRESCRIPTION and record.record_date < today
        and not record.title.strip().casefold().startswith("consultation")
    ]
    past_records = [record for record in records if record.record_date <= today]
    past_health_records = [
        record for record in past_records
        if record.record_type not in {RecordType.PRESCRIPTION, RecordType.LAB, RecordType.SURGERY}
    ]
    past_prescription_plans = [
        plan for plan in db.session.scalars(
            db.select(HealthPlan)
            .filter(
                HealthPlan.pet_id == pet.id,
                HealthPlan.prescribed_medicines.is_not(None),
                HealthPlan.prescription_end_on.is_not(None),
                HealthPlan.prescription_end_on < today,
            )
            .order_by(HealthPlan.prescription_end_on.desc())
        ).all()
    ]
    present_prescription_plans = [
        plan for plan in db.session.scalars(
            db.select(HealthPlan)
            .filter(
                HealthPlan.pet_id == pet.id,
                HealthPlan.prescribed_medicines.is_not(None),
                db.or_(
                    HealthPlan.prescription_end_on.is_(None),
                    HealthPlan.prescription_end_on >= today,
                ),
            )
            .order_by(HealthPlan.prescription_start_on.desc(), HealthPlan.id.desc())
        ).all()
    ]
    present_prescription_records = [
        record for record in records
        if record.record_type == RecordType.PRESCRIPTION and record.record_date >= today
    ]
    upcoming_appointments = db.session.scalars(
        db.select(Appointment)
        .filter(
            Appointment.vet_id == current_user.id,
            Appointment.user_id == pet.owner_id,
            Appointment.status != AppointmentStatus.CANCELLED,
            Appointment.scheduled_for >= datetime.now(timezone.utc),
        )
        .order_by(Appointment.scheduled_for.asc())
    ).all()
    upcoming_appointments = [
        appointment for appointment in upcoming_appointments
        if pet.public_pet_id in (appointment.note or "")
        or pet.name.casefold() in (appointment.note or "").casefold()
    ]
    return render_template(
        "vet/patient_health_record.html",
        pet=pet,
        records=records,
        vaccinations=vaccinations,
        today_reminders=today_reminders,
        upcoming_reminders=upcoming_reminders,
        today_plans=today_plans,
        current_plans=current_plans,
        plans=plans,
        past_prescriptions=past_prescriptions,
        past_records=past_records,
        past_health_records=past_health_records,
        past_prescription_plans=past_prescription_plans,
        present_prescription_plans=present_prescription_plans,
        present_prescription_records=present_prescription_records,
        upcoming_appointments=upcoming_appointments,
        RecordType=RecordType,
        today=today,
        today_iso=today.isoformat(),
        active_nav="patients",
    )


@vet_workspace_bp.route("/patients/<int:pet_id>/health-record/<int:record_id>")
@role_required(UserRole.VET)
def patient_health_record_detail(pet_id: int, record_id: int):
    pet = _linked_patient_or_404(pet_id)
    record = db.session.get(MedicalRecord, record_id)
    if record is None or record.pet_id != pet.id:
        abort(404)
    return render_template(
        "vet/patient_health_record_detail.html",
        pet=pet,
        record=record,
        active_nav="patients",
    )


def _unique_medical_records(records):
    unique = []
    seen = set()
    for record in records:
        identity = (
            record.record_type,
            record.title.strip().casefold(),
            record.record_date,
            (record.findings or "").strip().casefold(),
            (record.diagnosis or "").strip().casefold(),
            (record.summary or "").strip().casefold(),
        )
        if identity not in seen:
            seen.add(identity)
            unique.append(record)
    return unique


def _unique_vaccinations(vaccinations):
    unique = []
    seen = set()
    for vaccination in vaccinations:
        identity = (
            vaccination.name.strip().casefold(),
            vaccination.due_on,
            vaccination.last_given,
        )
        if identity not in seen:
            seen.add(identity)
            unique.append(vaccination)
    return unique


@vet_workspace_bp.route("/patients/new-plan", methods=["GET", "POST"])
@role_required(UserRole.VET)
def new_health_plan():
    public_pet_id = (
        request.form.get("pet_id")
        if request.method == "POST"
        else request.args.get("pet_id")
    ) or ""
    public_pet_id = public_pet_id.strip().upper()
    if request.method == "POST":
        match = re.fullmatch(r"PET-(\d{8})", public_pet_id)
        pet = db.session.get(OwnedPet, int(match.group(1))) if match else None
        if pet is None or pet.public_pet_id != public_pet_id:
            flash("Enter a valid pet ID linked to your vet account.", "warning")
        elif db.session.scalar(
            db.select(VetPatient).filter_by(vet_id=current_user.id, pet_id=pet.id)
        ) is None:
            flash("This pet is not in your patient list. Add the pet ID first.", "warning")
        else:
            consultation = (request.form.get("consultation") or "").strip()
            diagnosis = (request.form.get("diagnosis") or "").strip() or None
            medicines = (request.form.get("prescribed_medicines") or "").strip() or None
            next_visit_value = (request.form.get("next_visit_on") or "").strip()
            next_visit_purpose = (request.form.get("next_visit_purpose") or "").strip() or None
            schedule_next_visit = (
                request.form.get("schedule_next_visit") == "yes"
                or bool(next_visit_value)
            )
            if not consultation:
                flash("Enter the consultation and health instructions.", "warning")
            else:
                next_visit = None
                next_visit_error = None
                if schedule_next_visit:
                    if request.form.get("schedule_next_visit") == "yes" and not next_visit_purpose:
                        next_visit_error = "Enter the purpose of the next visit."
                    elif not next_visit_value:
                        next_visit_error = "Enter the next visit date."
                    else:
                        try:
                            next_visit = date.fromisoformat(next_visit_value)
                        except ValueError:
                            next_visit_error = "Enter a valid next visit date."
                        else:
                            if next_visit < date.today():
                                next_visit_error = "The next visit date cannot be in the past."
                else:
                    next_visit_purpose = None

                if next_visit_error:
                    flash(next_visit_error, "warning")
                else:
                        plan_title = f"Care plan · {date.today().strftime('%d %b %Y')}"
                        duplicate = db.session.scalar(
                            db.select(HealthPlan).filter_by(
                                pet_id=pet.id,
                                vet_id=current_user.id,
                                title=plan_title,
                                instructions=consultation,
                                prescribed_medicines=medicines,
                                next_visit_on=next_visit,
                                next_visit_purpose=next_visit_purpose,
                            ).limit(1)
                        )
                        if duplicate:
                            flash("This consultation and plan have already been shared.", "info")
                            return redirect(
                                url_for("vet_workspace.patient_health_record", pet_id=pet.id)
                            )
                        record = MedicalRecord(
                            pet_id=pet.id,
                            vet_id=current_user.id,
                            record_type=RecordType.CONSULTATION,
                            title=f"Consultation · {date.today().strftime('%d %b %Y')}",
                            record_date=date.today(),
                            vet_name=current_user.full_name,
                            findings=consultation,
                            diagnosis=diagnosis,
                            summary=consultation,
                            shared_with_owner=True,
                        )
                        plan = HealthPlan(
                            pet_id=pet.id,
                            vet_id=current_user.id,
                            title=plan_title,
                            instructions=consultation,
                            prescribed_medicines=medicines,
                            next_visit_on=next_visit,
                            next_visit_purpose=next_visit_purpose,
                            prescription_start_on=(
                                date.today()
                                if medicines and medicines.casefold() not in {"none", "no medicines", "nil"}
                                else None
                            ),
                        )
                        db.session.add_all([record, plan])
                        Notification.push(
                            pet.owner_id,
                            f"New health plan for {pet.name}",
                            f"{current_user.full_name} shared today's consultation and "
                            f"prescription for {pet.name} ({pet.public_pet_id}).",
                            category="health",
                            link=url_for("health.dashboard", pet_id=pet.id),
                        )
                        db.session.commit()
                        flash(f"Health plan saved and shared with {pet.owner.full_name}.", "success")
                        return redirect(
                            url_for("vet_workspace.patient_health_record", pet_id=pet.id)
                        )

    return render_template(
        "vet/new_health_plan.html",
        pet_id=public_pet_id,
        today=date.today().isoformat(),
        active_nav="patients",
    )


@vet_workspace_bp.route(
    "/patients/<int:pet_id>/health-record/medical-record", methods=["POST"]
)
@role_required(UserRole.VET)
def add_medical_record(pet_id: int):
    pet = _linked_patient_or_404(pet_id)
    try:
        record_type = RecordType(request.form.get("record_type", "consultation"))
        record_date = date.fromisoformat(request.form.get("record_date") or "")
    except ValueError:
        flash("Choose a valid record type and date.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("Enter a title for the medical record.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    duplicate = db.session.scalar(
        db.select(MedicalRecord).filter_by(
            pet_id=pet.id,
            vet_id=current_user.id,
            record_type=record_type,
            title=title,
            record_date=record_date,
            findings=(request.form.get("findings") or "").strip() or None,
            diagnosis=(request.form.get("diagnosis") or "").strip() or None,
            summary=(request.form.get("summary") or "").strip() or None,
        ).limit(1)
    )
    if duplicate:
        flash("This health record has already been shared.", "info")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    record = MedicalRecord(
        pet_id=pet.id,
        vet_id=current_user.id,
        record_type=record_type,
        title=title,
        record_date=record_date,
        vet_name=current_user.full_name,
        findings=(request.form.get("findings") or "").strip() or None,
        diagnosis=(request.form.get("diagnosis") or "").strip() or None,
        summary=(request.form.get("summary") or "").strip() or None,
        attachments=[
            url
            for url in (
                save_image(request.files.get("lab_report"), folder="lab-reports"),
            )
            if url
        ],
        shared_with_owner=True,
    )
    db.session.add(record)
    Notification.push(
        pet.owner_id,
        f"New health record for {pet.name}",
        f"{current_user.full_name} shared {title} to {pet.name}'s health profile.",
        category="health",
        link=url_for("health.dashboard", pet_id=pet.id),
    )
    db.session.commit()
    flash(f"Health record shared with {pet.owner.full_name}.", "success")
    return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))


@vet_workspace_bp.route(
    "/patients/<int:pet_id>/health-record/plan", methods=["POST"]
)
@role_required(UserRole.VET)
def add_health_plan(pet_id: int):
    pet = _linked_patient_or_404(pet_id)
    title = (request.form.get("title") or "").strip()
    instructions = (request.form.get("instructions") or "").strip() or None
    medicines = (request.form.get("prescribed_medicines") or "").strip() or None
    next_visit_value = (request.form.get("next_visit_on") or "").strip()
    next_visit_purpose = (request.form.get("next_visit_purpose") or "").strip() or None
    next_visit = None
    if next_visit_value:
        try:
            next_visit = date.fromisoformat(next_visit_value)
        except ValueError:
            flash("Enter a valid next visit date.", "warning")
            return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
        if next_visit_purpose is None and request.form.get("schedule_next_visit") == "yes":
            flash("Enter the purpose of the next visit.", "warning")
            return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    if not title:
        flash("Enter a title for the health plan.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    duplicate = db.session.scalar(
        db.select(HealthPlan).filter_by(
            pet_id=pet.id,
            vet_id=current_user.id,
            title=title,
            instructions=instructions,
            prescribed_medicines=medicines,
            next_visit_on=next_visit,
            next_visit_purpose=next_visit_purpose,
        ).limit(1)
    )
    if duplicate:
        flash("This health plan has already been shared.", "info")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    plan = HealthPlan(
        pet_id=pet.id,
        vet_id=current_user.id,
        title=title,
        instructions=instructions,
        prescribed_medicines=medicines,
        next_visit_on=next_visit,
        next_visit_purpose=next_visit_purpose,
        prescription_start_on=(
            date.today()
            if medicines and medicines.casefold() not in {"none", "no medicines", "nil"}
            else None
        ),
    )
    db.session.add(plan)
    Notification.push(
        pet.owner_id,
        f"New health plan for {pet.name}",
        f"{current_user.full_name} shared a health plan: {title}."
        + (f" Next visit: {next_visit.strftime('%d %b %Y')}." if next_visit else ""),
        category="health",
        link=url_for("health.dashboard", pet_id=pet.id),
    )
    db.session.commit()
    flash(f"Health plan shared with {pet.owner.full_name}.", "success")
    return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))


@vet_workspace_bp.route(
    "/patients/<int:pet_id>/health-record/today-record", methods=["POST"]
)
@role_required(UserRole.VET)
def add_today_health_record(pet_id: int):
    pet = _linked_patient_or_404(pet_id)
    visit_type = (request.form.get("visit_type") or "").strip() or "General check-up"
    findings = (request.form.get("findings") or "").strip()
    diagnosis = (request.form.get("diagnosis") or "").strip() or None
    suggestions = (request.form.get("suggestions") or "").strip() or None
    if not findings:
        flash("Enter general check-up details or instructions.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    title = f"{visit_type} · {date.today().strftime('%d %b %Y')}"
    record = MedicalRecord(
        pet_id=pet.id,
        vet_id=current_user.id,
        record_type=RecordType.EXAM,
        title=title,
        record_date=date.today(),
        vet_name=current_user.full_name,
        findings=findings,
        diagnosis=diagnosis,
        summary=suggestions or findings,
        shared_with_owner=True,
    )
    db.session.add(record)
    Notification.push(
        pet.owner_id,
        f"Today's health record for {pet.name}",
        f"{current_user.full_name} added a {visit_type.lower()} record for {pet.name}.",
        category="health",
        link=url_for("adopter.pet_health", pet_id=pet.id),
    )
    db.session.commit()
    flash("Today's health record saved and shared with the owner.", "success")
    return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))


@vet_workspace_bp.route(
    "/patients/<int:pet_id>/health-record/book-visit", methods=["POST"]
)
@role_required(UserRole.VET)
def book_patient_visit(pet_id: int):
    pet = _linked_patient_or_404(pet_id)
    visit_type = (request.form.get("visit_type") or "").strip() or "General check-up"
    date_value = (request.form.get("visit_date") or "").strip()
    time_value = (request.form.get("visit_time") or "").strip()
    try:
        visit_date = date.fromisoformat(date_value)
        visit_time = time.fromisoformat(time_value)
    except ValueError:
        flash("Choose a valid visit date and time.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    if datetime.combine(visit_date, visit_time, tzinfo=timezone.utc) < datetime.now(timezone.utc):
        flash("The visit must be scheduled in the future.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    scheduled_for = datetime.combine(visit_date, visit_time, tzinfo=timezone.utc)
    appointment = Appointment(
        kind=AppointmentKind.VET_VISIT,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=scheduled_for,
        vet_id=current_user.id,
        user_id=pet.owner_id,
        service=visit_type,
        note=f"{pet.name} · {pet.public_pet_id}",
        adopter_confirmed=False,
    )
    db.session.add(appointment)
    Notification.push(
        pet.owner_id,
        f"New visit booked for {pet.name}",
        f"{current_user.full_name} booked a {visit_type} visit on "
        f"{visit_date.strftime('%d %b %Y')} at {visit_time.strftime('%I:%M %p')}.",
        category="appointments",
        link=url_for("adopter.appointments"),
    )
    db.session.commit()
    flash("Visit booked and shared with the owner.", "success")
    return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))


@vet_workspace_bp.route(
    "/patients/<int:pet_id>/health-record/book-surgery", methods=["POST"]
)
@role_required(UserRole.VET)
def book_patient_surgery(pet_id: int):
    pet = _linked_patient_or_404(pet_id)
    title = (request.form.get("title") or "").strip()
    date_value = (request.form.get("surgery_date") or "").strip()
    time_value = (request.form.get("surgery_time") or "").strip()
    try:
        surgery_date = date.fromisoformat(date_value)
        surgery_time = time.fromisoformat(time_value)
    except ValueError:
        flash("Enter a valid surgery title, date and time.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    if not title:
        flash("Enter the surgery title.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    scheduled_for = datetime.combine(surgery_date, surgery_time, tzinfo=timezone.utc)
    record = MedicalRecord(
        pet_id=pet.id,
        vet_id=current_user.id,
        record_type=RecordType.SURGERY,
        title=title,
        record_date=surgery_date,
        vet_name=current_user.full_name,
        findings=f"Scheduled surgery at {surgery_time.strftime('%I:%M %p')}",
        shared_with_owner=True,
    )
    appointment = Appointment(
        kind=AppointmentKind.VET_VISIT,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=scheduled_for,
        vet_id=current_user.id,
        user_id=pet.owner_id,
        service="Surgery",
        note=f"{pet.name} · {pet.public_pet_id} · {title}",
    )
    db.session.add_all([record, appointment])
    Notification.push(
        pet.owner_id,
        f"Surgery scheduled for {pet.name}",
        f"{title} is scheduled on {surgery_date.strftime('%d %b %Y')} "
        f"at {surgery_time.strftime('%I:%M %p')}.",
        category="appointments",
        link=url_for("adopter.appointments"),
    )
    db.session.commit()
    flash("Surgery booked and shared with the owner.", "success")
    return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))


@vet_workspace_bp.route(
    "/patients/<int:pet_id>/health-record/lab-report", methods=["POST"]
)
@role_required(UserRole.VET)
def add_patient_lab_report(pet_id: int):
    pet = _linked_patient_or_404(pet_id)
    title = (request.form.get("title") or "").strip()
    report_file = save_image(request.files.get("lab_report"), folder="lab-reports")
    if not title or not report_file:
        flash("Enter a lab report title and choose the report file.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    record = MedicalRecord(
        pet_id=pet.id,
        vet_id=current_user.id,
        record_type=RecordType.LAB,
        title=title,
        record_date=date.today(),
        vet_name=current_user.full_name,
        attachments=[report_file],
        shared_with_owner=True,
    )
    db.session.add(record)
    Notification.push(
        pet.owner_id,
        f"Lab report for {pet.name}",
        f"{current_user.full_name} shared a lab report: {title}.",
        category="health",
        link=url_for("adopter.pet_health", pet_id=pet.id),
    )
    db.session.commit()
    flash("Lab report shared with the owner.", "success")
    return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))


@vet_workspace_bp.route(
    "/patients/<int:pet_id>/health-record/prescription", methods=["POST"]
)
@role_required(UserRole.VET)
def add_patient_prescription(pet_id: int):
    pet = _linked_patient_or_404(pet_id)
    medicines_list = [
        value.strip()
        for value in request.form.getlist("medicine_name")
        if value and value.strip()
    ]
    medicines = ", ".join(medicines_list)
    days_value = (request.form.get("days") or "").strip()
    timing = request.form.getlist("timing")
    if not medicines or not days_value:
        flash("Enter the medicine name and number of days.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    try:
        days = int(days_value)
    except ValueError:
        days = 0
    if days < 1:
        flash("Enter a valid number of days.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    timing_text = ", ".join(timing) if timing else "As directed"
    start_on = date.today()
    end_on = start_on + timedelta(days=days - 1)
    title = f"Prescription · {medicines}"
    plan = HealthPlan(
        pet_id=pet.id,
        vet_id=current_user.id,
        title=title,
        instructions=f"{medicines}\nTiming: {timing_text}\nDuration: {days} day(s)",
        prescribed_medicines=medicines,
        prescription_start_on=start_on,
        prescription_end_on=end_on,
    )
    record = MedicalRecord(
        pet_id=pet.id,
        vet_id=current_user.id,
        record_type=RecordType.PRESCRIPTION,
        title=title,
        record_date=start_on,
        vet_name=current_user.full_name,
        findings=f"Timing: {timing_text}",
        summary=f"{medicines} for {days} day(s)",
        shared_with_owner=True,
    )
    db.session.add_all([plan, record])
    Notification.push(
        pet.owner_id,
        f"Prescription for {pet.name}",
        f"{current_user.full_name} prescribed {medicines} for {days} day(s), "
        f"{timing_text.lower()}.",
        category="health",
        link=url_for("adopter.pet_health", pet_id=pet.id),
    )
    db.session.commit()
    flash("Prescription shared with the owner.", "success")
    return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))


@vet_workspace_bp.route("/patients/<int:appt_id>")
@role_required(UserRole.VET)
def patient_detail(appt_id: int):
    appt = db.session.get(Appointment, appt_id)
    if appt is None or appt.vet_id != current_user_id():
        abort(404)
    # Other visits for the same patient (pet or owner).
    history = db.session.scalars(
        db.select(Appointment)
        .filter(
            Appointment.vet_id == current_user_id(),
            Appointment.user_id == appt.user_id,
        )
        .order_by(Appointment.scheduled_for.desc())
    ).all()
    owner = db.session.get(User, appt.user_id) if appt.user_id else None
    pet_label = _appointment_pet_labels([appt])[appt.id]
    return render_template(
        "vet/patient_detail.html",
        appt=appt,
        pet_label=pet_label,
        owner=owner,
        history=history,
        active_nav="patients",
    )
