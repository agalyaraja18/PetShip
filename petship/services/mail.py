"""Email provider wrapper (fallback-first).

Supports three backends selected by ``MAIL_PROVIDER``:

* ``console`` (default) - logs the message to the application logger. No
  account needed, so the app runs end-to-end in development.
* ``smtp``    - sends via Flask-Mail using the configured SMTP server.
* ``resend``  - sends via the Resend HTTP API when ``RESEND_API_KEY`` is set.

Any backend failure degrades to console logging so flows never break in dev.
"""
from __future__ import annotations

from flask import current_app

from ..extensions import mail


def send_email(to: str, subject: str, body: str, html: str | None = None) -> str:
    """Send an email via the configured provider. Returns the provider used."""
    provider = (current_app.config.get("MAIL_PROVIDER") or "console").lower()

    if provider == "console":
        current_app.logger.warning(
            "Email delivery is in console mode; no email was sent to %s. "
            "Configure MAIL_PROVIDER and its credentials to send real email.",
            to,
        )
        return _send_console(to, subject, body)

    try:
        if provider == "smtp" and current_app.config.get("MAIL_SERVER"):
            return _send_smtp(to, subject, body, html)
        if provider == "resend" and current_app.config.get("RESEND_API_KEY"):
            return _send_resend(to, subject, body, html)
    except Exception:  # pragma: no cover - defensive fallback
        current_app.logger.exception("Email send failed; falling back to console.")
    else:
        current_app.logger.warning(
            "Email provider '%s' is missing required configuration; "
            "no email was sent to %s.",
            provider,
            to,
        )

    return _send_console(to, subject, body)


def _send_console(to: str, subject: str, body: str) -> str:
    current_app.logger.info(
        "\n----- EMAIL (console) -----\nTo: %s\nSubject: %s\n\n%s\n---------------------------",
        to,
        subject,
        body,
    )
    return "console"


def _send_smtp(to: str, subject: str, body: str, html: str | None) -> str:
    from flask_mail import Message

    msg = Message(
        subject=subject,
        recipients=[to],
        body=body,
        html=html,
        sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
    )
    mail.send(msg)
    return "smtp"


def _send_resend(to: str, subject: str, body: str, html: str | None) -> str:
    import resend

    resend.api_key = current_app.config["RESEND_API_KEY"]
    resend.Emails.send(
        {
            "from": current_app.config.get("MAIL_DEFAULT_SENDER"),
            "to": [to],
            "subject": subject,
            "text": body,
            "html": html or f"<p>{body}</p>",
        }
    )
    return "resend"
