"""
PMC API rate limiting — cache-based DRF throttling.

All throttle classes are registered globally in REST_FRAMEWORK settings.
Each class is a no-op unless its scope applies to the current request.
"""

from __future__ import annotations

import logging

from rest_framework.throttling import (
    AnonRateThrottle,
    ScopedRateThrottle,
    UserRateThrottle,
)

logger = logging.getLogger("pmc.throttling")

# ---------------------------------------------------------------------------
# Path prefixes (central registry — extend here for new modules)
# ---------------------------------------------------------------------------

THROTTLE_EXEMPT_PATH_PREFIXES = (
    "/api/health/",
    "/swagger/",
    "/redoc/",
    "/admin/",
)

LOGIN_PATHS = (
    "/api/token/",
    "/api/auth/login/",
)

REFRESH_PATHS = (
    "/api/token/refresh/",
    "/api/auth/refresh/",
)

# Future password-reset endpoints (same 5/min IP limit as login)
AUTH_SENSITIVE_PATHS = (
    "/api/auth/forgot-password/",
    "/api/auth/password-reset/",
    "/api/auth/otp-verify/",
    "/api/auth/verify-otp/",
)

ALERTS_PATH_PREFIX = "/api/alerts"
NOTIFICATIONS_PATH_PREFIX = "/api/notifications"

UPLOAD_PATH_PREFIXES = (
    "/api/site-images",
)

FINANCIAL_API_PREFIXES = (
    "/api/contract-values",
    "/api/invoicing",
    "/api/project-dates",
    "/api/correspondence-documents",
    "/api/correspondence",
    "/api/drawings",
    "/api/budget-performance",
    "/api/cost-performance",
    "/api/cashflow",
    "/api/planned-earned-value",
    "/api/planned-vs-actual",
    "/api/contract-performance",
)

EXPORT_QUERY_VALUES = frozenset({"csv", "pdf", "excel", "xlsx", "xls"})

METHOD_SCOPE_MAP = {
    "GET": "user",
    "HEAD": "user",
    "OPTIONS": "user",
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    return path if path.endswith("/") else f"{path}/"


def _path_starts_with(path: str, prefix: str) -> bool:
    normalized = _normalize_path(path)
    prefix_norm = _normalize_path(prefix)
    return normalized.startswith(prefix_norm)


def is_throttle_exempt_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return any(normalized.startswith(_normalize_path(p)) for p in THROTTLE_EXEMPT_PATH_PREFIXES)


def _path_in(path: str, candidates: tuple[str, ...]) -> bool:
    normalized = _normalize_path(path)
    return any(normalized == _normalize_path(candidate) for candidate in candidates)


def _request_path(request) -> str:
    return getattr(request, "path", "") or getattr(request, "path_info", "")


def _request_query_params(request):
    return getattr(request, "query_params", getattr(request, "GET", {}))


def _matches_financial_api(path: str, view) -> bool:
    if getattr(view, "apply_method_scoped_throttle", False):
        return True
    return any(_path_starts_with(path, prefix) for prefix in FINANCIAL_API_PREFIXES)


def _view_throttle_scope(view) -> str | None:
    scope = getattr(view, "throttle_scope", None)
    if isinstance(scope, str) and scope:
        return scope
    return None


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def log_throttled_request(request, view, scope: str | None, wait: float | None = None) -> None:
    user = getattr(request, "user", None)
    username = (
        user.get_username()
        if user and getattr(user, "is_authenticated", False)
        else "anonymous"
    )
    view_name = view.__class__.__name__ if view else "unknown"
    logger.warning(
        "Request throttled | user=%s | ip=%s | method=%s | path=%s | view=%s | scope=%s | wait=%s",
        username,
        _client_ip(request),
        getattr(request, "method", ""),
        getattr(request, "path", ""),
        view_name,
        scope or "unknown",
        wait,
    )


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class PMCScopedRateThrottle(ScopedRateThrottle):
    """Scoped throttle with path-based scope resolution and structured logging."""

    def get_rate(self):
        if not getattr(self, "scope", None):
            from django.core.exceptions import ImproperlyConfigured

            raise ImproperlyConfigured("Cannot get throttle rate; scope is not set.")
        from rest_framework.settings import api_settings

        try:
            return api_settings.DEFAULT_THROTTLE_RATES[self.scope]
        except KeyError as exc:
            from django.core.exceptions import ImproperlyConfigured

            raise ImproperlyConfigured(
                f"No default throttle rate set for '{self.scope}' scope"
            ) from exc

    def allow_request(self, request, view):
        if is_throttle_exempt_path(_request_path(request)):
            return True

        scope = self.get_scope(request, view)
        if scope is None:
            return True

        self.scope = scope
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)

        # Call SimpleRateThrottle — skip ScopedRateThrottle's view.throttle_scope logic.
        allowed = super(ScopedRateThrottle, self).allow_request(request, view)
        if not allowed:
            log_throttled_request(
                request,
                view,
                scope,
                self.wait(),
            )
        return allowed

    def get_scope(self, request, view):
        """Subclasses override to return a scope string or None."""
        return None


class FastUserRateThrottle(UserRateThrottle):
    """
    Same sliding-window user limit as DRF UserRateThrottle, but one Redis RTT.

    Uses a ZSET of request timestamps (Lua) instead of pickle GET + SET.
    Falls back to SimpleRateThrottle on LocMem or Redis errors.
    """

    _LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local cutoff = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local member = ARGV[5]
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local n = redis.call('ZCARD', key)
if n >= limit then
  return 0
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, ttl)
return 1
"""

    def get_rate(self):
        from rest_framework.settings import api_settings

        return api_settings.DEFAULT_THROTTLE_RATES[self.scope]

    def allow_request(self, request, view):
        redis_allowed = self._allow_via_redis(request, view)
        if redis_allowed is not None:
            return redis_allowed
        return super().allow_request(request, view)

    def _allow_via_redis(self, request, view):
        if self.rate is None:
            return True
        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return True

        client_getter = getattr(getattr(self.cache, "client", None), "get_client", None)
        if not callable(client_getter):
            return None
        try:
            self.rate = self.get_rate()
            self.num_requests, self.duration = self.parse_rate(self.rate)
            self.now = self.timer()
            redis_client = client_getter(write=True)
            make_key = getattr(self.cache, "make_key", None)
            redis_key = make_key(self.key) if callable(make_key) else self.key
            allowed = redis_client.eval(
                self._LUA_SLIDING_WINDOW,
                1,
                redis_key,
                str(self.now),
                str(self.now - self.duration),
                str(self.num_requests),
                str(int(self.duration) + 1),
                f"{self.now}:{id(request)}",
            )
            if not allowed:
                self.history = [self.now] * self.num_requests
                return False
            self.history = []
            return True
        except Exception:
            logger.debug("FastUserRateThrottle redis path failed; using cache backend", exc_info=True)
            return None


# Re-export DRF global throttles (configured via scope names in settings)
__all__ = [
    "AnonRateThrottle",
    "UserRateThrottle",
    "FastUserRateThrottle",
    "LoginRateThrottle",
    "RefreshRateThrottle",
    "CreateRateThrottle",
    "UpdateRateThrottle",
    "DeleteRateThrottle",
    "ExportRateThrottle",
    "UploadRateThrottle",
    "NotificationRateThrottle",
    "SearchRateThrottle",
    "MethodScopedRateThrottle",
    "FINANCIAL_API_PREFIXES",
    "THROTTLE_EXEMPT_PATH_PREFIXES",
]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class LoginRateThrottle(PMCScopedRateThrottle):
    """Per-IP login limit (default 100/min; override with LOGIN_THROTTLE_RATE)."""

    scope = "login"

    def get_scope(self, request, view):
        path = _request_path(request)
        if _path_in(path, LOGIN_PATHS) or _path_in(path, AUTH_SENSITIVE_PATHS):
            return "login"
        if _view_throttle_scope(view) == "login":
            return "login"
        return None

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        scope = self.scope or "login"
        return self.cache_format % {"scope": scope, "ident": ident}


class RefreshRateThrottle(PMCScopedRateThrottle):
    """30/min — JWT refresh token endpoints."""

    scope = "refresh"

    def get_scope(self, request, view):
        path = _request_path(request)
        if _path_in(path, REFRESH_PATHS):
            return type(self).scope
        if _view_throttle_scope(view) == "refresh":
            return type(self).scope
        return None


# ---------------------------------------------------------------------------
# CRUD scopes (financial / billing modules)
# ---------------------------------------------------------------------------


class CreateRateThrottle(PMCScopedRateThrottle):
    scope = "create"

    def get_scope(self, request, view):
        if request.method != "POST":
            return None
        explicit = _view_throttle_scope(view)
        if explicit == "create":
            return type(self).scope
        if explicit:
            return None
        if _matches_financial_api(_request_path(request), view):
            return type(self).scope
        return None


class UpdateRateThrottle(PMCScopedRateThrottle):
    scope = "update"

    def get_scope(self, request, view):
        if request.method not in ("PUT", "PATCH"):
            return None
        explicit = _view_throttle_scope(view)
        if explicit == "update":
            return type(self).scope
        if explicit:
            return None
        if _matches_financial_api(_request_path(request), view):
            return type(self).scope
        return None


class DeleteRateThrottle(PMCScopedRateThrottle):
    scope = "delete"

    def get_scope(self, request, view):
        if request.method != "DELETE":
            return None
        explicit = _view_throttle_scope(view)
        if explicit == "delete":
            return type(self).scope
        if explicit:
            return None
        if _matches_financial_api(_request_path(request), view):
            return type(self).scope
        return None


class MethodScopedRateThrottle(PMCScopedRateThrottle):
    """
    Applies method-based scoped limits for financial GET (scope=user / 300/min).
    POST/PUT/PATCH/DELETE are handled by Create/Update/Delete throttles above.
    """

    def get_scope(self, request, view):
        scope_map = getattr(view, "throttle_scope_map", None)
        if scope_map:
            return scope_map.get(request.method.upper())

        explicit = _view_throttle_scope(view)
        if explicit:
            return explicit

        if request.method not in ("GET", "HEAD", "OPTIONS"):
            return None

        if _matches_financial_api(_request_path(request), view):
            return METHOD_SCOPE_MAP.get(request.method.upper(), "user")
        return None


# ---------------------------------------------------------------------------
# Export / upload / alerts / search
# ---------------------------------------------------------------------------


def _is_export_request(request, view) -> bool:
    if getattr(view, "is_export_action", False):
        return True
    params = _request_query_params(request)
    export = str(params.get("export", "")).lower()
    if export in EXPORT_QUERY_VALUES:
        return True
    report_format = str(params.get("report_format", "")).lower()
    if report_format in EXPORT_QUERY_VALUES:
        return True
    return False


class ExportRateThrottle(PMCScopedRateThrottle):
    scope = "export"

    def get_scope(self, request, view):
        if _view_throttle_scope(view) == "export":
            return type(self).scope
        if _is_export_request(request, view):
            return type(self).scope
        return None


class UploadRateThrottle(PMCScopedRateThrottle):
    scope = "upload"

    def get_scope(self, request, view):
        if request.method not in ("POST", "PUT", "PATCH"):
            return None
        if _view_throttle_scope(view) == "upload":
            return type(self).scope
        if getattr(view, "is_upload_api", False):
            return type(self).scope
        if request.FILES:
            return type(self).scope
        path = _request_path(request)
        if any(_path_starts_with(path, prefix) for prefix in UPLOAD_PATH_PREFIXES):
            return type(self).scope
        return None


class NotificationRateThrottle(PMCScopedRateThrottle):
    """Alerts and notification trigger APIs — 120/min."""

    scope = "alerts"

    def get_scope(self, request, view):
        if _view_throttle_scope(view) == "alerts":
            return type(self).scope
        path = _request_path(request)
        if _path_starts_with(path, ALERTS_PATH_PREFIX):
            return type(self).scope
        if _path_starts_with(path, NOTIFICATIONS_PATH_PREFIX):
            return type(self).scope
        return None


class SearchRateThrottle(PMCScopedRateThrottle):
    scope = "search"

    def get_scope(self, request, view):
        if request.method not in ("GET", "HEAD"):
            return None
        if _view_throttle_scope(view) == "search":
            return type(self).scope
        params = _request_query_params(request)
        if params.get("search") or params.get("q"):
            return type(self).scope
        return None
