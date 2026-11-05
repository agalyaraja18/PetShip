"""PetShip application package.

Exposes the application factory :func:`create_app`. The factory wires
configuration, extensions, blueprints, error handlers, and template globals,
and returns a fully configured :class:`flask.Flask` instance.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask

from .config import get_config
from .extensions import csrf, db, login_manager, mail, migrate, socketio

# Load variables from a local .env file if present. Safe to call when absent.
load_dotenv()

__all__ = ["create_app"]


def create_app(config_name: str | None = None) -> Flask:
    """Build and return a configured Flask application.

    :param config_name: one of ``development``/``testing``/``production``.
        When omitted the ``FLASK_CONFIG`` env var is used, defaulting to
        development.
    """
    app = Flask(__name__, instance_relative_config=False)

    config_class = get_config(config_name)
    app.config.from_object(config_class)
    # ``init_app`` may raise in production if required settings are missing.
    config_class.init_app(app)

    _init_extensions(app)
    _register_blueprints(app)
    _register_cli(app)
    _register_template_globals(app)

    from .errors import register_error_handlers

    register_error_handlers(app)

    from .security_headers import register_security_headers

    register_security_headers(app)

    from .services.scheduler import init_scheduler

    init_scheduler(app)

    from .realtime import register_socketio_handlers

    register_socketio_handlers()

    # Tiny routes used only by the test suite to exercise error handlers.
    if app.config.get("TESTING"):
        @app.route("/_boom")
        def _boom():  # pragma: no cover - trivial
            raise RuntimeError("boom")

        @app.route("/_forbidden")
        def _forbidden():  # pragma: no cover - trivial
            from flask import abort

            abort(403)

    return app


def _init_extensions(app: Flask) -> None:
    """Bind extension singletons to the application."""
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)

    # SocketIO: use the Redis message queue when configured so multiple
    # workers can share events; otherwise run single-process (fine for dev).
    # async_mode is set explicitly (default "threading") to avoid importing an
    # eventlet build that is incompatible with the running Python version.
    socketio.init_app(
        app,
        message_queue=app.config.get("REDIS_URL"),
        async_mode=app.config.get("SOCKETIO_ASYNC_MODE", "threading"),
    )

    # Google OAuth (registers the provider only when credentials are present).
    from .services.oauth import init_oauth

    init_oauth(app)

    # Import models so Flask-Migrate/Alembic autogenerate can see every table
    # on the shared metadata. Imported inside the factory to avoid circular
    # imports at module load time.
    with app.app_context():
        from . import models  # noqa: F401  (registers models with db.metadata)

    _register_login_loader()


def _register_login_loader() -> None:
    """Register the Flask-Login user loader (expanded in the auth phase)."""
    from .models.user import User

    @login_manager.user_loader
    def load_user(user_id: str):  # pragma: no cover - thin lookup
        return db.session.get(User, int(user_id))


def _register_blueprints(app: Flask) -> None:
    """Register all domain blueprints.

    Blueprints are added incrementally across tasks. The core blueprint
    (health check + home placeholder) is always present.
    """
    from .blueprints.admin import admin_bp
    from .blueprints.admin_moderation import admin_mod_bp
    from .blueprints.adopter import adopter_bp
    from .blueprints.adoption import adoption_bp
    from .blueprints.ai import ai_bp
    from .blueprints.auth import auth_bp
    from .blueprints.shelter import shelter_bp
    from .blueprints.shelter_ops import shelter_ops_bp
    from .blueprints.shelter_pets import shelter_pets_bp
    from .blueprints.shelter_requests import shelter_requests_bp
    from .blueprints.vet import vet_bp
    from .blueprints.vet_booking import vet_booking_bp
    from .blueprints.vet_workspace import vet_workspace_bp
    from .blueprints.content import content_bp
    from .blueprints.core import core_bp
    from .blueprints.favourites import favourites_bp
    from .blueprints.feedback import feedback_bp
    from .blueprints.health import health_bp
    from .blueprints.legal import legal_bp
    from .blueprints.community import community_bp
    from .blueprints.learning import learning_bp
    from .blueprints.lostfound import lostfound_bp
    from .blueprints.messages import messages_bp
    from .blueprints.reviews import reviews_bp
    from .blueprints.lifestyle import lifestyle_bp
    from .blueprints.pets import pets_bp
    from .blueprints.reminders import reminders_bp
    from .blueprints.profile import profile_bp
    from .blueprints.reporting import reporting_bp
    from .blueprints.styleguide import styleguide_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(pets_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(styleguide_bp)
    app.register_blueprint(legal_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(reporting_bp)
    app.register_blueprint(favourites_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(adoption_bp)
    app.register_blueprint(adopter_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(lifestyle_bp)
    app.register_blueprint(reminders_bp)
    app.register_blueprint(learning_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(community_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(lostfound_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_mod_bp)
    app.register_blueprint(shelter_bp)
    app.register_blueprint(shelter_pets_bp)
    app.register_blueprint(shelter_requests_bp)
    app.register_blueprint(shelter_ops_bp)
    app.register_blueprint(vet_bp)
    app.register_blueprint(vet_booking_bp)
    app.register_blueprint(vet_workspace_bp)


def _register_cli(app: Flask) -> None:
    """Register custom Flask CLI commands (seed data, reminders, etc.)."""
    from .seed import register_seed
    from .services.scheduler import register_reminder_cli

    register_seed(app)
    register_reminder_cli(app)


def _register_template_globals(app: Flask) -> None:
    """Expose constants and helpers to all Jinja2 templates."""

    @app.context_processor
    def inject_globals():  # pragma: no cover - thin wrapper
        from flask_login import current_user

        from .blueprints.favourites import favourite_pet_ids
        from .services.oauth import google_enabled

        return {
            "APP_NAME": "PetShip",
            "APP_TAGLINE": "Beyond Fur & Feather; It's a Family",
            "google_enabled": google_enabled(),
            "fav_ids": favourite_pet_ids(current_user),
        }
