"""Editorial & support pages: blog, success stories, about, contact, FAQ."""
from __future__ import annotations

from collections import OrderedDict

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, Length

from ..extensions import db
from ..models.content import FAQ, BlogPost, ContactMessage, SuccessStory

content_bp = Blueprint("content", __name__)


# ---- Blog ----
@content_bp.route("/blog")
def blog():
    category = request.args.get("category")
    query = db.select(BlogPost).filter_by(published=True)
    if category and category != "All":
        query = query.filter_by(category=category)
    posts = db.session.scalars(query.order_by(BlogPost.created_at.desc())).all()
    categories = ["All", "Health", "Training", "Nutrition", "Adoption", "Care"]
    return render_template(
        "content/blog.html", posts=posts, categories=categories,
        active_category=category or "All", active_nav="blog",
    )


@content_bp.route("/blog/<slug>")
def blog_post(slug: str):
    post = db.session.scalar(db.select(BlogPost).filter_by(slug=slug, published=True))
    if post is None:
        abort(404)
    return render_template("content/blog_post.html", post=post, active_nav="blog")


@content_bp.route("/blog/write", methods=["GET", "POST"])
def write_blog():
    """Any logged-in user (adopter, shelter, or vet) can publish a blog post."""
    from flask_login import current_user

    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=url_for("content.write_blog")))

    if request.method == "POST":
        import re
        import secrets

        title = (request.form.get("title") or "").strip()
        body = (request.form.get("body") or "").strip()
        if not title or not body:
            flash("A title and body are required.", "warning")
        else:
            base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "post"
            slug = f"{base}-{secrets.token_hex(3)}"
            words = max(1, len(body.split()))

            # Handle optional cover photo upload.
            cover_url = None
            photo_file = request.files.get("cover_photo")
            if photo_file and photo_file.filename:
                from ..services.storage import save_image
                cover_url = save_image(photo_file)

            post = BlogPost(
                slug=slug, title=title,
                category=request.form.get("category", "Care"),
                author=current_user.full_name,
                read_minutes=max(1, round(words / 200)),
                excerpt=body[:160],
                body=body,
                cover_url=cover_url,
                published=True,
            )
            db.session.add(post)
            db.session.commit()
            flash("Your blog post is published!", "success")
            return redirect(url_for("content.blog_post", slug=slug))

    return render_template(
        "content/write_blog.html",
        categories=["Health", "Training", "Nutrition", "Adoption", "Care"],
        active_nav="blog",
    )


# ---- Success stories ----
@content_bp.route("/stories")
def stories():
    featured = db.session.scalar(
        db.select(SuccessStory).filter_by(featured=True).limit(1)
    )
    others = db.session.scalars(
        db.select(SuccessStory).filter_by(featured=False)
    ).all()
    from ..models.pet import Pet, PetStatus

    adopted = db.session.scalar(
        db.select(db.func.count()).select_from(Pet).filter_by(status=PetStatus.ADOPTED)
    ) or 0
    return render_template(
        "content/stories.html", featured=featured, others=others,
        adopted=adopted, active_nav="stories",
    )


@content_bp.route("/stories/share", methods=["GET", "POST"])
def share_story():
    """Any logged-in user can share a success story."""
    from flask_login import current_user

    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=url_for("content.share_story")))

    if request.method == "POST":
        quote = (request.form.get("quote") or "").strip()
        if not quote:
            flash("Please share a few words about your story.", "warning")
        else:
            # Handle optional photo upload.
            photo_url = None
            photo_file = request.files.get("photo")
            if photo_file and photo_file.filename:
                from ..services.storage import save_image
                photo_url = save_image(photo_file)

            story = SuccessStory(
                title=(request.form.get("title") or "Our happy tail").strip(),
                family=current_user.full_name,
                pet_name=(request.form.get("pet_name") or "").strip() or None,
                quote=quote,
                body=(request.form.get("body") or "").strip() or None,
                photo_url=photo_url,
            )
            db.session.add(story)
            db.session.commit()
            flash("Thank you for sharing your story!", "success")
            return redirect(url_for("content.stories"))

    return render_template("content/share_story.html", active_nav="stories")


# ---- About ----
@content_bp.route("/about")
def about():
    from ..models.pet import Pet, PetStatus
    from ..models.shelter import Shelter
    from ..models.user import User, UserRole
    from ..models.vet import VetProfile

    def _count(model, **f):
        q = db.select(db.func.count()).select_from(model)
        return (db.session.scalar(q.filter_by(**f) if f else q)) or 0

    stats = {
        "pets_adopted": _count(Pet, status=PetStatus.ADOPTED),
        "verified_shelters": _count(Shelter, is_verified=True),
        "partner_vets": _count(VetProfile, is_verified=True),
        "pet_parents": _count(User, role=UserRole.ADOPTER),
    }
    return render_template("content/about.html", stats=stats, active_nav="")


# ---- Contact ----
class ContactForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(max=160)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    topic = SelectField(
        "Topic",
        choices=[
            ("Adoption question", "Adoption question"),
            ("Shelter partnership", "Shelter partnership"),
            ("Vet partnership", "Vet partnership"),
            ("Something else", "Something else"),
        ],
    )
    message = TextAreaField("Message", validators=[DataRequired(), Length(max=2000)])


@content_bp.route("/contact", methods=["GET", "POST"])
def contact():
    form = ContactForm()
    if form.validate_on_submit():
        msg = ContactMessage(
            name=form.name.data.strip(),
            email=form.email.data.lower().strip(),
            topic=form.topic.data,
            message=form.message.data.strip(),
        )
        db.session.add(msg)
        db.session.commit()
        flash("Thanks! Our team replies within one working day.", "success")
        return redirect(url_for("content.contact"))
    return render_template("content/contact.html", form=form, active_nav="")


# ---- FAQ / Help centre ----
@content_bp.route("/help")
def help_centre():
    q = (request.args.get("q") or "").strip().lower()
    query = db.select(FAQ).order_by(FAQ.category, FAQ.sort_order)
    faqs = db.session.scalars(query).all()
    if q:
        faqs = [f for f in faqs if q in f.question.lower() or q in f.answer.lower()]

    # Group by category, preserving order.
    grouped: "OrderedDict[str, list]" = OrderedDict()
    for f in faqs:
        grouped.setdefault(f.category, []).append(f)

    if request.headers.get("HX-Request"):
        return render_template("content/_faq_list.html", grouped=grouped, q=q)
    return render_template(
        "content/help.html", grouped=grouped, q=q, active_nav="",
    )
