"""Shared Flask extension singletons.

These are instantiated here without an app and bound later inside the
application factory via ``init_app``. Importing from this module avoids
circular imports between the factory, models, and blueprints.
"""
from __future__ import annotations

from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

# Database + migrations
db = SQLAlchemy()
migrate = Migrate()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(connection, _record) -> None:
    if connection.__class__.__module__.startswith("sqlite3"):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# Authentication / sessions
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "info"

# Forms / CSRF protection
csrf = CSRFProtect()

# Email
mail = Mail()

# Real-time. ``async_mode`` and the Redis message queue are configured in the
# factory; left unset here so the extension stays import-safe.
socketio = SocketIO(cors_allowed_origins="*")
