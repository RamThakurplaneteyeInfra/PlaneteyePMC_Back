"""
User-friendly API error formatting for the PMC backend.

Converts DRF / Django validation and exception messages into clear,
actionable field-level errors without changing successful responses.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from rest_framework import status
from rest_framework.response import Response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Generic DRF / Django message → friendly text
# ---------------------------------------------------------------------------

GENERIC_MESSAGE_MAP: dict[str, str] = {
    "This field is required.": "This field is required to continue.",
    "This field may not be null.": "Please provide a value.",
    "This field may not be blank.": "Please provide a value.",
    "Invalid.": "Please enter a valid value.",
    "Not found.": "The requested record could not be found.",
    "Permission denied.": "You do not have permission to perform this action.",
    "Authentication credentials were not provided.": (
        "Please log in to continue."
    ),
    "Invalid token.": "Your session is invalid. Please log in again.",
    "Token is invalid or expired": "Your session has expired. Please log in again.",
    "Given token not valid for any token type": (
        "Your session is invalid. Please log in again."
    ),
    "A valid number is required.": "Please enter a valid number.",
    "A valid integer is required.": "Please enter a valid whole number.",
    "Enter a valid email address.": "Please enter a valid email address.",
    "Enter a valid URL.": "Please enter a valid URL.",
    "Date has wrong format. Use one of these formats instead: YYYY-MM-DD.": (
        "Please enter the date in YYYY-MM-DD format."
    ),
    "The submitted data was not a file. Check the encoding type on the form.": (
        "Please choose a file to upload."
    ),
    "The submitted file is empty.": "Please upload a non-empty file.",
    "No file was submitted.": "Please choose a file to upload.",
    "Incorrect type. Expected pk value, received {data_type}.": (
        "Please select a valid option."
    ),
    "No active account found with the given credentials": (
        "Incorrect username or password."
    ),
    "Unable to log in with provided credentials.": (
        "Incorrect username or password."
    ),
    "Invalid username/password.": "Incorrect username or password.",
    "User account is disabled.": (
        "Your account has been disabled. Please contact the administrator."
    ),
}

# Field-aware overrides (matched by field name substring, case-insensitive)
FIELD_FRIENDLY_MESSAGES: dict[str, dict[str, str]] = {
    "date": {
        "required": "Please select a date.",
        "null": "Please select a date.",
        "blank": "Please select a date.",
        "invalid": "Please enter the date in YYYY-MM-DD format.",
    },
    "test_date": {
        "required": "Please select a date.",
        "null": "Please select a date.",
        "blank": "Please select a date.",
        "invalid": "Please enter the date in YYYY-MM-DD format.",
    },
    "start_date": {
        "required": "Please select a start date.",
        "null": "Please select a start date.",
        "blank": "Please select a start date.",
        "invalid": "Please enter the start date in YYYY-MM-DD format.",
    },
    "end_date": {
        "required": "Please select an end date.",
        "null": "Please select an end date.",
        "blank": "Please select an end date.",
        "invalid": "Please enter the end date in YYYY-MM-DD format.",
    },
    "month": {
        "required": "Please select a month.",
        "null": "Please select a month.",
        "blank": "Please select a month.",
        "invalid": "Please select a valid month.",
    },
    "year": {
        "required": "Please select a year.",
        "null": "Please select a year.",
        "blank": "Please select a year.",
        "invalid": "Please select a valid year.",
    },
    "project": {
        "required": "Project is required.",
        "null": "Project is required.",
        "blank": "Project is required.",
        "invalid": "Selected project does not exist.",
        "does_not_exist": "Selected project does not exist.",
    },
    "project_name": {
        "required": "Project is required.",
        "null": "Project is required.",
        "blank": "Project is required.",
        "invalid": "Selected project does not exist.",
    },
    "projectName": {
        "required": "Project is required.",
        "null": "Project is required.",
        "blank": "Project is required.",
        "invalid": "Selected project does not exist.",
    },
    "contractor": {
        "required": "Please select a contractor.",
        "null": "Please select a contractor.",
        "blank": "Please select a contractor.",
        "invalid": "Selected contractor does not exist.",
        "does_not_exist": "Selected contractor does not exist.",
    },
    "contractor_id": {
        "required": "Please select a contractor.",
        "null": "Please select a contractor.",
        "invalid": "Selected contractor does not exist.",
    },
    "contractor_name": {
        "required": "Please select a contractor.",
        "blank": "Please select a contractor.",
    },
    "file": {
        "required": "Please choose a file to upload.",
        "null": "Please choose a file to upload.",
        "empty": "Please choose a file to upload.",
        "invalid": "Please upload a valid file.",
    },
    "attachment": {
        "required": "Please choose a file to upload.",
        "null": "Please choose a file to upload.",
        "empty": "Please choose a file to upload.",
        "invalid": "Please upload a valid file.",
    },
    "username": {
        "required": "Please enter your username.",
        "blank": "Please enter your username.",
    },
    "password": {
        "required": "Please enter your password.",
        "blank": "Please enter your password.",
    },
    "email": {
        "required": "Please enter your email address.",
        "invalid": "Please enter a valid email address.",
    },
    "title": {
        "required": "Please enter a title.",
        "blank": "Please enter a title.",
    },
    "issue_title": {
        "required": "Please enter an issue title.",
        "blank": "Please enter an issue title.",
    },
    "issue_description": {
        "required": "Please describe the issue.",
        "blank": "Please describe the issue.",
    },
}

# Regex patterns for messages that include dynamic values
_PATTERN_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r'^Invalid pk ["\'].*["\'] - object does not exist\.?$', re.I),
        "Selected record does not exist.",
    ),
    (
        re.compile(r"^Object with .+ does not exist\.?$", re.I),
        "Selected record does not exist.",
    ),
    (
        re.compile(r".*already exists\.?$", re.I),
        "A record with the same details already exists.",
    ),
    (
        re.compile(r"^Ensure this value is greater than or equal to 0\.?$", re.I),
        "Value cannot be negative.",
    ),
    (
        re.compile(r"^Ensure this value is greater than or equal to .+$", re.I),
        "Please enter a value within the allowed range.",
    ),
    (
        re.compile(r"^Ensure this value is less than or equal to .+$", re.I),
        "Please enter a value within the allowed range.",
    ),
    (
        re.compile(r"^Ensure this field has no more than \d+ characters\.?$", re.I),
        "This value is too long.",
    ),
    (
        re.compile(r"^Ensure this field has at least \d+ characters\.?$", re.I),
        "This value is too short.",
    ),
    (
        re.compile(r"^Date has wrong format.*$", re.I),
        "Please enter the date in YYYY-MM-DD format.",
    ),
    (
        re.compile(r"^Datetime has wrong format.*$", re.I),
        "Please enter a valid date and time.",
    ),
    (
        re.compile(r"^Maximum upload.*exceeded.*$", re.I),
        "File size exceeds the allowed limit.",
    ),
    (
        re.compile(r"^Unsupported (file|attachment).*$", re.I),
        "Only PDF, JPG, JPEG, PNG and WEBP files are allowed.",
    ),
]


def _code_from_error(err: Any) -> str | None:
    return getattr(err, "code", None)


def _stringify(err: Any) -> str:
    return str(err)


def friendly_field_message(field: str | None, message: str, code: str | None = None) -> str:
    """Map a raw validation message to a user-friendly one."""
    raw = (message or "").strip()
    field_key = (field or "").strip()
    lowered = raw.lower()
    field_map = FIELD_FRIENDLY_MESSAGES.get(field_key) or {}

    # Prefer wording in the message over DRF's default code ("invalid"),
    # which is often attached even to required/null/blank strings.
    if field_map:
        if ("may not be null" in lowered or code == "null") and "null" in field_map:
            return field_map["null"]
        if ("may not be blank" in lowered or code == "blank") and "blank" in field_map:
            return field_map["blank"]
        if ("required" in lowered or code == "required") and "required" in field_map:
            return field_map["required"]
        if "does not exist" in lowered and "does_not_exist" in field_map:
            return field_map["does_not_exist"]
        if code and code in field_map:
            return field_map[code]
        if ("invalid" in lowered or "wrong format" in lowered) and "invalid" in field_map:
            return field_map["invalid"]

    # Exact generic map
    if raw in GENERIC_MESSAGE_MAP:
        return GENERIC_MESSAGE_MAP[raw]

    # Pattern map
    for pattern, replacement in _PATTERN_REPLACEMENTS:
        if pattern.match(raw):
            return replacement

    # Project-ish field names with pk errors
    if field_key.lower() in {"project", "project_name", "projectname", "project_id"}:
        if "does not exist" in lowered or "invalid pk" in lowered:
            return "Selected project does not exist."

    if field_key.lower() in {"contractor", "contractor_id", "contractor_name"}:
        if "does not exist" in lowered or "invalid pk" in lowered:
            return "Selected contractor does not exist."

    # Already friendly-looking custom messages — keep them
    return raw or "Please enter a valid value."


def flatten_errors(detail: Any, parent_field: str | None = None) -> list[dict[str, str]]:
    """
    Flatten DRF / Django error structures into:
      [{"field": "<name|non_field_errors>", "message": "<friendly text>"}, ...]
    """
    items: list[dict[str, str]] = []

    if detail is None:
        return items

    if isinstance(detail, dict):
        for key, value in detail.items():
            field_name = key if parent_field is None else f"{parent_field}.{key}"
            if key in ("non_field_errors", "detail"):
                field_name = parent_field or "non_field_errors"
            items.extend(flatten_errors(value, field_name))
        return items

    if isinstance(detail, (list, tuple)):
        for entry in detail:
            items.extend(flatten_errors(entry, parent_field))
        return items

    # Single ErrorDetail / string
    code = _code_from_error(detail)
    message = friendly_field_message(parent_field, _stringify(detail), code)
    field = parent_field or "non_field_errors"
    if field == "detail":
        field = "non_field_errors"
    items.append({"field": field, "message": message})
    return items


def summarize_errors(errors: list[dict[str, str]], default: str = "Validation failed") -> str:
    """Pick a top-level human message for the errors list."""
    if not errors:
        return default
    if len(errors) == 1:
        return errors[0]["message"]
    return "Please correct the highlighted fields."


def build_error_payload(
    message: str,
    errors: Any = None,
    *,
    default_message: str = "Validation failed",
) -> dict[str, Any]:
    """
    Build the standard PMC error envelope.

    `errors` may be:
      - already a list of {field, message}
      - a DRF serializer.errors dict
      - a string / list of strings
      - None
    """
    if errors is None:
        flattened: list[dict[str, str]] = []
    elif (
        isinstance(errors, list)
        and errors
        and isinstance(errors[0], dict)
        and "message" in errors[0]
    ):
        # Already normalized (optionally missing field)
        flattened = [
            {
                "field": str(item.get("field") or "non_field_errors"),
                "message": friendly_field_message(
                    item.get("field"),
                    str(item.get("message") or ""),
                ),
            }
            for item in errors
            if isinstance(item, dict)
        ]
    else:
        flattened = flatten_errors(errors)

    top = (message or "").strip() or summarize_errors(flattened, default_message)
    # Soften ultra-generic titles when we have field details
    if flattened and top.lower() in {
        "validation failed",
        "invalid input",
        "bad request",
        "error",
        "validation error",
    }:
        top = summarize_errors(flattened, top)

    return {
        "success": False,
        "message": top,
        "errors": flattened,
    }


def error_response(
    message: str,
    errors: Any = None,
    *,
    http_status: int = status.HTTP_400_BAD_REQUEST,
) -> Response:
    return Response(build_error_payload(message, errors), status=http_status)


def integrity_error_message(exc: BaseException) -> str:
    text = str(exc).lower()
    if "unique" in text or "duplicate" in text:
        return "A record with the same details already exists."
    if "foreign key" in text or "violates foreign key" in text:
        return (
            "This record cannot be deleted because it is being used in another module."
            if "delete" in text or "restrict" in text or "cascade" in text
            else "Related record could not be found. Please check your selection."
        )
    if "not null" in text:
        return "Please complete all required fields before submitting."
    return "Unable to save this record. Please check your input and try again."


def aws_error_message() -> str:
    return "Unable to upload the file. Please try again later."
