"""
Normalize API error JSON bodies into the PMC standard envelope.

Successful responses (2xx) are never modified.
Only JSON error responses under /api/ are touched.
"""

from __future__ import annotations

import json
import logging

from django.utils.deprecation import MiddlewareMixin

from core.api_errors import build_error_payload, flatten_errors, summarize_errors

logger = logging.getLogger(__name__)

# Extra keys kept on error envelopes (domain-specific payloads).
_PRESERVE_EXTRA_KEYS = frozenset({"dependencies", "data", "code", "details"})


def _already_normalized(errors) -> bool:
    return (
        isinstance(errors, list)
        and (
            not errors
            or (
                isinstance(errors[0], dict)
                and "message" in errors[0]
            )
        )
    )


def _extract_message_and_errors(payload: dict) -> tuple[str, object]:
    """
    Pull message + raw errors from common legacy PMC / DRF shapes.
    """
    if not isinstance(payload, dict):
        return "Request failed", payload

    # Preferred existing shape
    if "success" in payload and payload.get("success") is False:
        message = payload.get("message") or payload.get("detail") or "Request failed"
        errors = payload.get("errors")
        if errors is None and payload.get("detail") is not None:
            errors = payload.get("detail")
        return str(message), errors

    # DRF default {"detail": "..."} or {"field": ["..."]}
    if "detail" in payload and len(payload) == 1:
        return "Request failed", payload["detail"]

    # {"error": "..."} legacy — prefer details/message when present
    if "error" in payload and "success" not in payload:
        message = str(
            payload.get("message")
            or payload.get("error")
            or "Request failed"
        )
        errors = (
            payload.get("errors")
            if payload.get("errors") is not None
            else payload.get("details")
            if payload.get("details") is not None
            else payload.get("error")
        )
        return message, errors

    # Looks like serializer errors at top level
    if any(isinstance(v, (list, dict, str)) for v in payload.values()):
        return "Validation failed", payload

    return "Request failed", payload


class FriendlyAPIErrorMiddleware(MiddlewareMixin):
    """
    Post-process /api/ error responses so clients always receive:

      {
        "success": false,
        "message": "...",
        "errors": [{"field": "...", "message": "..."}]
      }
    """

    def process_response(self, request, response):
        path = getattr(request, "path", "") or ""
        if not path.startswith("/api/"):
            return response

        status_code = getattr(response, "status_code", 200) or 200
        if status_code < 400:
            return response

        content_type = (response.get("Content-Type") or "").lower()
        if "application/json" not in content_type and not hasattr(response, "data"):
            return response

        try:
            if hasattr(response, "data") and isinstance(response.data, dict):
                payload = response.data
            else:
                raw = response.content.decode("utf-8") if response.content else ""
                if not raw:
                    return response
                payload = json.loads(raw)
        except Exception:
            return response

        if not isinstance(payload, dict):
            return response

        # Already in final shape with list errors — leave alone
        if (
            payload.get("success") is False
            and isinstance(payload.get("message"), str)
            and _already_normalized(payload.get("errors"))
        ):
            # Still run messages through friendly mapper via rebuild for consistency
            normalized = build_error_payload(payload["message"], payload.get("errors"))
            for key in _PRESERVE_EXTRA_KEYS:
                if key in payload and key not in normalized:
                    normalized[key] = payload[key]
            return self._write(response, normalized, status_code)

        message, errors = _extract_message_and_errors(payload)

        # If errors already list-of-dicts, keep; else flatten
        if _already_normalized(errors):
            normalized = build_error_payload(message, errors)
        else:
            flattened = flatten_errors(errors)
            if not flattened and message:
                flattened = [{"field": "non_field_errors", "message": str(message)}]
            top = message
            if flattened and str(message).lower() in {
                "validation failed",
                "request failed",
                "error",
                "bad request",
                "invalid input",
            }:
                top = summarize_errors(flattened, str(message))
            normalized = build_error_payload(top, flattened)

        for key in _PRESERVE_EXTRA_KEYS:
            if key in payload and key not in normalized:
                normalized[key] = payload[key]

        return self._write(response, normalized, status_code)

    @staticmethod
    def _write(response, payload: dict, status_code: int):
        # DRF Response
        if hasattr(response, "data"):
            response.data = payload
            try:
                # Force re-render if already rendered
                if getattr(response, "is_rendered", False) and response.accepted_renderer:
                    response._is_rendered = False
                    response.render()
            except Exception:
                logger.debug("FriendlyAPIErrorMiddleware re-render skipped", exc_info=True)
            return response

        # Django JsonResponse / HttpResponse
        try:
            content = json.dumps(payload).encode("utf-8")
            response.content = content
            response["Content-Type"] = "application/json"
            response["Content-Length"] = str(len(content))
            response.status_code = status_code
        except Exception:
            logger.debug("FriendlyAPIErrorMiddleware write skipped", exc_info=True)
        return response
