"""Adopter health views + vet-side record creation (Task 21)."""
from __future__ import annotations

from datetime import date

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ..extensions import db
from ..models.health import (
    MedicalRecord,
    OwnedPet,
    RecordType,
    Vaccination,
    VaccineStatus,
    HealthPlan,
    VetPatient,
)
from ..models.reminder import Notification
from ..models.user import UserRole
from ..security import role_required
from ..services.storage import save_image
from ..services.pdf import render_document

health_bp = Blueprint("health", __name__, url_prefix="/health")


def _owned_or_404(pet_id: int) -> OwnedPet:
    pet = db.session.get(OwnedPet, pet_id)
    if pet is None or pet.owner_id != current_user.id:
        abort(404)
    return pet


def _first_pet() -> OwnedPet | None:
    return db.session.scalar(
        db.select(OwnedPet).filter_by(owner_id=current_user.id).order_by(OwnedPet.id)
    )


# ---- Health dashboard ----
@health_bp.route("/")
@health_bp.route("/pet/<int:pet_id>")
@login_required
def dashboard(pet_id: int | None = None):
    pet = _owned_or_404(pet_id) if pet_id else _first_pet()
    all_pets = db.session.scalars(
        db.select(OwnedPet).filter_by(owner_id=current_user.id)
    ).all()
    if pet is None:
        return render_template("health/empty.html", active_nav="health")

    vaccs = sorted(pet.vaccinations, key=lambda v: (v.due_on or date.max))
    next_due = next((v for v in vaccs if v.status != VaccineStatus.DONE), None)
    return render_template(
        "health/dashboard.html",
        pet=pet,
        all_pets=all_pets,
        vaccinations=vaccs,
        next_due=next_due,
        records=sorted(
            (r for r in pet.medical_records if r.shared_with_owner),
            key=lambda r: r.record_date,
            reverse=True,
        ),
        health_plans=db.session.scalars(
            db.select(HealthPlan)
            .filter(
                HealthPlan.pet_id == pet.id,
                db.or_(
                    HealthPlan.next_visit_on.is_(None),
                    HealthPlan.next_visit_on >= date.today(),
                ),
            )
            .order_by(HealthPlan.next_visit_on.asc().nullslast(), HealthPlan.created_at.desc())
        ).all(),
        active_nav="health",
    )


# ---- Medical records ----
@health_bp.route("/pet/<int:pet_id>/records")
@login_required
def records(pet_id: int):
    pet = _owned_or_404(pet_id)
    type_filter = request.args.get("type")
    items = sorted(
        (r for r in pet.medical_records if r.shared_with_owner),
        key=lambda r: r.record_date,
        reverse=True,
    )
    if type_filter and type_filter != "all":
        items = [r for r in items if r.record_type.value == type_filter]
    return render_template(
        "health/records.html",
        pet=pet,
        records=items,
        type_filter=type_filter or "all",
        RecordType=RecordType,
        active_nav="health",
    )


@health_bp.route("/record/<int:record_id>.pdf")
@login_required
def record_pdf(record_id: int):
    record = db.session.get(MedicalRecord, record_id)
    if record is None:
        abort(404)
    is_owner = record.pet.owner_id == current_user.id
    is_linked_vet = db.session.scalar(
        db.select(VetPatient).filter_by(vet_id=current_user.id, pet_id=record.pet_id)
    ) is not None
    if not is_owner and not is_linked_vet:
        abort(404)
    sections = [
        ("Pet", record.pet.name),
        ("Record type", record.record_type.label),
        ("Date", record.record_date.strftime("%d %B %Y")),
        ("Veterinarian", record.vet_name or "—"),
    ]
    if record.findings:
        sections.append(("Findings", record.findings))
    if record.diagnosis:
        sections.append(("Diagnosis", record.diagnosis))
    if record.summary:
        sections.append(("Summary", record.summary))
    pdf = render_document(record.title, f"{record.pet.name} medical record", sections)
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=record-{record.id}.pdf"},
    )


# ---- Vaccination tracker ----
@health_bp.route("/pet/<int:pet_id>/vaccinations")
@login_required
def vaccinations(pet_id: int):
    pet = _owned_or_404(pet_id)
    vaccs = sorted(pet.vaccinations, key=lambda v: (v.due_on or date.max))
    up_to_date = sum(1 for v in vaccs if v.status in (VaccineStatus.DONE, VaccineStatus.UPCOMING))
    overdue = sum(1 for v in vaccs if v.status == VaccineStatus.OVERDUE)
    next_due = next((v for v in vaccs if v.status != VaccineStatus.DONE), None)
    return render_template(
        "health/vaccinations.html",
        pet=pet,
        vaccinations=vaccs,
        up_to_date=up_to_date,
        total=len(vaccs),
        overdue=overdue,
        next_due=next_due,
        active_nav="health",
    )


# ---- Vet-side: create a medical record and share with the owner ----
@health_bp.route("/vet/record/new", methods=["GET", "POST"])
@role_required(UserRole.VET)
def new_record():
    links = db.session.scalars(
        db.select(VetPatient)
        .filter_by(vet_id=current_user.id)
        .join(OwnedPet, VetPatient.pet_id == OwnedPet.id)
        .order_by(OwnedPet.name)
    ).all()
    pets = [link.pet for link in links]
    if request.method == "POST":
        pet_id = request.form.get("pet_id", type=int)
        pet = next((patient for patient in pets if patient.id == pet_id), None)
        if pet is None:
            flash("Choose a patient linked to your vet account.", "warning")
            return render_template("health/vet_record_form.html", pets=pets,
                                   RecordType=RecordType, active_nav="records")
        try:
            record_type = RecordType(request.form.get("record_type", "consultation"))
            record_date = date.fromisoformat(
                request.form.get("record_date") or date.today().isoformat()
            )
        except ValueError:
            flash("Choose a valid record type and date.", "warning")
            return render_template("health/vet_record_form.html", pets=pets,
                                   RecordType=RecordType, active_nav="records")
        record = MedicalRecord(
            pet_id=pet.id,
            vet_id=current_user.id,
            record_type=record_type,
            title=(request.form.get("title") or "Consultation").strip(),
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
            f"{current_user.full_name} shared a medical record to {pet.name}'s health profile.",
            category="health",
            link=url_for("health.dashboard", pet_id=pet.id),
        )
        db.session.commit()
        flash(f"Record shared with {pet.name}'s owner.", "success")
        return redirect(url_for("health.new_record"))
    return render_template(
        "health/vet_record_form.html", pets=pets, RecordType=RecordType,
        active_nav="records",
    )
