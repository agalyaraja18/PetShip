"""Real-time direct messaging + notification bell (Task 32)."""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ..extensions import db
from ..models.message import Message, Thread
from ..models.reminder import Notification
from ..models.user import User, UserRole
from ..realtime import emit_message

messages_bp = Blueprint("messages", __name__, url_prefix="/messages")


def _get_or_create_thread(a_id: int, b_id: int) -> Thread:
    lo, hi = sorted((a_id, b_id))
    thread = db.session.scalar(
        db.select(Thread).filter_by(user_a_id=lo, user_b_id=hi)
    )
    if thread is None:
        thread = Thread(user_a_id=lo, user_b_id=hi)
        db.session.add(thread)
        db.session.commit()
    return thread


def _my_threads():
    return db.session.scalars(
        db.select(Thread).filter(
            (Thread.user_a_id == current_user.id)
            | (Thread.user_b_id == current_user.id)
        ).order_by(Thread.updated_at.desc())
    ).all()


@messages_bp.route("/")
@messages_bp.route("/<int:thread_id>")
@login_required
def inbox(thread_id: int | None = None):
    if current_user.role == UserRole.VET:
        abort(404)
    threads = _my_threads()
    active = None
    if thread_id:
        active = db.session.get(Thread, thread_id)
        if active is None or current_user.id not in (active.user_a_id, active.user_b_id):
            abort(404)
        # Mark incoming messages read.
        for m in active.messages:
            if m.sender_id != current_user.id and not m.read:
                m.read = True
        db.session.commit()
    elif threads:
        active = threads[0]

    # Directory of people the user can start a conversation with: verified
    # shelters and vets (so the Messages page is useful even with no threads).
    from ..models.shelter import Shelter
    from ..models.vet import VetProfile

    contacts = []
    seen_user_ids = {t.other(current_user.id).id for t in threads}
    for s in db.session.scalars(
        db.select(Shelter).filter_by(is_verified=True)
    ).all():
        if s.owner_id and s.owner_id != current_user.id and s.owner_id not in seen_user_ids:
            contacts.append({"user_id": s.owner_id, "name": s.name, "role": "Shelter"})
    for v in db.session.scalars(
        db.select(VetProfile).filter_by(is_verified=True)
    ).all():
        if v.user_id != current_user.id and v.user_id not in seen_user_ids:
            contacts.append({"user_id": v.user_id, "name": v.display_name, "role": "Vet"})

    return render_template(
        "messages/inbox.html",
        threads=threads,
        active=active,
        messages=active.messages if active else [],
        contacts=contacts,
        layout_template=_layout_for(current_user),
        active_nav="messages",
    )


def _layout_for(user):
    """Render messages inside the shell matching the user's role."""
    from ..models.user import UserRole

    return {
        UserRole.SHELTER: "layouts/shelter.html",
        UserRole.VET: "layouts/vet.html",
        UserRole.ADMIN: "layouts/admin.html",
    }.get(user.role, "layouts/adopter.html")


@messages_bp.route("/start/<int:user_id>")
@login_required
def start(user_id: int):
    if current_user.role == UserRole.VET:
        abort(404)
    other = db.session.get(User, user_id)
    if other is None or user_id == current_user.id:
        abort(404)
    thread = _get_or_create_thread(current_user.id, user_id)
    return redirect(url_for("messages.inbox", thread_id=thread.id))


@messages_bp.route("/<int:thread_id>/send", methods=["POST"])
@login_required
def send(thread_id: int):
    if current_user.role == UserRole.VET:
        abort(404)
    thread = db.session.get(Thread, thread_id)
    if thread is None or current_user.id not in (thread.user_a_id, thread.user_b_id):
        abort(404)
    body = (request.form.get("body") or "").strip()
    if not body:
        return ("", 204)

    msg = Message(thread_id=thread.id, sender_id=current_user.id, body=body)
    db.session.add(msg)
    # Touch the thread so it sorts to the top.
    from ..models.mixins import utcnow

    thread.updated_at = utcnow()
    db.session.commit()

    recipient = thread.other(current_user.id)
    # Live message delivery (always — the recipient is in an active thread).
    emit_message(recipient.id, {
        "thread_id": thread.id,
        "sender": current_user.full_name,
        "body": body,
    })
    # Notification respects the recipient's "messages" preference.
    from ..services.notify import notify

    notify(
        recipient,
        title=f"New message from {current_user.full_name}",
        body=body[:80],
        category="messages",
        link=url_for("messages.inbox", thread_id=thread.id),
    )
    db.session.commit()

    if request.headers.get("HX-Request"):
        return render_template("messages/_message.html", m=msg, mine=True)
    return redirect(url_for("messages.inbox", thread_id=thread.id))


# ---- Notification bell (shared across role shells) ----
@messages_bp.route("/bell")
@login_required
def bell():
    """Bell dropdown fragment: recent notifications + unread count."""
    notifs = db.session.scalars(
        db.select(Notification).filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc()).limit(6)
    ).all()
    unread = db.session.scalar(
        db.select(db.func.count()).select_from(Notification)
        .filter_by(user_id=current_user.id, read=False)
    ) or 0
    return render_template("messages/_bell.html", notifs=notifs, unread=unread)
