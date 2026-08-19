"""Measure Django → Postgres / Redis RTT from the current process.

Usage:
  python manage.py perf_network
  python manage.py perf_network --n 20

Run this ON the Railway web service (railway run / one-off) for in-runtime numbers.
Does not print credentials or Redis values.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from core.perf_network import run_network_benchmark


class Command(BaseCommand):
    help = "Benchmark PostgreSQL SELECT 1 and Redis PING/GET/SET/INCR/EVAL RTT"

    def add_arguments(self, parser):
        parser.add_argument("--n", type=int, default=20)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        payload = run_network_benchmark(n=options["n"])
        if options["json"]:
            self.stdout.write(json.dumps(payload, indent=2, default=str))
            return
        runtime = payload.get("runtime") or {}
        pg = payload.get("postgres") or {}
        rd = payload.get("redis") or {}
        self.stdout.write("=== runtime ===")
        for key in (
            "RAILWAY_ENVIRONMENT_NAME",
            "RAILWAY_SERVICE_NAME",
            "RAILWAY_REPLICA_REGION",
            "RAILWAY_REGION",
            "RAILWAY_PUBLIC_DOMAIN",
            "RAILWAY_PRIVATE_DOMAIN",
        ):
            self.stdout.write(f"  {key}={runtime.get(key)}")
        self.stdout.write("=== postgres ===")
        self.stdout.write(f"  host={pg.get('host')}")
        self.stdout.write(f"  neon={pg.get('neon')}")
        self.stdout.write(f"  conn_max_age={pg.get('conn_max_age')}")
        self.stdout.write("=== redis ===")
        self.stdout.write(f"  host={rd.get('host')}")
        self.stdout.write(f"  classification={rd.get('classification')}")
        self.stdout.write(f"  backend={rd.get('django_cache_backend')}")
        self.stdout.write("=== benchmarks (ms) ===")
        for name, stats in (payload.get("benchmarks") or {}).items():
            self.stdout.write(
                f"  {name}: avg={stats.get('avg')} p50={stats.get('p50')} "
                f"p95={stats.get('p95')} max={stats.get('max')}"
            )
        if payload.get("errors"):
            self.stdout.write("=== errors ===")
            for err in payload["errors"]:
                self.stdout.write(f"  {err}")
