"""Server messages in the user's language (slice G5, ADR-0013).

The screen sends Accept-Language; messages shown to people (errors, delivery-risk explanations,
suggestions, report definitions, import problems) are translated with tr(). Stored records and
audit details stay in English so history does not depend on who looked at it.

tr("Only {count} left", count=3) looks the English text up in the Tamil catalogue and fills the
named placeholders. N_() only marks text that is translated later with tr(). The test
tests/test_i18n_catalogue.py fails when a message has no Tamil or its placeholders differ.
"""

from contextvars import ContextVar
from typing import Any

from app.core.ta import TA

LANGUAGES = ("en", "ta")
_language: ContextVar[str] = ContextVar("language", default="en")


def language_from_header(value: str | None) -> str:
    """'ta', 'ta-IN' or 'ta-IN,en;q=0.8' choose Tamil; anything else is English."""
    first = (value or "").split(",")[0].strip().lower()
    return "ta" if first.startswith("ta") else "en"


def set_language(value: str) -> None:
    _language.set(value if value in LANGUAGES else "en")


def current_language() -> str:
    return _language.get()


def tr(_text: str, /, **values: Any) -> str:
    template = TA.get(_text, _text) if _language.get() == "ta" else _text
    if not values:
        return template
    return template.format_map({key: str(value) for key, value in values.items()})


def N_(text: str) -> str:  # noqa: N802  (conventional name for "translate later")
    return text


# Pydantic request-validation messages, by error type (FastAPI returns them as detail[].msg).
VALIDATION = {
    "missing": N_("Required"),
    "string_too_short": N_("Enter at least {min_length} characters"),
    "string_too_long": N_("Enter at most {max_length} characters"),
    "greater_than": N_("Must be greater than {gt}"),
    "greater_than_equal": N_("Must be {ge} or more"),
    "less_than": N_("Must be less than {lt}"),
    "less_than_equal": N_("Must be {le} or less"),
    "decimal_max_places": N_("Use at most {decimal_places} decimal places"),
    "decimal_max_digits": N_("Use at most {max_digits} digits"),
    "decimal_parsing": N_("Enter a number"),
    "int_parsing": N_("Enter a whole number"),
    "float_parsing": N_("Enter a number"),
    "uuid_parsing": N_("Choose a valid record"),
    "date_parsing": N_("Enter a valid date"),
    "date_from_datetime_parsing": N_("Enter a valid date"),
    "datetime_parsing": N_("Enter a valid date and time"),
    "datetime_from_date_parsing": N_("Enter a valid date and time"),
    "time_parsing": N_("Enter a valid time"),
    "literal_error": N_("Choose one of the listed options"),
    "enum": N_("Choose one of the listed options"),
    "value_error": N_("Value is not valid"),
    "string_pattern_mismatch": N_("Use the expected format"),
    "too_short": N_("Add at least {min_length}"),
    "too_long": N_("Add at most {max_length}"),
    "extra_forbidden": N_("This field is not accepted"),
    "bool_parsing": N_("Choose yes or no"),
    "list_type": N_("Expected a list"),
}


def translate_validation_error(error: dict[str, Any]) -> dict[str, Any]:
    """Translate one pydantic error dict for the response; custom ValueError text included."""
    if _language.get() != "ta":
        return error
    out = dict(error)
    ctx = {k: v for k, v in (error.get("ctx") or {}).items() if isinstance(v, (str, int, float))}
    message = str(error.get("msg", ""))
    if error.get("type") == "value_error" and message.startswith("Value error, "):
        out["msg"] = tr(message.removeprefix("Value error, "))
    elif error.get("type") in VALIDATION:
        try:
            out["msg"] = tr(VALIDATION[error["type"]], **ctx)
        except (KeyError, IndexError):
            out["msg"] = tr(VALIDATION[error["type"]])
    loc = list(error.get("loc") or [])
    if loc and isinstance(loc[-1], str):
        loc[-1] = tr(FIELD_NAMES.get(loc[-1], loc[-1]))
        out["loc"] = loc
    return out


# Request fields people see named in validation messages.
FIELD_NAMES = {
    "reason": N_("Reason"),
    "quantity": N_("Quantity"),
    "name": N_("Name"),
    "code": N_("Code"),
    "email": N_("Email"),
    "password": N_("Password"),
    "note": N_("Note"),
    "description": N_("Description"),
    "reference": N_("Reference"),
    "title": N_("Title"),
    "due_at": N_("Due"),
    "promised_date": N_("Promised date"),
    "requested_date": N_("Requested date"),
    "movement_date": N_("Date"),
    "dispatch_date": N_("Dispatched on"),
    "receipt_date": N_("Received on"),
    "sent_date": N_("Sent on"),
    "expected_return_date": N_("Expected back"),
    "received_qty": N_("Quantity received"),
    "accepted_qty": N_("Accepted"),
    "rejected_qty": N_("Rejected"),
    "held_qty": N_("On hold"),
    "rework_qty": N_("Rework"),
    "completed_qty": N_("Completed"),
    "pending_qty": N_("Pending"),
    "qty_per_unit": N_("Quantity per unit"),
    "duration_minutes": N_("Minutes"),
    "rank": N_("Priority"),
    "decimal_places": N_("Decimal places"),
    "contact_email": N_("Contact email"),
    "contact_phone": N_("Contact phone"),
    "time_zone": N_("Time zone"),
    "permissions": N_("Permissions"),
}
