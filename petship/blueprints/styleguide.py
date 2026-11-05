"""Styleguide blueprint.

Renders the component library and live previews of all four role shells.
This is a documentation/QA surface for the design system (Task 3). It is
always registered; later tasks reference these layouts for real pages.
"""
from __future__ import annotations

from flask import Blueprint, abort, render_template

styleguide_bp = Blueprint("styleguide", __name__)

_SHELL_TEMPLATES = {
    "public": "styleguide.html",
    "adopter": "shell_previews/adopter.html",
    "vet": "shell_previews/vet.html",
    "shelter": "shell_previews/shelter.html",
    "admin": "shell_previews/admin.html",
}


@styleguide_bp.route("/styleguide")
def index():
    return render_template("styleguide.html")


@styleguide_bp.route("/styleguide/shell/<shell>")
def shell_preview(shell: str):
    template = _SHELL_TEMPLATES.get(shell)
    if template is None:
        abort(404)
    return render_template(template)
