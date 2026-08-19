"""
In-runtime network latency probes (Postgres + Redis).

Never logs credentials or cache values. Hostnames only.
"""

from __future__ import annotations

import os
import statistics
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.db import connection

_LUA_INCR = """
local key = KEYS[1]
local n = redis.call('INCR', key)
redis.call('EXPIRE', key, 30)
return n
"""


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100) * (len(ordered) - 1)))))
    return round(ordered[idx], 3)


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "avg": None, "p50": None, "p95": None, "max": None}
    return {
        "n": len(values),
        "avg": round(sum(values) / len(values), 3),
        "p50": _pct(values, 50),
        "p95": _pct(values, 95),
        "max": round(max(values), 3),
    }


def classify_redis_host(host: str | None) -> str:
    if not host:
        return "UNSET"
    h = host.lower()
    if h in {"127.0.0.1", "localhost"} or h.endswith(".local"):
        return "LOCAL"
    if "railway.internal" in h or h.endswith(".rlwy.internal"):
        return "PRIVATE / INTERNAL"
    if "proxy.rlwy.net" in h:
        return "PUBLIC / EXTERNAL"
    if h.endswith(".rlwy.net"):
        return "PUBLIC / EXTERNAL"
    return "PUBLIC / EXTERNAL"


def classify_neon_host(host: str | None) -> dict[str, Any]:
    if not host:
        return {"host": None, "endpoint_type": "UNSET", "region": None}
    h = host.lower()
    endpoint = "pooler" if "pooler" in h else "direct"
    region = None
    for token in h.split("."):
        if token.startswith("ap-") or token.startswith("us-") or token.startswith("eu-"):
            region = token
            break
    return {"host": host, "endpoint_type": endpoint, "region": region}


def _safe_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlparse(url).hostname
    except Exception:
        return None


def _railway_runtime() -> dict[str, Any]:
    keys = (
        "RAILWAY_ENVIRONMENT_NAME",
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_SERVICE_NAME",
        "RAILWAY_PROJECT_NAME",
        "RAILWAY_REPLICA_ID",
        "RAILWAY_REPLICA_REGION",
        "RAILWAY_REGION",
        "RAILWAY_PRIVATE_DOMAIN",
        "RAILWAY_PUBLIC_DOMAIN",
        "RAILWAY_DEPLOYMENT_ID",
        "RAILWAY_GIT_COMMIT_SHA",
    )
    data = {k: os.environ.get(k) or None for k in keys}
    replica = os.environ.get("RAILWAY_REPLICA_ID")
    data["replica_present"] = bool(replica)
    return data


def _db_settings_audit() -> dict[str, Any]:
    cfg = settings.DATABASES.get("default") or {}
    host = cfg.get("HOST") or _safe_host(os.environ.get("DATABASE_URL"))
    return {
        "engine": cfg.get("ENGINE"),
        "host": host,
        "neon": classify_neon_host(host),
        "conn_max_age": cfg.get("CONN_MAX_AGE"),
        "sslmode": (cfg.get("OPTIONS") or {}).get("sslmode"),
        "atomic_requests": cfg.get("ATOMIC_REQUESTS", False),
        "disable_server_side_cursors": cfg.get("DISABLE_SERVER_SIDE_CURSORS"),
    }


def _redis_settings_audit() -> dict[str, Any]:
    redis_url = (
        os.environ.get("REDIS_URL")
        or os.environ.get("REDIS_CACHE_URL")
        or (settings.CACHES.get("default") or {}).get("LOCATION")
    )
    host = _safe_host(str(redis_url) if redis_url else None)
    cache_cfg = settings.CACHES.get("default") or {}
    return {
        "django_cache_backend": cache_cfg.get("BACKEND"),
        "host": host,
        "classification": classify_redis_host(host),
        "connect_timeout_s": os.environ.get("REDIS_CONNECT_TIMEOUT", "2"),
        "socket_timeout_s": os.environ.get("REDIS_SOCKET_TIMEOUT", "2"),
        "max_connections": os.environ.get("REDIS_MAX_CONNECTIONS", "50"),
        "web_server": "daphne (entrypoint.sh)" if not os.environ.get("SERVICE_ROLE") or os.environ.get("SERVICE_ROLE") == "web" else os.environ.get("SERVICE_ROLE"),
        "django_settings_module": os.environ.get("DJANGO_SETTINGS_MODULE"),
    }


def _redis_client():
    import redis as redis_lib

    redis_url = (
        os.environ.get("REDIS_URL")
        or os.environ.get("REDIS_CACHE_URL")
        or (settings.CACHES.get("default") or {}).get("LOCATION")
    )
    if not redis_url or not isinstance(redis_url, str) or not redis_url.startswith("redis"):
        return None
    return redis_lib.from_url(
        redis_url,
        socket_connect_timeout=float(os.environ.get("REDIS_CONNECT_TIMEOUT", "2")),
        socket_timeout=float(os.environ.get("REDIS_SOCKET_TIMEOUT", "5")),
    )


def _bench(n: int, fn) -> list[float]:
    samples: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return samples


def run_network_benchmark(n: int = 20) -> dict[str, Any]:
    n = max(5, min(int(n), 50))
    result: dict[str, Any] = {
        "runtime": _railway_runtime(),
        "postgres": _db_settings_audit(),
        "redis": _redis_settings_audit(),
        "benchmarks": {},
        "errors": [],
    }

    pg_samples: list[float] = []
    try:
        with connection.cursor() as cursor:
            for _ in range(n):
                t0 = time.perf_counter()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                pg_samples.append((time.perf_counter() - t0) * 1000)
        result["benchmarks"]["postgres_select_1"] = _summary(pg_samples)
        result["postgres"]["connection_reused"] = connection.connection is not None
    except Exception as exc:
        result["errors"].append(f"postgres: {type(exc).__name__}")
        result["benchmarks"]["postgres_select_1"] = _summary([])

    client = None
    suffix = uuid.uuid4().hex[:12]
    ping_key = f"_pmc:perfnet:ping:{suffix}"
    get_key = f"_pmc:perfnet:get:{suffix}"
    set_key = f"_pmc:perfnet:set:{suffix}"
    incr_key = f"_pmc:perfnet:incr:{suffix}"
    eval_key = f"_pmc:perfnet:eval:{suffix}"
    try:
        client = _redis_client()
        if client is None:
            result["errors"].append("redis: no REDIS_URL / cache LOCATION")
            return result
        client.ping()
        result["benchmarks"]["redis_ping"] = _summary(_bench(n, client.ping))
        client.set(get_key, "1", ex=30)
        result["benchmarks"]["redis_get"] = _summary(_bench(n, lambda: client.get(get_key)))
        result["benchmarks"]["redis_set"] = _summary(
            _bench(n, lambda: client.set(set_key, "1", ex=30))
        )
        client.set(incr_key, "0", ex=30)
        result["benchmarks"]["redis_incr"] = _summary(_bench(n, lambda: client.incr(incr_key)))
        result["benchmarks"]["redis_eval"] = _summary(
            _bench(n, lambda: client.eval(_LUA_INCR, 1, eval_key))
        )
    except Exception as exc:
        result["errors"].append(f"redis: {type(exc).__name__}")
    finally:
        if client is not None:
            try:
                client.delete(ping_key, get_key, set_key, incr_key, eval_key)
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
    return result
