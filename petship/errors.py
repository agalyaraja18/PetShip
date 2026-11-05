"""Application-wide error handlers rendering branded error pages (Task 4)."""
from __future__ import annotations

import secrets

from flask import Flask, render_template
from werkzeug.exceptions import Forbidden, HTTPException, NotFound


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(NotFound)
    def handle_404(error: HTTPException):
        return render_template("errors/404.html"), 404

    @app.errorhandler(Forbidden)
    def handle_403(error: HTTPException):
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    @app.errorhandler(Exception)
    def handle_500(error):
        # Re-raise non-500 HTTP exceptions so their own handlers run.
        if isinstance(error, HTTPException) and error.code != 500:
            return error
        # A short reference helps users report the incident.
        error_ref = "PS-500-" + secrets.token_hex(2).upper()
        app.logger.exception("Unhandled error (ref=%s)", error_ref)
        return render_template("errors/500.html", error_ref=error_ref), 500
