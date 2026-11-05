"""Google OAuth integration (optional, cleanly disabled when unkeyed).

Uses Authlib's Flask integration. ``init_oauth`` registers the Google provider
only when client credentials are configured; otherwise the OAuth routes report
that sign-in is unavailable. This keeps the app fully functional with no keys.
"""
from __future__ import annotations

from authlib.integrations.flask_client import OAuth

oauth = OAuth()

GOOGLE_CONF_URL = "https://accounts.google.com/.well-known/openid-configuration"


def init_oauth(app) -> None:
    oauth.init_app(app)
    if app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url=GOOGLE_CONF_URL,
            client_kwargs={"scope": "openid email profile"},
        )


def google_enabled() -> bool:
    from flask import current_app

    return bool(
        current_app.config.get("GOOGLE_CLIENT_ID")
        and current_app.config.get("GOOGLE_CLIENT_SECRET")
    )
