"""Adopter workspace: dashboard, My Adopted Pets, pet profile management (Task 22)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

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
from sqlalchemy import or_

from ..extensions import db
from ..models.application import Application, ApplicationStage, ReturnStatus
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
    VaccineStatus,
)
from ..models.lifestyle import ExpenseItem
from ..models.reminder import Notification
from ..models.review import FollowUp, FollowUpStatus
from ..models.vet import VetProfile
from ..services.storage import save_image

adopter_bp = Blueprint("adopter", __name__, url_prefix="/me")


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_completed_adoption(application: Application) -> bool:
    return (
        application.returned_at is None
        and (
            application.stage == ApplicationStage.COMPLETE
            or application.adopted_at is not None
            or application.owned_pet is not None
        )
    )


def _active_adoption_applications(applicant_id: int) -> list[Application]:
    return db.session.scalars(
        db.select(Application)
        .filter(
            Application.applicant_id == applicant_id,
            Application.stage.notin_([
                ApplicationStage.DRAFT,
                ApplicationStage.DECLINED,
                ApplicationStage.COMPLETE,
            ]),
            Application.return_status.is_(None),
        )
        .order_by(Application.created_at.desc())
    ).all()


@adopter_bp.route("/adoptions")
@login_required
def adoptions():
    from ..services.scheduler import run_due_reminders
    run_due_reminders(current_app._get_current_object())
    active_applications = _active_adoption_applications(current_user.id)
    tab = request.args.get("tab")
    if tab is None:
        tab = "applications" if active_applications else "adopted"
    if tab not in {"applications", "adopted", "returns", "declined", "cancelled"}:
        tab = "adopted"

    all_applications = db.session.scalars(
        db.select(Application)
        .filter(Application.applicant_id == current_user.id)
        .order_by(Application.adopted_at.desc(), Application.created_at.desc())
    ).all()
    adopted_applications = [
        app for app in all_applications
        if _is_completed_adoption(app) and app.return_status is None
    ]
    returned_applications = [
        app for app in all_applications
        if app.returned_at is not None
    ]
    declined_applications = [
        app for app in all_applications
        if app.stage == ApplicationStage.DECLINED and not app.applicant_cancelled
    ]
    cancelled_applications = [
        app for app in all_applications
        if app.stage == ApplicationStage.DECLINED and app.applicant_cancelled
    ]
    owned_adoptions = db.session.scalars(
        db.select(OwnedPet)
        .filter(
            OwnedPet.owner_id == current_user.id,
            OwnedPet.adopted_on.is_not(None),
        )
        .order_by(OwnedPet.adopted_on.desc(), OwnedPet.id.desc())
    ).all()
    application_owned_pet_ids = {
        app.owned_pet.id
        for app in adopted_applications
        if app.owned_pet is not None
    }
    legacy_owned_adoptions = [
        pet for pet in owned_adoptions
        if pet.id not in application_owned_pet_ids
    ]
    now = datetime.now(timezone.utc)
    returnable_app_ids = {
        app.id for app in adopted_applications
        if app.return_status is None
        and app.stage == ApplicationStage.COMPLETE
        and app.adopted_at is not None
        and _aware(app.adopted_at) <= now <= _aware(app.adopted_at) + timedelta(days=30)
    }
    return render_template(
        "adopter/adoptions.html",
        tab=tab,
        active_applications=active_applications,
        adopted_applications=adopted_applications,
        legacy_owned_adoptions=legacy_owned_adoptions,
        returned_applications=returned_applications,
        declined_applications=declined_applications,
        cancelled_applications=cancelled_applications,
        returnable_app_ids=returnable_app_ids,
        active_nav="adoptions",
    )


def _care_plans(pet: OwnedPet) -> dict:
    schedule = pet.care_schedule
    if isinstance(schedule, dict):
        diet_plan = schedule.get("diet_plan", [])
        routine_plan = schedule.get("routine_plan", "")
        return {
            "diet_plan": diet_plan if isinstance(diet_plan, list) else [],
            "routine_plan": routine_plan if isinstance(routine_plan, str) else "",
            "diet_plans": schedule.get("diet_plans", [])
            if isinstance(schedule.get("diet_plans"), list) else [],
            "routine_plans": schedule.get("routine_plans", [])
            if isinstance(schedule.get("routine_plans"), list) else [],
        }

    legacy_rows = schedule if isinstance(schedule, list) else []
    diet_plan = [
        {
            "food": str(item.get("food") or ""),
            "quantity": "",
            "time": str(item.get("time") or ""),
        }
        for item in legacy_rows
        if isinstance(item, dict)
    ]
    routine_plan = "\n".join(
        " · ".join(
            value for value in (item.get("activity"), item.get("notes")) if value
        )
        for item in legacy_rows
        if isinstance(item, dict)
        and (item.get("activity") or item.get("notes"))
    )
    return {
        "diet_plan": diet_plan,
        "routine_plan": routine_plan,
        "diet_plans": [],
        "routine_plans": [],
    }


@adopter_bp.route("/dashboard")
@login_required
def dashboard():
    from ..services.scheduler import run_due_reminders
    run_due_reminders(current_app._get_current_object())
    pets = db.session.scalars(
        db.select(OwnedPet)
        .outerjoin(Application, OwnedPet.application_id == Application.id)
        .filter(
            OwnedPet.owner_id == current_user.id,
            or_(OwnedPet.application_id.is_(None), Application.returned_at.is_(None)),
        )
    ).all()

    adoption_applications = _active_adoption_applications(current_user.id)
    return_applications = db.session.scalars(
        db.select(Application)
        .filter(
            Application.applicant_id == current_user.id,
            Application.return_status.is_not(None),
            Application.returned_at.is_(None),
        )
        .order_by(Application.return_requested_at.desc(), Application.created_at.desc())
    ).all()

    now = datetime.now(timezone.utc)
    appointments = db.session.scalars(
        db.select(Appointment)
        .filter(
            Appointment.user_id == current_user.id,
            Appointment.status.in_(
                [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]
            ),
        )
        .order_by(Appointment.scheduled_for.asc())
    ).all()
    appointments = [a for a in appointments if _aware(a.scheduled_for) >= now]
    today_appointments = [
        appointment
        for appointment in appointments
        if _aware(appointment.scheduled_for).astimezone().date()
        == now.astimezone().date()
    ]
    today_appointments = [
        {
            "appointment": appointment,
            "local_time": _aware(appointment.scheduled_for).astimezone(),
        }
        for appointment in today_appointments
    ]
    expenses = db.session.scalars(
        db.select(ExpenseItem).filter_by(owner_id=current_user.id)
    ).all()
    monthly_spend = sum(item.monthly_amount for item in expenses)
    stats = {
        "pets": len(pets),
        "applications": len(adoption_applications) + len(return_applications),
        "appointments": len(appointments),
        "spend": f"₹{monthly_spend:,.0f}",
    }
    return render_template(
        "adopter/dashboard.html",
        user=current_user,
        pets=pets,
        adoption_applications=adoption_applications,
        return_applications=return_applications,
        today_appointments=today_appointments,
        ReturnStatus=ReturnStatus,
        stats=stats,
        active_nav="dashboard",
    )


@adopter_bp.route("/appointments")
@login_required
def appointments():
    appts = db.session.scalars(
        db.select(Appointment)
        .filter(
            Appointment.user_id == current_user.id,
            Appointment.kind == AppointmentKind.VET_VISIT,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
        .order_by(Appointment.scheduled_for.desc())
    ).all()
    now = datetime.now(timezone.utc)
    upcoming = [a for a in appts if _aware(a.scheduled_for) >= now]
    past = [a for a in appts if _aware(a.scheduled_for) < now]
    upcoming.sort(key=lambda appt: _aware(appt.scheduled_for))
    past.sort(key=lambda appt: _aware(appt.scheduled_for), reverse=True)

    categories = [
        ("all", "All"),
        ("general", "General check-up"),
        ("vaccination", "Vaccination"),
        ("dental", "Dental"),
        ("grooming", "Grooming"),
        ("video", "Video consult"),
    ]
    category = request.args.get("category", "all")
    if category not in {key for key, _ in categories}:
        category = "all"

    def matches_category(appt):
        if category == "all":
            return True
        service = (appt.service or "").strip().casefold()
        return (
            (category == "general" and service in ("general", "general check-up"))
            or (category == "vaccination" and service == "vaccination")
            or (category == "dental" and service == "dental")
            or (category == "grooming" and service == "grooming")
            or (category == "video" and "video" in service)
        )

    filtered_upcoming = [a for a in upcoming if matches_category(a)]
    filtered_past = [a for a in past if matches_category(a)]

    grouped_upcoming = {}
    for appt in filtered_upcoming:
        service = (appt.service or "Other").strip()
        grouped_upcoming.setdefault(service, []).append(appt)

    return render_template(
        "adopter/appointments.html",
        upcoming=filtered_upcoming,
        upcoming_grouped=grouped_upcoming,
        past=filtered_past,
        categories=categories,
        category=category,
        active_nav="appointments",
    )


@adopter_bp.route("/appointments/<int:appt_id>/cancel", methods=["POST"])
@login_required
def cancel_appointment(appt_id: int):
    appt = db.session.get(Appointment, appt_id)
    if (
        appt is None
        or appt.user_id != current_user.id
        or appt.kind != AppointmentKind.VET_VISIT
    ):
        abort(404)
    if appt.status in (AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED):
        flash("This appointment cannot be cancelled.", "info")
        return redirect(url_for("adopter.appointments"))

    now = datetime.now(timezone.utc)
    if _aware(appt.scheduled_for) < now:
        flash("Past appointments cannot be cancelled.", "info")
        return redirect(url_for("adopter.appointments"))

    appt.status = AppointmentStatus.CANCELLED
    if appt.vet_id:
        Notification.push(
            appt.vet_id,
            "Vet appointment cancelled",
            f"{current_user.full_name} cancelled {appt.service or 'the appointment'} "
            f"for {appt.note or 'their pet'} on "
            f"{_aware(appt.scheduled_for).strftime('%d %b %Y at %I:%M %p UTC')}.",
            category="appointments",
            link=url_for("vet_workspace.appointments"),
        )
    db.session.commit()
    flash("Appointment cancelled successfully.", "success")
    return redirect(url_for("adopter.appointments"))


@adopter_bp.route("/followups")
@login_required
def followups():
    return redirect(url_for("adopter.adoptions", tab="adopted"))


@adopter_bp.route("/returns")
@login_required
def returns():
    return redirect(url_for("adopter.adoptions", tab="returns"))


@adopter_bp.route("/followups/<int:fu_id>/respond", methods=["POST"])
@login_required
def respond_followup(fu_id: int):
    fu = db.session.get(FollowUp, fu_id)
    if fu is None or fu.application.applicant_id != current_user.id:
        abort(404)
    now = datetime.now(timezone.utc)
    if (
        fu.application.returned_at is not None
        or fu.status != FollowUpStatus.DUE
        or _aware(fu.due_on) > now
    ):
        flash("This check-in is not currently available for a response.", "warning")
        return redirect(url_for("adopter.followups"))

    outcome = request.form.get("outcome")
    response_text = (request.form.get("response") or "").strip()
    if outcome not in {"done", "needs_support"}:
        flash("Choose whether your pet is settling in or needs support.", "warning")
        return redirect(url_for("adopter.followups"))
    if len(response_text) > 1000:
        flash("Your check-in response must be 1,000 characters or fewer.", "warning")
        return redirect(url_for("adopter.followups"))

    fu.status = (
        FollowUpStatus.DONE if outcome == "done" else FollowUpStatus.NEEDS_SUPPORT
    )
    fu.response = response_text or None
    application = fu.application
    required_milestones = {"7 days", "15 days", "30 days"}
    completed_milestones = {
        followup.milestone
        for followup in application.followups
        if followup.status == FollowUpStatus.DONE
    }
    if (
        application.owned_pet is None
        and application.returned_at is None
        and application.return_status is None
        and required_milestones.issubset(completed_milestones)
    ):
        listed_pet = application.pet
        db.session.add(
            OwnedPet(
                owner_id=application.applicant_id,
                application_id=application.id,
                name=listed_pet.name,
                species=listed_pet.species.label,
                breed=listed_pet.breed,
                sex=listed_pet.sex.label,
                weight_kg=listed_pet.weight_kg,
                photo_url=listed_pet.primary_photo,
                personality_tags=list(listed_pet.personality_tags or []),
                adopted_on=(
                    _aware(application.adopted_at).date()
                    if application.adopted_at
                    else date.today()
                ),
            )
        )
    db.session.commit()
    from ..services.notify import notify

    notify(
        fu.application.pet.shelter.owner,
        title=f"{fu.milestone} adoption check-in: {fu.application.pet.name}",
        body=(
            f"{current_user.full_name} reports the pet is settling in."
            if outcome == "done"
            else f"{current_user.full_name} says the pet needs support."
        ),
        category="adoption",
        link=url_for("shelter_ops.followups"),
    )
    db.session.commit()
    flash("Your check-in was shared with the shelter.", "success")
    return redirect(url_for("adopter.followups"))


@adopter_bp.route("/applications/<int:app_id>/return", methods=["POST"])
@login_required
def return_adopted_pet(app_id: int):
    application = db.session.get(Application, app_id)
    if (
        application is None
        or application.applicant_id != current_user.id
        or application.stage != ApplicationStage.COMPLETE
    ):
        abort(404)
    if application.return_status is not None:
        flash("A return process has already been started for this pet.", "info")
        return redirect(url_for("adopter.returns"))

    adopted_at = application.adopted_at
    now = datetime.now(timezone.utc)
    if adopted_at is None or now < _aware(adopted_at) or now > _aware(adopted_at) + timedelta(days=30):
        flash("Adopter returns are available only during the first 30 days after adoption.", "warning")
        return redirect(url_for("adopter.returns"))
    reason = (request.form.get("reason") or "").strip()
    if not reason or len(reason) > 1000:
        flash("Enter a return reason of 1 to 1,000 characters.", "warning")
        return redirect(url_for("adopter.returns"))

    application.submit_return(reason, now)
    db.session.commit()
    from ..services.notify import notify

    notify(
        application.pet.shelter.owner,
        title=f"Return submitted for {application.pet.name}",
        body=f"{current_user.full_name} requested a return within the 30-day adoption period.",
        category="adoption",
        link=url_for("shelter_ops.returns"),
    )
    db.session.commit()
    flash(f"Your return request for {application.pet.name} was sent to the shelter.", "success")
    return redirect(url_for("adopter.adoptions", tab="returns"))


@adopter_bp.route("/pets")
@login_required
def my_pets():
    from ..services.scheduler import run_due_reminders
    run_due_reminders(current_app._get_current_object())
    pets = db.session.scalars(
        db.select(OwnedPet)
        .outerjoin(Application, OwnedPet.application_id == Application.id)
        .filter(
            OwnedPet.owner_id == current_user.id,
            or_(OwnedPet.application_id.is_(None), Application.returned_at.is_(None)),
        )
    ).all()
    return render_template("adopter/my_pets.html", pets=pets, active_nav="mypets")


@adopter_bp.route("/pets/add", methods=["POST"])
@login_required
def add_pet():
    pet = OwnedPet(
        owner_id=current_user.id,
        name=(request.form.get("name") or "New pet").strip(),
        species=(request.form.get("species") or "").strip() or None,
    )
    db.session.add(pet)
    db.session.commit()
    flash(f"{pet.name} added. Complete their profile below.", "success")
    return redirect(url_for("adopter.pet_profile", pet_id=pet.id))


def _owned_or_404(pet_id: int) -> OwnedPet:
    pet = db.session.get(OwnedPet, pet_id)
    if (
        pet is None
        or pet.owner_id != current_user.id
        or (pet.application is not None and pet.application.returned_at is not None)
    ):
        abort(404)
    return pet


@adopter_bp.route("/pets/<int:pet_id>", methods=["GET", "POST"])
@login_required
def pet_profile(pet_id: int):
    pet = _owned_or_404(pet_id)
    tab = request.args.get("tab", "basic")
    if tab == "documents":
        return redirect(url_for("adopter.pet_profile", pet_id=pet.id))
    if tab not in {"basic", "diet"}:
        tab = "basic"
    edit_mode = request.args.get("edit") == "1"

    if request.method == "POST":
        section = request.form.get("section", "basic")
        if section == "basic":
            pet.name = (request.form.get("name") or pet.name).strip()
            pet.species = (request.form.get("species") or "").strip() or None
            pet.breed = (request.form.get("breed") or "").strip() or None
            pet.sex = (request.form.get("sex") or "").strip() or None
            pet.microchip_id = (request.form.get("microchip_id") or "").strip() or None
            pet.primary_vet = (request.form.get("primary_vet") or "").strip() or None
            dob = request.form.get("date_of_birth")
            if dob:
                try:
                    pet.date_of_birth = date.fromisoformat(dob)
                except ValueError:
                    pass
            weight = request.form.get("weight_kg")
            if weight:
                try:
                    pet.weight_kg = float(weight)
                except ValueError:
                    pass
            pet.personality_tags = request.form.getlist("personality_tags")
            photo = request.files.get("photo")
            if photo and photo.filename:
                url = save_image(photo, folder="pets")
                if url:
                    pet.photo_url = url
        elif section == "diet_plan":
            times = request.form.getlist("diet_time")
            foods = request.form.getlist("diet_food")
            quantities = request.form.getlist("diet_quantity")
            plans = []
            for at, food, quantity in zip(times, foods, quantities):
                at, food, quantity = at.strip(), food.strip(), quantity.strip()
                if not any((at, food, quantity)):
                    continue
                if not food:
                    flash("Enter a food for each diet plan row.", "warning")
                    return redirect(url_for(
                        "adopter.pet_profile", pet_id=pet.id, tab="diet", edit_diet=1
                    ))
                if at:
                    try:
                        datetime.strptime(at, "%H:%M")
                    except ValueError:
                        flash("Enter a valid time for each diet plan row.", "warning")
                        return redirect(url_for(
                            "adopter.pet_profile", pet_id=pet.id, tab="diet", edit_diet=1
                        ))
                plans.append({"food": food, "quantity": quantity, "time": at})
            diet_notes = (request.form.get("diet_note") or "").strip()
            if len(diet_notes) > 2000:
                flash("Diet notes must be 2,000 characters or fewer.", "warning")
                return redirect(url_for(
                    "adopter.pet_profile", pet_id=pet.id, tab="diet", edit_diet=1
                ))
            care_plans = _care_plans(pet)
            care_plans["diet_plan"] = plans
            pet.care_schedule = care_plans
            pet.diet_note = diet_notes or None
        elif section == "routine_plan":
            routine_plan = (request.form.get("routine_plan") or "").strip()
            if len(routine_plan) > 4000:
                flash("Routine plans must be 4,000 characters or fewer.", "warning")
                return redirect(url_for(
                    "adopter.pet_profile", pet_id=pet.id, tab="diet", edit_routine=1
                ))
            care_plans = _care_plans(pet)
            care_plans["routine_plan"] = routine_plan
            pet.care_schedule = care_plans
        elif section == "add_diet_plan":
            name = (request.form.get("diet_plan_name") or "").strip()
            times = request.form.getlist("diet_time")
            foods = request.form.getlist("diet_food")
            quantities = request.form.getlist("diet_quantity")
            meals = []
            for at, food, quantity in zip(times, foods, quantities):
                at, food, quantity = at.strip(), food.strip(), quantity.strip()
                if not any((at, food, quantity)):
                    continue
                if not food:
                    flash("Enter a food for each diet plan row.", "warning")
                    return redirect(url_for(
                        "adopter.pet_profile", pet_id=pet.id, tab="diet", add_diet=1
                    ))
                if at:
                    try:
                        datetime.strptime(at, "%H:%M")
                    except ValueError:
                        flash("Enter a valid time for each diet plan row.", "warning")
                        return redirect(url_for(
                            "adopter.pet_profile", pet_id=pet.id, tab="diet", add_diet=1
                        ))
                meals.append({"food": food, "quantity": quantity, "time": at})
            notes = (request.form.get("diet_plan_note") or "").strip()
            if not name or len(name) > 100:
                flash("Enter a diet plan name of 1 to 100 characters.", "warning")
                return redirect(url_for(
                    "adopter.pet_profile", pet_id=pet.id, tab="diet", add_diet=1
                ))
            if not meals:
                flash("Add at least one meal to the diet plan.", "warning")
                return redirect(url_for(
                    "adopter.pet_profile", pet_id=pet.id, tab="diet", add_diet=1
                ))
            if len(notes) > 2000:
                flash("Diet notes must be 2,000 characters or fewer.", "warning")
                return redirect(url_for(
                    "adopter.pet_profile", pet_id=pet.id, tab="diet", add_diet=1
                ))
            care_plans = _care_plans(pet)
            care_plans["diet_plans"].append(
                {"name": name, "meals": meals, "notes": notes}
            )
            pet.care_schedule = care_plans
        elif section == "add_routine_plan":
            name = (request.form.get("routine_plan_name") or "").strip()
            details = (request.form.get("routine_plan_details") or "").strip()
            if not name or len(name) > 100:
                flash("Enter a routine plan name of 1 to 100 characters.", "warning")
                return redirect(url_for(
                    "adopter.pet_profile", pet_id=pet.id, tab="diet", add_routine=1
                ))
            if not details or len(details) > 4000:
                flash("Enter routine details of 1 to 4,000 characters.", "warning")
                return redirect(url_for(
                    "adopter.pet_profile", pet_id=pet.id, tab="diet", add_routine=1
                ))
            care_plans = _care_plans(pet)
            care_plans["routine_plans"].append({"name": name, "details": details})
            pet.care_schedule = care_plans
        else:
            flash("That profile section is not available.", "warning")
            return redirect(url_for("adopter.pet_profile", pet_id=pet.id))
        db.session.commit()
        flash("Profile saved.", "success")
        return redirect(url_for(
            "adopter.pet_profile",
            pet_id=pet.id,
            tab="diet" if section in {
                "diet_plan", "routine_plan", "add_diet_plan", "add_routine_plan"
            } else section,
        ))

    return render_template(
        "adopter/pet_profile.html",
        pet=pet,
        tab=tab,
        edit_mode=edit_mode,
        care_plans=_care_plans(pet),
        edit_diet=request.args.get("edit_diet") == "1",
        edit_routine=request.args.get("edit_routine") == "1",
        add_diet=request.args.get("add_diet") == "1",
        add_routine=request.args.get("add_routine") == "1",
        personality_options=["Calm", "Affectionate", "Playful", "Indoor", "Shy with strangers"],
        primary_vets=db.session.scalars(
            db.select(VetProfile)
            .filter_by(is_verified=True)
            .order_by(VetProfile.display_name)
        ).all(),
        active_nav="mypets",
    )


@adopter_bp.route("/pets/<int:pet_id>/health")
@login_required
def pet_health(pet_id: int):
    """View-only health page: vaccinations (past + upcoming) and medical records."""
    pet = _owned_or_404(pet_id)
    today = date.today()

    # Deduplicate vaccinations: keep only the most recent record per vaccine name.
    all_vaccs = sorted(pet.vaccinations, key=lambda v: (v.due_on or date.max))
    seen_vacc_names: set[str] = set()
    unique_vaccs = []
    for v in all_vaccs:
        key = v.name.strip().lower()
        if key not in seen_vacc_names:
            seen_vacc_names.add(key)
            unique_vaccs.append(v)

    past_vaccs = [v for v in unique_vaccs if v.status == VaccineStatus.DONE]
    upcoming_vaccs = [v for v in unique_vaccs if v.status != VaccineStatus.DONE]

    # Only show records explicitly shared by a veterinarian with the owner.
    shared_records = [r for r in pet.medical_records if r.shared_with_owner]
    primary_vet_name = (pet.primary_vet or "").split(",", 1)[0].strip()
    primary_vet_profile = next(
        (
            vet
            for vet in db.session.scalars(
                db.select(VetProfile).filter_by(is_verified=True)
            ).all()
            if vet.display_name.casefold() == primary_vet_name.casefold()
        ),
        None,
    )

    # Deduplicate medical records: keep only unique (title, date) combinations.
    seen_records: set[tuple] = set()
    unique_records = []
    for r in sorted(shared_records, key=lambda r: r.record_date, reverse=True):
        key = (r.title.strip().lower(), r.record_date.isoformat())
        if key not in seen_records:
            seen_records.add(key)
            unique_records.append(r)

    past_records = [r for r in unique_records if r.record_date <= today]
    upcoming_records = [r for r in unique_records if r.record_date > today]
    past_health_records = [
        r for r in past_records
        if r.record_type not in {RecordType.PRESCRIPTION, RecordType.LAB, RecordType.SURGERY}
    ]
    past_checkup_count = sum(
        1 for r in past_records
        if r.record_type in {RecordType.CONSULTATION, RecordType.EXAM}
    )
    upcoming_checkup_count = sum(
        1 for r in upcoming_records
        if r.record_type in {RecordType.CONSULTATION, RecordType.EXAM}
    )
    lab_reports = [
        r for r in unique_records
        if r.record_type == RecordType.LAB
    ]
    surgery_count = sum(
        1 for r in unique_records
        if r.record_type == RecordType.SURGERY and r.record_date <= today
    )
    upcoming_surgery_count = sum(
        1 for r in upcoming_records
        if r.record_type == RecordType.SURGERY
    )
    health_plans = db.session.scalars(
        db.select(HealthPlan)
        .where(HealthPlan.pet_id == pet.id)
        .order_by(HealthPlan.next_visit_on.asc().nullslast(), HealthPlan.id.desc())
    ).all()
    prescription_items = []
    for plan in health_plans:
        if not plan.prescribed_medicines:
            continue
        medicine_text = plan.prescribed_medicines.strip().casefold()
        if medicine_text in {"", "none", "no medicines", "nil"}:
            continue
        title_text = plan.title.strip().casefold()
        is_prescription = (
            title_text.startswith("prescription")
            or plan.prescription_start_on is not None
            or plan.prescription_end_on is not None
            or medicine_text not in {"", "none", "no medicines", "nil"}
        )
        if not is_prescription:
            continue
        plan_date = (
            plan.prescription_start_on
            if plan.prescription_start_on is not None
            else plan.created_at.date()
        )
        end_date = plan.prescription_end_on or plan_date
        prescription_items.append({
            "title": plan.title,
            "medicines": plan.prescribed_medicines,
            "instructions": plan.instructions,
            "date": plan_date,
            "end_date": end_date,
        })
    for record in unique_records:
        if (
            record.summary
            and record.record_type == RecordType.PRESCRIPTION
            and not record.title.strip().casefold().startswith("consultation")
        ):
            prescription_items.append({
                "title": record.title,
                "medicines": record.summary,
                "instructions": record.findings,
                "date": record.record_date,
                "end_date": record.record_date,
            })

    seen_prescriptions: set[tuple] = set()
    unique_prescriptions = []
    for item in sorted(
        prescription_items,
        key=lambda item: item["date"],
        reverse=True,
    ):
        key = (
            item["title"].strip().casefold(),
            item["date"].isoformat(),
        )
        if key not in seen_prescriptions:
            seen_prescriptions.add(key)
            unique_prescriptions.append(item)
    past_prescriptions = [
        item for item in unique_prescriptions
        if item["end_date"] < today
    ]
    present_prescriptions = [
        item for item in unique_prescriptions
        if item["end_date"] >= today and item["date"] <= today
    ]
    upcoming_appointments = db.session.scalars(
        db.select(Appointment)
        .where(
            Appointment.user_id == current_user.id,
            Appointment.status != AppointmentStatus.CANCELLED,
            Appointment.scheduled_for >= datetime.now(timezone.utc),
        )
        .order_by(Appointment.scheduled_for.asc())
    ).all()
    upcoming_appointments = [
        appointment for appointment in upcoming_appointments
        if pet.name.casefold() in (appointment.note or "").casefold()
    ]

    return render_template(
        "adopter/pet_health.html",
        pet=pet,
        past_vaccs=past_vaccs,
        upcoming_vaccs=upcoming_vaccs,
        past_records=past_records,
        past_health_records=past_health_records,
        upcoming_records=upcoming_records,
        past_checkup_count=past_checkup_count,
        upcoming_checkup_count=upcoming_checkup_count,
        primary_vet_profile=primary_vet_profile,
        lab_reports=lab_reports,
        surgery_count=surgery_count,
        upcoming_surgery_count=upcoming_surgery_count,
        past_prescriptions=past_prescriptions,
        present_prescriptions=present_prescriptions,
        upcoming_appointments=upcoming_appointments,
        RecordType=RecordType,
        today=today,
        active_nav="mypets",
    )


@adopter_bp.route("/pets/<int:pet_id>/health/records/<int:record_id>")
@login_required
def pet_health_record(pet_id: int, record_id: int):
    """Display one shared veterinary health record for an owned pet."""
    pet = _owned_or_404(pet_id)
    record = db.session.get(MedicalRecord, record_id)
    if (
        record is None
        or record.pet_id != pet.id
        or not record.shared_with_owner
    ):
        abort(404)

    health_plans = db.session.scalars(
        db.select(HealthPlan)
        .where(HealthPlan.pet_id == pet.id)
        .order_by(HealthPlan.next_visit_on.asc(), HealthPlan.id.desc())
    ).all()

    return render_template(
        "adopter/pet_health_record.html",
        pet=pet,
        record=record,
        health_plans=health_plans,
        active_nav="mypets",
    )


@adopter_bp.route("/pets/<int:pet_id>/health/lab-reports")
@login_required
def pet_lab_reports(pet_id: int):
    """List lab reports shared for one pet."""
    pet = _owned_or_404(pet_id)
    reports = db.session.scalars(
        db.select(MedicalRecord)
        .where(
            MedicalRecord.pet_id == pet.id,
            MedicalRecord.shared_with_owner.is_(True),
            MedicalRecord.record_type == RecordType.LAB,
        )
        .order_by(MedicalRecord.record_date.desc(), MedicalRecord.id.desc())
    ).all()
    seen_reports: set[tuple] = set()
    unique_reports = []
    for report in reports:
        key = (
            report.title.strip().casefold(),
            report.record_date.isoformat(),
        )
        if key not in seen_reports:
            seen_reports.add(key)
            unique_reports.append(report)
    selected_id = request.args.get("record", type=int)
    selected = next((r for r in unique_reports if r.id == selected_id), None)
    return render_template(
        "adopter/pet_lab_reports.html",
        pet=pet,
        reports=unique_reports,
        selected=selected,
        active_nav="mypets",
    )
