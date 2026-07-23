"""
Centralized DRF exception handler for the PMC API.

Goals:
  - Consistent {success, message, errors[{field, message}]} envelope for failures
  - Friendly, actionable messages for end users
  - Full technical details logged server-side only
  - Successful responses are never modified
"""

from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, OperationalError, ProgrammingError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .api_errors import (
    aws_error_message,
    build_error_payload,
    flatten_errors,
    integrity_error_message,
    summarize_errors,
)
from .throttling import log_throttled_request

logger = logging.getLogger(__name__)


def _is_aws_exception(exc: BaseException) -> bool:
    name = type(exc).__module__ + "." + type(exc).__name__
    text = str(exc).lower()
    return (
        "botocore" in name
        or "boto3" in name
        or "clienterror" in name.lower()
        or "nosuchbucket" in text
        or "accessdenied" in text and "s3" in text
    )


def _status_for_exception(exc: BaseException, fallback: int) -> int:
    if isinstance(exc, APIException):
        return getattr(exc, "status_code", fallback)
    if isinstance(exc, (Http404, NotFound)):
        return status.HTTP_404_NOT_FOUND
    if isinstance(exc, (PermissionDenied, DjangoPermissionDenied)):
        return status.HTTP_403_FORBIDDEN
    if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
        return status.HTTP_401_UNAUTHORIZED
    if isinstance(exc, IntegrityError):
        return status.HTTP_400_BAD_REQUEST
    if isinstance(exc, (OperationalError, ProgrammingError)):
        return status.HTTP_503_SERVICE_UNAVAILABLE
    return fallback


def _payload_for_drf_response(exc: BaseException, response: Response) -> dict:
    detail = getattr(exc, "detail", response.data)

    if isinstance(exc, Throttled):
        return build_error_payload(
            "Rate limit exceeded. Please try again later.",
            [{"field": "non_field_errors", "message": "Too many requests. Please wait a moment and try again."}],
        )

    if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
        errors = flatten_errors(detail)
        message = summarize_errors(
            errors,
            default="Incorrect username or password."
            if isinstance(exc, AuthenticationFailed)
            else "Please log in to continue.",
        )
        # Prefer auth-specific wording
        if isinstance(exc, AuthenticationFailed):
            text = str(detail)
            lowered = text.lower()
            if "disabled" in lowered or "inactive" in lowered:
                message = (
                    "Your account has been disabled. Please contact the administrator."
                )
            else:
                message = "Incorrect username or password."
            errors = [{"field": "non_field_errors", "message": message}]
        return build_error_payload(message, errors)

    if isinstance(exc, (PermissionDenied, DjangoPermissionDenied)):
        return build_error_payload(
            "You do not have permission to perform this action.",
            [
                {
                    "field": "non_field_errors",
                    "message": "You do not have permission to perform this action.",
                }
            ],
        )

    if isinstance(exc, (NotFound, Http404)):
        return build_error_payload(
            "The requested record could not be found.",
            [
                {
                    "field": "non_field_errors",
                    "message": "The requested record could not be found.",
                }
            ],
        )

    if isinstance(exc, ValidationError):
        errors = flatten_errors(detail)
        return build_error_payload(
            summarize_errors(
                errors,
                "Some information is missing or invalid. Please review the highlighted fields.",
            ),
            errors,
        )

    # Generic APIException / already-shaped response data
    errors = flatten_errors(detail)
    if errors:
        return build_error_payload(summarize_errors(errors), errors)

    return build_error_payload(
        "An unexpected error occurred. Please try again later.",
        [{"field": "non_field_errors", "message": "An unexpected error occurred. Please try again later."}],
    )


def pmc_exception_handler(exc, context):
    """
    DRF exception handler used by REST_FRAMEWORK['EXCEPTION_HANDLER'].
    """
    request = context.get("request")
    view = context.get("view")

    # --- Database integrity / operational issues (not handled by DRF) ---
    if isinstance(exc, IntegrityError):
        logger.warning(
            "IntegrityError on %s %s: %s",
            getattr(request, "method", "?"),
            getattr(request, "path", "?"),
            exc,
        )
        return Response(
            build_error_payload(integrity_error_message(exc)),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, (OperationalError, ProgrammingError)):
        logger.exception(
            "Database error on %s %s",
            getattr(request, "method", "?"),
            getattr(request, "path", "?"),
        )
        return Response(
            build_error_payload(
                "Unable to connect to the server.",
                [
                    {
                        "field": "non_field_errors",
                        "message": "Unable to connect to the server. Please try again later.",
                    }
                ],
            ),
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            detail = exc.message_dict
        elif hasattr(exc, "messages"):
            detail = list(exc.messages)
        else:
            detail = [str(exc)]
        errors = flatten_errors(detail)
        return Response(
            build_error_payload(
                summarize_errors(
                    errors,
                    "Some information is missing or invalid. Please review the highlighted fields.",
                ),
                errors,
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if _is_aws_exception(exc):
        logger.exception(
            "AWS/S3 error on %s %s",
            getattr(request, "method", "?"),
            getattr(request, "path", "?"),
        )
        return Response(
            build_error_payload(
                aws_error_message(),
                [{"field": "file", "message": aws_error_message()}],
            ),
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # --- Standard DRF handling ---
    response = exception_handler(exc, context)

    if isinstance(exc, Throttled) and response is not None:
        scope = getattr(exc, "scope", None)
        log_throttled_request(request, view, scope, exc.wait)
        response.data = build_error_payload(
            "Rate limit exceeded. Please try again later.",
            [
                {
                    "field": "non_field_errors",
                    "message": "Too many requests. Please wait a moment and try again.",
                }
            ],
        )
        if exc.wait is not None:
            response["Retry-After"] = str(int(exc.wait) + 1)
        return response

    if response is not None:
        response.data = _payload_for_drf_response(exc, response)
        return response

    # --- Unhandled exceptions → safe 500 ---
    logger.exception(
        "Unhandled exception on %s %s (view=%s)",
        getattr(request, "method", "?"),
        getattr(request, "path", "?"),
        getattr(view, "__class__", type("?", (), {})).__name__,
    )
    return Response(
        build_error_payload(
            "An unexpected error occurred. Please try again later.",
            [
                {
                    "field": "non_field_errors",
                    "message": "An unexpected error occurred. Please try again later.",
                }
            ],
        ),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
