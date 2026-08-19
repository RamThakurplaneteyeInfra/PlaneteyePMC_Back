"""Cache health / observability API."""

from __future__ import annotations

import time

from django.conf import settings
from django.core.cache import cache
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.rbac import is_admin_user
from core.cache_metrics import get_metrics_snapshot
from core.perf_network import run_network_benchmark


class CacheHealthAPIView(APIView):
    """
    GET /api/system/cache-health/

    Admin / HO / CEO / PMC Head only — Redis status + hit ratios.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (
            request.user.is_superuser
            or is_admin_user(request.user)
        ):
            return Response(
                {"success": False, "message": "Admin access required."},
                status=403,
            )

        backend = settings.CACHES.get("default", {}).get("BACKEND", "")
        using_redis = "redis" in backend.lower()
        redis_info: dict = {}
        ping_ms = None
        redis_ok = False
        redis_error = None

        if using_redis:
            try:
                import redis as redis_lib

                redis_url = settings.CACHES["default"].get("LOCATION") or ""
                client = redis_lib.from_url(
                    redis_url,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                t0 = time.perf_counter()
                client.ping()
                ping_ms = round((time.perf_counter() - t0) * 1000, 3)
                redis_ok = True
                info = client.info()
                redis_info = {
                    "redis_version": info.get("redis_version"),
                    "used_memory_human": info.get("used_memory_human"),
                    "used_memory": info.get("used_memory"),
                    "connected_clients": info.get("connected_clients"),
                    "evicted_keys": info.get("evicted_keys"),
                    "keyspace_hits": info.get("keyspace_hits"),
                    "keyspace_misses": info.get("keyspace_misses"),
                    "uptime_in_seconds": info.get("uptime_in_seconds"),
                }
                kh = float(info.get("keyspace_hits") or 0)
                km = float(info.get("keyspace_misses") or 0)
                total = kh + km
                redis_info["redis_hit_ratio_pct"] = (
                    round((kh / total) * 100, 2) if total else 0.0
                )
            except Exception as exc:
                redis_error = str(exc)
                redis_ok = False

        # Application-level set/get probe
        app_ok = False
        try:
            cache.set("_pmc:healthprobe", "1", 10)
            app_ok = cache.get("_pmc:healthprobe") == "1"
        except Exception as exc:
            redis_error = redis_error or str(exc)

        metrics = get_metrics_snapshot()
        return Response(
            {
                "success": True,
                "message": "Cache health retrieved successfully.",
                "data": {
                    "backend": backend,
                    "using_redis": using_redis,
                    "fallback_mode": not using_redis or not redis_ok,
                    "redis_connection": "ok" if redis_ok else "unavailable",
                    "ping_latency_ms": ping_ms,
                    "application_cache_ok": app_ok,
                    "redis": redis_info,
                    "redis_error": redis_error,
                    "application_metrics": metrics,
                    "ttl_policy": {
                        "overview": getattr(settings, "CACHE_TTL_OVERVIEW", 300),
                        "dashboard": getattr(settings, "CACHE_TTL_DASHBOARD", 300),
                        "dropdown": getattr(settings, "CACHE_TTL_DROPDOWN", 1800),
                        "report": getattr(settings, "CACHE_TTL_REPORT", 900),
                        "reference": getattr(settings, "CACHE_TTL_REFERENCE", 3600),
                        "default": getattr(settings, "CACHE_TTL_DEFAULT", 300),
                    },
                },
            }
        )


class PerfNetworkAPIView(APIView):
    """
    GET /api/system/perf-network/

    Admin-only in-runtime Postgres/Redis RTT from this web process.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (request.user.is_superuser or is_admin_user(request.user)):
            return Response(
                {"success": False, "message": "Admin access required."},
                status=403,
            )
        n = request.query_params.get("n", "20")
        try:
            n_int = int(n)
        except (TypeError, ValueError):
            n_int = 20
        payload = run_network_benchmark(n=n_int)
        return Response(
            {
                "success": True,
                "message": "Network probe completed.",
                "data": payload,
            }
        )
