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
from ..models.reminder import Notification
from ..models.review import Review, ReviewTarget
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
    today = date.today()
    active_appointments = [
        appointment
        for appointment in appts
        if appointment.status != AppointmentStatus.CANCELLED
    ]
    todays = [
        appointment
        for appointment in active_appointments
        if _aware(appointment.scheduled_for).astimezone().date() == today
    ]
    patients = db.session.scalar(
        db.select(db.func.count())
        .select_from(VetPatient)
        .filter_by(vet_id=current_user.id)
    ) or 0

    current_month = today.replace(day=1)
    months = []
    for offset in range(5, -1, -1):
        month_number = current_month.month - offset
        year = current_month.year + (month_number - 1) // 12
        month_number = (month_number - 1) % 12 + 1
        months.append(date(year, month_number, 1))
    month_counts = {(month.year, month.month): 0 for month in months}
    for appointment in active_appointments:
        scheduled_on = _aware(appointment.scheduled_for).astimezone().date()
        month_key = (scheduled_on.year, scheduled_on.month)
        if month_key in month_counts:
            month_counts[month_key] += 1

    profile = current_user.vet_profile[0] if current_user.vet_profile else None

    return render_template(
        "vet/dashboard.html",
        todays=todays,
        appointment_count=len(active_appointments),
        patients=patients,
        is_verified=profile.is_verified if profile else False,
        month_labels=[month.strftime("%b") for month in months],
        month_values=[month_counts[(month.year, month.month)] for month in months],
        pet_labels=_appointment_pet_labels(todays),
        now=now,
        active_nav="dashboard",
    )


@vet_workspace_bp.route("/reviews")
@role_required(UserRole.VET)
def reviews():
    profile = current_user.vet_profile[0] if current_user.vet_profile else None
    items = []
    if profile is not None:
        items = db.session.scalars(
            db.select(Review)
            .filter_by(
                target_type=ReviewTarget.VET,
                target_id=profile.id,
                hidden=False,
            )
            .order_by(Review.created_at.desc())
        ).all()
    average_rating = (
        round(sum(review.rating for review in items) / len(items), 1)
        if items else 0
    )
    return render_template(
        "vet/reviews.html",
        reviews=items,
        average_rating=average_rating,
        total_reviews=len(items),
        clinic_name=(profile.clinic_name if profile else None) or "Vet account",
        active_nav="reviews",
    )


@vet_workspace_bp.route("/settings", methods=["GET", "POST"])
@role_required(UserRole.VET)
def settings():
    if request.method == "POST":
        if request.form.get("section") == "notifications":
            prefs = dict(current_user.prefs)
            for key in ("health_reminders", "vet_appointments"):
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
    prescription_records = [
        record for record in records
        if record.record_type == RecordType.PRESCRIPTION
        and not record.title.strip().casefold().startswith("consultation")
    ]
    past_records = [record for record in records if record.record_date <= today]
    past_health_records = [
        record for record in past_records
        if record.record_type not in {RecordType.PRESCRIPTION, RecordType.LAB, RecordType.SURGERY}
    ]
    prescription_plans = [
        plan
        for plan in db.session.scalars(
            db.select(HealthPlan)
            .filter(
                HealthPlan.pet_id == pet.id,
                HealthPlan.prescribed_medicines.is_not(None),
            )
            .order_by(HealthPlan.prescription_start_on.desc(), HealthPlan.id.desc())
        ).all()
        if plan.prescribed_medicines.strip().casefold()
        not in {"", "none", "no medicines", "nil"}
    ]
    past_prescription_plans = [
        plan for plan in prescription_plans
        if plan.prescription_end_on is not None
        and plan.prescription_end_on < today
    ]
    present_prescription_plans = [
        plan for plan in prescription_plans
        if plan.prescription_end_on is None or plan.prescription_end_on >= today
    ]
    plan_record_keys = {
        (
            plan.title.strip().casefold(),
            (plan.prescription_start_on or plan.created_at.date()).isoformat(),
        )
        for plan in prescription_plans
    }
    unmatched_prescription_records = [
        record for record in prescription_records
        if (record.title.strip().casefold(), record.record_date.isoformat())
        not in plan_record_keys
    ]
    past_prescriptions = [
        record for record in unmatched_prescription_records
        if record.record_date < today
    ]
    present_prescriptions = [
        record for record in unmatched_prescription_records
        if record.record_date >= today
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
        today_plans=today_plans,
        current_plans=current_plans,
        plans=plans,
        past_prescriptions=past_prescriptions,
        past_records=past_records,
        past_health_records=past_health_records,
        past_prescription_plans=past_prescription_plans,
        present_prescription_plans=present_prescription_plans,
        present_prescriptions=present_prescriptions,
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
    allowed_visit_types = {
        "General check-up",
        "Dental care",
        "Lab test",
        "Referral",
    }
    findings = (request.form.get("findings") or "").strip()
    diagnosis = (request.form.get("diagnosis") or "").strip() or None
    suggestions = (request.form.get("suggestions") or "").strip() or None
    if visit_type not in allowed_visit_types:
        flash("Choose a valid health record visit type.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
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
    "/patients/<int:pet_id>/health-record/vaccination", methods=["POST"]
)
@role_required(UserRole.VET)
def add_patient_vaccination(pet_id: int):
    pet = _linked_patient_or_404(pet_id)
    vaccine_name = (request.form.get("vaccine_name") or "").strip()
    date_value = (request.form.get("vaccination_date") or "").strip()
    time_value = (request.form.get("vaccination_time") or "").strip()
    if not vaccine_name or len(vaccine_name) > 66:
        flash("Enter a vaccination name of 66 characters or fewer.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    try:
        vaccination_date = date.fromisoformat(date_value)
        vaccination_time = time.fromisoformat(time_value)
    except ValueError:
        flash("Choose a valid vaccination date and time.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
    scheduled_for = datetime.combine(
        vaccination_date, vaccination_time, tzinfo=timezone.utc
    )
    if scheduled_for <= datetime.now(timezone.utc):
        flash("The vaccination must be scheduled in the future.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))

    vaccination = Vaccination(
        pet_id=pet.id,
        name=vaccine_name,
        due_on=vaccination_date,
    )
    appointment = Appointment(
        kind=AppointmentKind.VET_VISIT,
        status=AppointmentStatus.CONFIRMED,
        scheduled_for=scheduled_for,
        vet_id=current_user.id,
        user_id=pet.owner_id,
        service=f"Vaccination · {vaccine_name}",
        note=f"{pet.name} · {pet.public_pet_id}",
        adopter_confirmed=False,
    )
    db.session.add_all([vaccination, appointment])
    Notification.push(
        pet.owner_id,
        f"Vaccination scheduled for {pet.name}",
        f"{vaccine_name} is scheduled for "
        f"{vaccination_date.strftime('%d %b %Y')} at "
        f"{vaccination_time.strftime('%I:%M %p')}.",
        category="health",
        link=url_for("adopter.pet_health", pet_id=pet.id),
    )
    db.session.commit()
    flash("Vaccination saved and shared with the owner.", "success")
    return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))


@vet_workspace_bp.route(
    "/patients/<int:pet_id>/health-record/book-visit", methods=["POST"]
)
@role_required(UserRole.VET)
def book_patient_visit(pet_id: int):
    pet = _linked_patient_or_404(pet_id)
    visit_type = (request.form.get("visit_type") or "").strip() or "General check-up"
    allowed_visit_types = {
        "General check-up",
        "Dental care",
        "Lab test",
        "Referral visit",
    }
    if visit_type not in allowed_visit_types:
        flash("Choose a valid visit type.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
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
    medicine_names = [value.strip() for value in request.form.getlist("medicine_name")]
    instructions = [value.strip() for value in request.form.getlist("instructions")]
    frequencies = [value.strip() for value in request.form.getlist("frequency")]
    stop_date_values = [value.strip() for value in request.form.getlist("stop_date")]
    if (
        not medicine_names
        or len(medicine_names) > 20
        or len(instructions) != len(medicine_names)
        or len(frequencies) != len(medicine_names)
        or len(stop_date_values) != len(medicine_names)
        or any(not name or len(name) > 120 for name in medicine_names)
        or any(len(f"Prescription · {name}") > 200 for name in medicine_names)
        or any(not text or len(text) > 1000 for text in instructions)
        or any(frequency not in {"Days", "Weekly", "Monthly"} for frequency in frequencies)
    ):
        flash("Complete the medicine name, instructions, frequency, and stop date for each prescription.", "warning")
        return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))

    allowed_timings = {"Morning", "Afternoon", "Evening", "Night"}
    prescription_details = []
    for index, (name, instruction, frequency, stop_date_value) in enumerate(
        zip(medicine_names, instructions, frequencies, stop_date_values)
    ):
        try:
            stop_date = date.fromisoformat(stop_date_value)
        except ValueError:
            flash("Enter a valid stop date for each prescription.", "warning")
            return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
        if stop_date < date.today():
            flash("A prescription stop date cannot be in the past.", "warning")
            return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
        timings = request.form.getlist(f"timing_{index}")
        if not timings or any(timing not in allowed_timings for timing in timings):
            flash("Choose at least one valid timing for each prescription.", "warning")
            return redirect(url_for("vet_workspace.patient_health_record", pet_id=pet.id))
        detail_text = (
            f"{name}\nInstructions: {instruction}\n"
            f"When to take it: {frequency}\nTiming: {', '.join(timings)}\n"
            f"Stop date: {stop_date.strftime('%d %b %Y')}"
        )
        prescription_details.append({
            "name": name,
            "stop_date": stop_date,
            "detail_text": detail_text,
        })

    start_on = date.today()
    prescriptions = []
    for prescription in prescription_details:
        name = prescription["name"]
        stop_date = prescription["stop_date"]
        detail_text = prescription["detail_text"]
        title = f"Prescription · {name}"
        plan = HealthPlan(
            pet_id=pet.id,
            vet_id=current_user.id,
            title=title,
            instructions=detail_text,
            prescribed_medicines=name,
            prescription_start_on=start_on,
            prescription_end_on=stop_date,
        )
        record = MedicalRecord(
            pet_id=pet.id,
            vet_id=current_user.id,
            record_type=RecordType.PRESCRIPTION,
            title=title,
            record_date=start_on,
            vet_name=current_user.full_name,
            findings=detail_text,
            summary=detail_text,
            shared_with_owner=True,
        )
        prescriptions.extend([plan, record])
    db.session.add_all(prescriptions)
    medicines = ", ".join(medicine_names)
    Notification.push(
        pet.owner_id,
        f"Prescription for {pet.name}",
        f"{current_user.full_name} prescribed {medicines}.",
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
