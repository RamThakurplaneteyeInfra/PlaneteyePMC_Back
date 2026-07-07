"""
Custom DRF exception handler — consistent 429 responses for throttled requests.
"""

from rest_framework.exceptions import Throttled
from rest_framework.views import exception_handler

from .throttling import log_throttled_request


def pmc_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if isinstance(exc, Throttled) and response is not None:
        request = context.get("request")
        view = context.get("view")
        scope = getattr(exc, "scope", None)
        log_throttled_request(request, view, scope, exc.wait)

        response.data = {
            "success": False,
            "message": "Rate limit exceeded. Please try again later.",
            "errors": {
                "detail": "Request was throttled.",
            },
        }

        if exc.wait is not None:
            response["Retry-After"] = str(int(exc.wait) + 1)

    return response
