"""Configuration classes for PetShip.

Configuration is environment-driven. Three named configs are provided:

* ``development`` - sensible local defaults, SQLite fallback, debug on.
* ``production``  - strict; expects real values via environment variables.
* ``testing``     - in-memory SQLite, CSRF disabled, fast and isolated.

All paid/keyed integrations are optional. Their absence is handled by the
provider wrappers (see ``petship/services``), not here: config only records
whatever values are present in the environment.
"""
from __future__ import annotations

import os
from pathlib import Path

# Project root (the directory that contains the ``petship`` package).
BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _database_url() -> str | None:
    """Return the DB URL normalised for psycopg v3.

    Accepts the various PostgreSQL URL forms Render/Heroku hand out and rewrites
    them to the ``postgresql+psycopg://`` driver. For managed Postgres (e.g.
    Render) that requires TLS, ``sslmode=require`` is appended when the caller
    hasn't specified an sslmode, unless DB_SSL_DISABLE is set (local Postgres).
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    is_postgres = url.startswith("postgresql+psycopg://")
    ssl_disabled = _bool(os.environ.get("DB_SSL_DISABLE"), False)
    if is_postgres and not ssl_disabled and "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return url


class BaseConfig:
    """Settings shared by every environment."""

    # ---- Core ----
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    # ---- SQLAlchemy ----
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # ---- URL / server ----
    SERVER_NAME = os.environ.get("SERVER_NAME") or None
    PREFERRED_URL_SCHEME = os.environ.get("PREFERRED_URL_SCHEME", "http")

    # ---- Sessions / cookies ----
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True

    # ---- Redis / SocketIO ----
    REDIS_URL = os.environ.get("REDIS_URL") or None
    # SocketIO async mode. "threading" works everywhere (dev/test, any Python
    # version) with no monkey-patching. Production overrides to "eventlet"
    # (run under `gunicorn -k eventlet`). Avoid letting SocketIO auto-detect,
    # which can import an eventlet build incompatible with newer Python.
    SOCKETIO_ASYNC_MODE = os.environ.get("SOCKETIO_ASYNC_MODE", "threading")

    # ---- Background scheduler (reminders) ----
    # Off by default (and in tests). Enable on exactly one instance in
    # production, or run reminders via the `flask run-reminders` CLI / cron.
    SCHEDULER_ENABLED = _bool(os.environ.get("SCHEDULER_ENABLED"), False)

    # ---- Email ----
    MAIL_PROVIDER = os.environ.get("MAIL_PROVIDER", "console")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER", "PetShip <hello@petship.com>"
    )
    MAIL_SERVER = os.environ.get("MAIL_SERVER") or None
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = _bool(os.environ.get("MAIL_USE_TLS"), True)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME") or None
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD") or None
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY") or None

    # ---- Keyed integrations (optional, fallback-first) ----
    # Firebase Cloud Storage. Provide EITHER a path to a service-account JSON
    # via FIREBASE_CREDENTIALS_FILE, or the JSON itself via FIREBASE_CREDENTIALS.
    # FIREBASE_STORAGE_BUCKET is the bucket name (e.g. my-app.appspot.com).
    # When unset, media uploads fall back to local filesystem storage.
    FIREBASE_CREDENTIALS_FILE = os.environ.get("FIREBASE_CREDENTIALS_FILE") or None
    FIREBASE_CREDENTIALS = os.environ.get("FIREBASE_CREDENTIALS") or None
    FIREBASE_STORAGE_BUCKET = os.environ.get("FIREBASE_STORAGE_BUCKET") or None
    # Google Gemini (fallback: safe templated responses when unset).
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or None
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID") or None
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET") or None

    # ---- Uploads (local-storage fallback for Firebase Cloud Storage) ----
    UPLOAD_FOLDER = str(BASE_DIR / "petship" / "static" / "uploads")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    # CSRF protection on by default; TestingConfig disables it for easy posting.
    WTF_CSRF_ENABLED = True

    DEBUG = False
    TESTING = False

    @staticmethod
    def init_app(app) -> None:
        """Hook for per-config initialization. Overridden where needed."""
        INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
        Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    # Fall back to a local SQLite file when no DATABASE_URL is provided so the
    # app runs with zero external services in development.
    SQLALCHEMY_DATABASE_URI = _database_url() or (
        "sqlite:///" + str(INSTANCE_DIR / "petship-dev.sqlite")
    )


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = False
    # In-memory DB keeps tests fast and isolated.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL", "sqlite:///:memory:"
    )
    # Disable CSRF so tests can post forms without tokens.
    WTF_CSRF_ENABLED = False
    # Keep secret deterministic in tests.
    SECRET_KEY = "testing-secret"


class ProductionConfig(BaseConfig):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = _database_url()
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True

    @staticmethod
    def init_app(app) -> None:
        BaseConfig.init_app(app)
        # Fail fast on missing critical production settings.
        if not app.config.get("SQLALCHEMY_DATABASE_URI"):
            raise RuntimeError(
                "DATABASE_URL must be set in production (PostgreSQL URL)."
            )
        if app.config.get("SECRET_KEY") in (None, "", "dev-secret-change-me"):
            raise RuntimeError("A strong SECRET_KEY must be set in production.")


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None):
    """Resolve a config class by name, defaulting to the env or development."""
    name = name or os.environ.get("FLASK_CONFIG", "development")
    return config_by_name.get(name, DevelopmentConfig)
