"""
Performance audit: profile key PMC API endpoints (query count, timing, payload).

Usage:
  python manage.py perf_audit
  python manage.py perf_audit --rounds 3 --username <user>
"""

from __future__ import annotations

import json
import statistics
import time
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection, reset_queries
from django.test.utils import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

# High-traffic / historically slow GET endpoints to benchmark.
ENDPOINTS: list[tuple[str, str]] = [
    ("GET", "/api/projects/"),
    ("GET", "/api/projects/overview/"),
    ("GET", "/api/projects/overview/?paginate=true&page=1&page_size=20"),
    ("GET", "/api/projects/dropdown/"),
    ("GET", "/api/projects/init-list/"),
    ("GET", "/api/dpr/"),
    ("GET", "/api/monthly-scope/"),
    ("GET", "/api/project-dates/"),
    ("GET", "/api/project-eot/"),
    ("GET", "/api/cost-performance/"),
    ("GET", "/api/cashflow/"),
    ("GET", "/api/contract-values/"),
    ("GET", "/api/invoicing/"),
    ("GET", "/api/budget-performance/"),
    ("GET", "/api/construction-progress/"),
    ("GET", "/api/project-progress/"),
    ("GET", "/api/bottlenecks/"),
    ("GET", "/api/bottlenecks/summary/"),
    ("GET", "/api/health-safety/"),
    ("GET", "/api/hse/"),
    ("GET", "/api/project-quality/"),
    ("GET", "/api/site-images/"),
    ("GET", "/api/correspondence-documents/"),
    ("GET", "/api/equipment/"),
    ("GET", "/api/manpower-mh/"),
    ("GET", "/api/plant-machinery/"),
    ("GET", "/api/users/"),
    ("GET", "/api/alerts/"),
    ("GET", "/api/sites/"),
    ("GET", "/api/contracts/"),
    ("GET", "/api/planned-vs-actual/"),
    ("GET", "/api/meeting-documents/"),
    ("GET", "/api/testing-documents/"),
    ("GET", "/api/project-feedback/"),
    ("GET", "/api/health/"),
]


class Command(BaseCommand):
    help = "Benchmark key API endpoints: latency, SQL count, payload size"

    def add_arguments(self, parser):
        parser.add_argument("--rounds", type=int, default=3)
        parser.add_argument("--username", type=str, default="")
        parser.add_argument("--json-out", type=str, default="perf_audit_results.json")

    def handle(self, *args, **options):
        rounds = max(1, int(options["rounds"]))
        username = (options["username"] or "").strip()
        user = self._resolve_user(username)
        client = APIClient()
        token = str(RefreshToken.for_user(user).access_token)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        results: list[dict[str, Any]] = []
        self.stdout.write(
            self.style.NOTICE(
                f"Profiling {len(ENDPOINTS)} endpoints × {rounds} rounds "
                f"as user={user.username!r}"
            )
        )

        with override_settings(DEBUG=True):
            for method, path in ENDPOINTS:
                samples: list[dict[str, Any]] = []
                for _ in range(rounds):
                    reset_queries()
                    t0 = time.perf_counter()
                    if method == "GET":
                        resp = client.get(path)
                    else:
                        resp = client.generic(method, path)
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    queries = list(connection.queries)
                    sql_ms = sum(float(q.get("time") or 0) * 1000 for q in queries)
                    body = resp.content or b""
                    samples.append(
                        {
                            "status": resp.status_code,
                            "elapsed_ms": round(elapsed_ms, 2),
                            "sql_count": len(queries),
                            "sql_ms": round(sql_ms, 2),
                            "payload_kb": round(len(body) / 1024, 2),
                            "slowest_sql_ms": round(
                                max(
                                    (float(q.get("time") or 0) * 1000 for q in queries),
                                    default=0.0,
                                ),
                                2,
                            ),
                        }
                    )

                ok = [s for s in samples if 200 <= s["status"] < 400]
                use = ok or samples
                times = [s["elapsed_ms"] for s in use]
                row = {
                    "method": method,
                    "path": path,
                    "status": use[0]["status"] if use else None,
                    "avg_ms": round(statistics.mean(times), 2),
                    "p95_ms": round(
                        statistics.quantiles(times, n=20)[18]
                        if len(times) >= 20
                        else max(times),
                        2,
                    ),
                    "max_ms": round(max(times), 2),
                    "avg_sql_count": round(
                        statistics.mean(s["sql_count"] for s in use), 1
                    ),
                    "avg_sql_ms": round(statistics.mean(s["sql_ms"] for s in use), 2),
                    "avg_payload_kb": round(
                        statistics.mean(s["payload_kb"] for s in use), 2
                    ),
                    "max_slowest_sql_ms": round(
                        max(s["slowest_sql_ms"] for s in use), 2
                    ),
                }
                results.append(row)
                flag = "SLOW" if row["avg_ms"] >= 300 else ("OK" if row["avg_ms"] < 100 else "MED")
                self.stdout.write(
                    f"[{flag}] {method} {path}  "
                    f"{row['avg_ms']}ms  q={row['avg_sql_count']}  "
                    f"sql={row['avg_sql_ms']}ms  {row['avg_payload_kb']}KB  "
                    f"status={row['status']}"
                )

        out_path = options["json_out"]
        payload = {
            "user": user.username,
            "rounds": rounds,
            "endpoint_count": len(results),
            "results": sorted(results, key=lambda r: r["avg_ms"], reverse=True),
            "summary": self._summary(results),
        }
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path}"))
        self._print_summary(payload["summary"])

    def _resolve_user(self, username: str):
        if username:
            user = User.objects.filter(username=username).first()
            if user:
                return user
        # Prefer admin / PMC Head for broad RBAC visibility
        for name in ("admin", "pmc_head", "pmc_head1", "init_test_uday"):
            user = User.objects.filter(username=name).first()
            if user:
                return user
        user = (
            User.objects.filter(is_superuser=True).first()
            or User.objects.filter(is_staff=True).first()
            or User.objects.order_by("id").first()
        )
        if not user:
            user = User.objects.create_superuser(
                username="perf_audit_admin",
                email="perf@example.com",
                password="PerfAudit@123",
            )
        return user

    @staticmethod
    def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
        timed = [r for r in results if r.get("avg_ms") is not None]
        def bucket(lo, hi=None):
            if hi is None:
                return sum(1 for r in timed if r["avg_ms"] >= lo)
            return sum(1 for r in timed if lo <= r["avg_ms"] < hi)

        return {
            "fast_lt_100": bucket(0, 100),
            "medium_100_300": bucket(100, 300),
            "slow_300_1000": bucket(300, 1000),
            "critical_gte_1000": bucket(1000),
            "avg_response_ms": round(
                statistics.mean(r["avg_ms"] for r in timed) if timed else 0, 2
            ),
            "avg_sql_count": round(
                statistics.mean(r["avg_sql_count"] for r in timed) if timed else 0, 1
            ),
        }

    def _print_summary(self, summary: dict[str, Any]):
        self.stdout.write(
            self.style.NOTICE(
                f"Summary: fast={summary['fast_lt_100']} med={summary['medium_100_300']} "
                f"slow={summary['slow_300_1000']} critical={summary['critical_gte_1000']} "
                f"avg={summary['avg_response_ms']}ms sql_avg={summary['avg_sql_count']}"
            )
        )
