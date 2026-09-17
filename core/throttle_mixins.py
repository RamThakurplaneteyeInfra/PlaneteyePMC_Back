"""
Optional ViewSet mixins for explicit throttle scope assignment.

Financial modules are covered automatically via path prefixes in core.throttling.
Use these mixins only when a view is outside the default prefix registry.
"""

from .throttling import METHOD_SCOPE_MAP


class MethodScopedThrottleMixin:
    """Enable method-based scoped throttling on non-standard URL paths."""

    apply_method_scoped_throttle = True
    throttle_scope_map = METHOD_SCOPE_MAP


class AlertsThrottleMixin:
    throttle_scope = "alerts"


class ExportThrottleMixin:
    is_export_action = True


class UploadThrottleMixin:
    is_upload_api = True


class SearchThrottleMixin:
    throttle_scope = "search"
