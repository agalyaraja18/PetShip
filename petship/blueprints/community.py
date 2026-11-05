"""Community feed, posts, comments, profiles (Task 30) + report/abuse (Task 31)."""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ..extensions import db
from ..models.community import POST_TOPICS, Comment, Follow, Post, PostLike
from ..models.report import AbuseReport, ReportTargetType
from ..models.user import User
from ..services.storage import save_image

community_bp = Blueprint("community", __name__, url_prefix="/community")

TRENDING = [
    ("#FirstWeekHome", "1.2k posts"),
    ("Monsoon paw care", "384 posts"),
    ("Senior pet love", "291 posts"),
]


def _liked_post_ids() -> set[int]:
    if not current_user.is_authenticated:
        return set()
    return set(
        db.session.scalars(
            db.select(PostLike.post_id).filter_by(user_id=current_user.id)
        ).all()
    )


@community_bp.route("/")
def feed():
    topic = request.args.get("topic")
    query = db.select(Post).filter_by(hidden=False)
    if topic and topic != "All posts":
        query = query.filter_by(topic=topic)
    posts = db.session.scalars(query.order_by(Post.created_at.desc())).all()
    return render_template(
        "community/feed.html",
        posts=posts,
        topics=["All posts"] + POST_TOPICS,
        active_topic=topic or "All posts",
        trending=TRENDING,
        liked=_liked_post_ids(),
        active_nav="community",
    )


@community_bp.route("/post/<int:post_id>")
def discussion(post_id: int):
    post = db.session.get(Post, post_id)
    if post is None or post.hidden:
        abort(404)
    top_level = [c for c in post.comments if c.parent_id is None and not c.hidden]
    replies = {}
    for c in post.comments:
        if c.parent_id and not c.hidden:
            replies.setdefault(c.parent_id, []).append(c)
    return render_template(
        "community/discussion.html",
        post=post,
        top_level=top_level,
        replies=replies,
        liked=_liked_post_ids(),
        active_nav="community",
    )


@community_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        body = (request.form.get("body") or "").strip()
        if not body:
            flash("Write something to share.", "warning")
            return render_template("community/create.html", topics=POST_TOPICS,
                                   post=None, active_nav="community")
        post = Post(
            author_id=current_user.id,
            title=(request.form.get("title") or "").strip() or None,
            topic=request.form.get("topic", "Show & tell"),
            body=body,
        )
        urls = []
        for f in request.files.getlist("photos"):
            url = save_image(f, folder="posts")
            if url:
                urls.append(url)
        post.photos = urls
        db.session.add(post)
        db.session.commit()
        flash("Your post is live!", "success")
        return redirect(url_for("community.discussion", post_id=post.id))
    return render_template("community/create.html", topics=POST_TOPICS, post=None,
                           active_nav="community")


@community_bp.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def edit(post_id: int):
    post = db.session.get(Post, post_id)
    if post is None or post.author_id != current_user.id:
        abort(404)
    if request.method == "POST":
        if request.form.get("action") == "delete":
            db.session.delete(post)
            db.session.commit()
            flash("Post deleted.", "info")
            return redirect(url_for("community.feed"))
        post.title = (request.form.get("title") or "").strip() or None
        post.topic = request.form.get("topic", post.topic)
        post.body = (request.form.get("body") or post.body).strip()
        post.edited = True
        db.session.commit()
        flash("Post updated.", "success")
        return redirect(url_for("community.discussion", post_id=post.id))
    return render_template("community/create.html", topics=POST_TOPICS, post=post,
                           active_nav="community")


@community_bp.route("/post/<int:post_id>/like", methods=["POST"])
@login_required
def like(post_id: int):
    post = db.session.get(Post, post_id)
    if post is None:
        abort(404)
    existing = db.session.scalar(
        db.select(PostLike).filter_by(post_id=post_id, user_id=current_user.id)
    )
    if existing:
        db.session.delete(existing)
        liked = False
    else:
        db.session.add(PostLike(post_id=post_id, user_id=current_user.id))
        liked = True
    db.session.commit()
    if request.headers.get("HX-Request"):
        db.session.refresh(post)
        return render_template("community/_like_button.html", post=post, liked=liked)
    return redirect(url_for("community.discussion", post_id=post_id))


@community_bp.route("/post/<int:post_id>/comment", methods=["POST"])
@login_required
def comment(post_id: int):
    post = db.session.get(Post, post_id)
    if post is None:
        abort(404)
    body = (request.form.get("body") or "").strip()
    if body:
        db.session.add(Comment(
            post_id=post_id, author_id=current_user.id, body=body,
            parent_id=request.form.get("parent_id", type=int),
        ))
        db.session.commit()
    return redirect(url_for("community.discussion", post_id=post_id))


@community_bp.route("/u/<int:user_id>")
def profile(user_id: int):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    posts = db.session.scalars(
        db.select(Post).filter_by(author_id=user_id, hidden=False)
        .order_by(Post.created_at.desc())
    ).all()
    followers = db.session.scalar(
        db.select(db.func.count()).select_from(Follow).filter_by(following_id=user_id)
    ) or 0
    is_following = False
    if current_user.is_authenticated:
        is_following = db.session.scalar(
            db.select(Follow).filter_by(
                follower_id=current_user.id, following_id=user_id
            )
        ) is not None
    return render_template(
        "community/profile.html",
        profile_user=user,
        posts=posts,
        followers=followers,
        is_following=is_following,
        active_nav="community",
    )


@community_bp.route("/u/<int:user_id>/follow", methods=["POST"])
@login_required
def follow(user_id: int):
    if user_id == current_user.id:
        abort(400)
    existing = db.session.scalar(
        db.select(Follow).filter_by(follower_id=current_user.id, following_id=user_id)
    )
    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Follow(follower_id=current_user.id, following_id=user_id))
    db.session.commit()
    return redirect(url_for("community.profile", user_id=user_id))


# ---- Report / abuse (Task 31) ----
REPORT_REASONS = [
    "Selling animals for profit",
    "Suspected animal abuse or neglect",
    "Fake or misleading information",
    "Harassment",
    "Something else",
]


@community_bp.route("/report", methods=["POST"])
@login_required
def report():
    target_type = request.form.get("target_type", "post")
    try:
        ttype = ReportTargetType(target_type)
    except ValueError:
        ttype = ReportTargetType.POST
    db.session.add(AbuseReport(
        reporter_id=current_user.id,
        target_type=ttype,
        target_id=request.form.get("target_id", type=int) or 0,
        target_label=request.form.get("target_label"),
        reason=request.form.get("reason", "Something else"),
        details=(request.form.get("details") or "").strip() or None,
        priority=request.form.get("priority", "medium"),
    ))
    db.session.commit()
    flash("Report submitted. Our team reviews every report within 24 hours.", "success")
    return redirect(request.referrer or url_for("community.feed"))
