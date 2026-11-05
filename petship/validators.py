from __future__ import annotations

import phonenumbers
from wtforms import ValidationError


def validate_phone_number(form, field) -> None:
    value = (field.data or "").strip()
    if not value:
        return
    try:
        number = phonenumbers.parse(value, None if value.startswith("+") else "IN")
    except phonenumbers.NumberParseException:
        raise ValidationError("Enter a valid phone number.")

    if not phonenumbers.is_valid_number(number):
        raise ValidationError("Enter a valid phone number.")

    field.data = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
