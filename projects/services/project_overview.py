"""
Project Overview aggregation service.

Builds lightweight project-card payloads with bulk queries (no N+1).
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, QuerySet

from core.cache_keys import build_rbac_list_cache_key
from core.cache_ops import TTL_OVERVIEW
from core.cache_swr import get_or_rebuild
from core.cache_tags import invalidate_tags

from bottlenecks.models import Bottleneck
from construction_progress.models.construction_progress import ConstructionProgress
from cost_performance.models import ProjectCostPerformance
from dpr.models import DailyProgressReport
from health_safety.models import HSERecord
from project_quality_status.models.project_quality_status import ProjectQualityStatus
from projects.models import Project

from .overview_kpis import (
    build_cost_kpi,
    build_progress_kpi,
    build_quality_kpi,
    build_safety_kpi,
    build_time_kpi,
    compute_health_score,
    compute_project_status,
    extract_project_code,
)

CACHE_PREFIX = "project_overview_v4"
CACHE_TTL_SECONDS = TTL_OVERVIEW
# Soft TTL = configured overview TTL; hard TTL keeps stale payload for SWR window.
CACHE_HARD_TTL_SECONDS = TTL_OVERVIEW * 2


def invalidate_project_overview_cache() -> None:
    """
    Invalidate overview cards + dropdown/project list caches.

    Prefer invalidate_overview_kpi_cache() for KPI source-model writes so
    dropdown/init-list are not churned on every DPR/cost/quality update.
    """
    invalidate_tags("overview", "dropdown", "projects")


def invalidate_overview_kpi_cache() -> None:
    """Invalidate only overview card cache (KPI aggregates)."""
    invalidate_tags("overview")


def invalidate_project_directory_cache() -> None:
    """Invalidate dropdown / init-list style project directory caches."""
    invalidate_tags("dropdown", "projects")


class ProjectOverviewService:
    """Aggregate card fields for all projects in a filtered queryset."""

    DEFAULT_ORDERING = "-updated_at"
    ALLOWED_ORDERING = {
        "name",
        "-name",
        "updated_at",
        "-updated_at",
        "status",
        "-status",
        "client_name",
        "-client_name",
        "client",
        "-client",
        "health_score",
        "-health_score",
        "project_name",
        "-project_name",
    }

    def __init__(self, queryset: QuerySet[Project], request=None):
        self.base_queryset = queryset
        self.request = request

    @staticmethod
    def _safe_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _truthy(value) -> bool:
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    def get_paginated_overview(
        self,
        *,
        paginate: bool | str = False,
        page: int = 1,
        page_size: int = 20,
        search: str = "",
        client: str = "",
        status: str = "",
        billing_status: str = "",
        project_type: str = "",
        project_name: str = "",
        ordering: str = "",
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """
        Build overview cards.

        Default (paginate=false): return every matching card in one response.
        Optional (paginate=true): slice by page / page_size and include pagination meta.
        """
        paginate = self._truthy(paginate) if not isinstance(paginate, bool) else paginate
        page = max(1, self._safe_int(page, 1))
        page_size = min(100, max(1, self._safe_int(page_size, 20)))

        cache_key = None
        if use_cache and self.request is not None:
            cache_key = build_rbac_list_cache_key(
                CACHE_PREFIX,
                self.request,
                extra_parts=[
                    f"pg{int(paginate)}",
                    f"p{page}" if paginate else "pall",
                    f"ps{page_size}" if paginate else "psall",
                    f"s{search}",
                    f"c{client}",
                    f"st{status}",
                    f"bs{billing_status}",
                    f"pt{project_type}",
                    f"pn{project_name}",
                    f"o{ordering or self.DEFAULT_ORDERING}",
                ],
                use_query_string=False,
            )

            def _build() -> dict[str, Any]:
                return self._build_payload(
                    paginate=paginate,
                    page=page,
                    page_size=page_size,
                    search=search,
                    client=client,
                    status=status,
                    billing_status=billing_status,
                    project_type=project_type,
                    project_name=project_name,
                    ordering=ordering,
                )

            return get_or_rebuild(
                cache_key,
                _build,
                soft_ttl=CACHE_TTL_SECONDS,
                hard_ttl=CACHE_HARD_TTL_SECONDS,
                prefix=CACHE_PREFIX,
            )

        # use_cache=False: caller (e.g. ProjectViewSet.overview) owns the cache layer.
        return self._build_payload(
            paginate=paginate,
            page=page,
            page_size=page_size,
            search=search,
            client=client,
            status=status,
            billing_status=billing_status,
            project_type=project_type,
            project_name=project_name,
            ordering=ordering,
        )

    def _build_payload(
        self,
        *,
        paginate: bool,
        page: int,
        page_size: int,
        search: str,
        client: str,
        status: str,
        billing_status: str,
        project_type: str,
        project_name: str,
        ordering: str,
    ) -> dict[str, Any]:
        from core.cache_profiling import profile_queries

        with profile_queries("project_overview"):
            return self._build_payload_inner(
                paginate=paginate,
                page=page,
                page_size=page_size,
                search=search,
                client=client,
                status=status,
                billing_status=billing_status,
                project_type=project_type,
                project_name=project_name,
                ordering=ordering,
            )

    # Orderings that can be applied in SQL before KPI build (page-then-aggregate).
    _DB_ORDERING_MAP = {
        "name": "name",
        "-name": "-name",
        "updated_at": "updated_at",
        "-updated_at": "-updated_at",
        "status": "status",
        "-status": "-status",
        "client_name": "client_name",
        "-client_name": "-client_name",
        "client": "client_name",
        "-client": "-client_name",
        "project_name": "name",
        "-project_name": "-name",
    }

    def _build_payload_inner(
        self,
        *,
        paginate: bool,
        page: int,
        page_size: int,
        search: str,
        client: str,
        status: str,
        billing_status: str,
        project_type: str,
        project_name: str,
        ordering: str,
    ) -> dict[str, Any]:
        qs = self._filtered_queryset(
            search=search,
            client=client,
            status=status,
            billing_status=billing_status,
            project_type=project_type,
            project_name=project_name,
        )

        order_key = (ordering or self.DEFAULT_ORDERING).strip()
        db_order = self._DB_ORDERING_MAP.get(order_key)

        # Paginated + DB-sortable: count + page in SQL, KPI only for that page.
        # Preserves health_score formulas; health_score ordering still needs full build.
        if paginate and db_order:
            total = qs.count()
            page_qs = qs.order_by(db_order, "id")
            start = (page - 1) * page_size
            projects = list(page_qs[start : start + page_size])
            cards = self._build_cards(projects)
            return {
                "success": True,
                "message": "Project overview retrieved successfully.",
                "data": cards,
                "count": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size if page_size else 0,
            }

        projects = list(qs)
        cards = self._build_cards(projects)
        cards = self._sort_cards(cards, ordering)

        total = len(cards)
        if paginate:
            start = (page - 1) * page_size
            end = start + page_size
            page_cards = cards[start:end]
            return {
                "success": True,
                "message": "Project overview retrieved successfully.",
                "data": page_cards,
                "count": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size if page_size else 0,
            }
        return {
            "success": True,
            "message": "Project overview retrieved successfully.",
            "count": total,
            "data": cards,
        }

    def _filtered_queryset(
        self,
        *,
        search: str,
        client: str,
        status: str,
        billing_status: str,
        project_type: str,
        project_name: str,
    ) -> QuerySet[Project]:
        qs = (
            self.base_queryset.select_related("team_lead", "completed_by")
            .only(
                "id",
                "name",
                "client_name",
                "location",
                "status",
                "billing_status",
                "updated_at",
                "project_start",
                "commencement_date",
                "start_date",
                "contract_finish",
                "end_date",
                "forecast_finish",
                "delay_days",
                "completed_at",
                "completion_notes",
                "team_lead_id",
                "team_lead__id",
                "team_lead__username",
                "team_lead__first_name",
                "team_lead__last_name",
                "completed_by_id",
                "completed_by__id",
                "completed_by__username",
                "completed_by__first_name",
                "completed_by__last_name",
            )
        )

        search = (search or "").strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(client_name__icontains=search)
                | Q(location__icontains=search)
            )

        client = (client or "").strip()
        if client:
            qs = qs.filter(client_name__icontains=client)

        status_param = (status or "").strip()
        if status_param:
            statuses = [s.strip() for s in status_param.split(",") if s.strip()]
            if statuses:
                qs = qs.filter(status__in=statuses)
                # Never leak merged duplicates unless caller explicitly asks for merged.
                if "merged" not in statuses:
                    qs = qs.exclude(status="merged")
        else:
            # Dashboard cards: live active + completed (historical) by default.
            # planning / on_hold / merged stay hidden unless explicitly filtered.
            qs = qs.filter(status__in=["active", "completed"])

        project_name = (project_name or "").strip()
        if project_name:
            qs = qs.filter(name__icontains=project_name)

        billing_param = (billing_status or "").strip()
        if billing_param:
            from projects.services.project_completion import normalize_billing_status

            billing_values = []
            for raw in billing_param.split(","):
                normalized = normalize_billing_status(raw)
                if normalized:
                    billing_values.append(normalized)
            if billing_values:
                qs = qs.filter(billing_status__in=billing_values)

        # project_type is not a stored Project field yet — reserved for future filter.
        _ = (project_type or "").strip()

        return qs.order_by("id")

    def _build_cards(self, projects: list[Project]) -> list[dict[str, Any]]:
        if not projects:
            return []

        project_ids = [p.id for p in projects]
        project_names = [p.name for p in projects]

        # Overlap independent KPI source queries (same formulas; lower wall time
        # when DB RTT dominates, e.g. remote Neon).
        from concurrent.futures import ThreadPoolExecutor
        from django.db import close_old_connections

        def _run(fn, *args):
            close_old_connections()
            try:
                return fn(*args)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=6) as pool:
            f_progress = pool.submit(_run, self._latest_progress_by_name, project_names)
            f_scope = pool.submit(_run, self._scope_progress_by_project_id, project_ids)
            f_schedule = pool.submit(_run, self._schedule_dates_by_project_id, project_ids)
            f_eot = pool.submit(
                _run, self._latest_approved_eot_date_by_project_id, project_ids
            )
            f_cost = pool.submit(_run, self._latest_cost_by_project_id, project_ids)
            f_quality = pool.submit(_run, self._latest_quality_by_name, project_names)
            f_safety = pool.submit(_run, self._safety_by_name, project_names)
            f_issues = pool.submit(_run, self._issue_counts_by_project_id, project_ids)
            f_dpr = pool.submit(_run, self._dpr_counts_by_name, project_names)

            progress_by_name = f_progress.result()
            scope_pct_by_id = f_scope.result()
            schedule_by_id = f_schedule.result()
            eot_by_id = f_eot.result()
            cost_by_id = f_cost.result()
            quality_by_name = f_quality.result()
            safety_by_name = f_safety.result()
            issues_by_id = f_issues.result()
            dpr_by_name = f_dpr.result()

        cards: list[dict[str, Any]] = []
        for project in projects:
            schedule = schedule_by_id.get(project.id) or {}
            eot_date = eot_by_id.get(project.id)
            contract_finish = schedule.get("contract_finish") or project.contract_finish
            project_start = schedule.get("project_start") or project.project_start

            progress = build_progress_kpi(
                scope_pct=scope_pct_by_id.get(project.id),
                progress_row=progress_by_name.get(project.name),
            )
            time_kpi = build_time_kpi(
                project,
                progress["percentage"],
                latest_eot_date=eot_date,
                contract_finish=contract_finish,
                project_start=project_start,
            )
            cost = build_cost_kpi(cost_by_id.get(project.id))
            quality = build_quality_kpi(quality_by_name.get(project.name))
            safety = build_safety_kpi(safety_by_name.get(project.name))
            health_score = compute_health_score(
                progress["percentage"],
                time_kpi["percentage"],
                cost["percentage"],
                quality["percentage"],
                safety["percentage"],
            )
            project_status = compute_project_status(
                project,
                latest_eot_date=eot_date,
                contract_finish=contract_finish,
            )
            team_lead = project.team_lead
            completed_by = project.completed_by
            cards.append(
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "project_code": extract_project_code(project.name),
                    "client": project.client_name or "",
                    "project_type": "",
                    "project_icon": "",
                    "status": project.status,
                    "billing_status": project.billing_status
                    or Project.BILLING_STATUS_PENDING,
                    "project_status": project_status,
                    "completed_at": project.completed_at.isoformat()
                    if project.completed_at
                    else None,
                    "completed_by": self._team_leader_payload(completed_by),
                    "health_score": health_score,
                    "progress": progress,
                    "time": time_kpi,
                    "cost": cost,
                    "quality": quality,
                    "safety": safety,
                    "team_leader": self._team_leader_payload(team_lead),
                    "location": project.location or "",
                    "issues_count": issues_by_id.get(project.id, 0),
                    "dpr_count": dpr_by_name.get(project.name, 0),
                    "last_updated": project.updated_at.isoformat()
                    if project.updated_at
                    else None,
                    "compare_enabled": project.status == "active",
                }
            )
        return cards

    @staticmethod
    def _team_leader_payload(user) -> dict[str, Any] | None:
        if user is None:
            return None
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        return {
            "id": user.id,
            "username": user.username,
            "full_name": full_name or user.username,
        }

    @staticmethod
    def _latest_progress_by_name(names: list[str]) -> dict[str, ConstructionProgress]:
        rows = (
            ConstructionProgress.objects.filter(projectName__in=names)
            .only(
                "projectName",
                "progressMonth",
                "plannedProgress",
                "actualProgress",
                "performancePercentage",
            )
            .order_by("projectName", "-progressMonth")
        )
        latest: dict[str, ConstructionProgress] = {}
        for row in rows:
            if row.projectName not in latest:
                latest[row.projectName] = row
        return latest

    @staticmethod
    def _scope_progress_by_project_id(project_ids: list[int]) -> dict[int, float]:
        """
        Bulk Assigned Scope progress:
          SUM(cumulative_quantity) / SUM(planned_quantity) * 100
        """
        from django.db.models import Sum

        from monthly_scope.models import MonthlyScopeWork

        rows = (
            MonthlyScopeWork.objects.filter(project_id__in=project_ids)
            .values("project_id")
            .annotate(
                planned=Sum("planned_quantity"),
                executed=Sum("cumulative_quantity"),
            )
        )
        out: dict[int, float] = {}
        for row in rows:
            planned = float(row["planned"] or 0)
            executed = float(row["executed"] or 0)
            if planned <= 0:
                continue
            out[row["project_id"]] = min(100.0, (executed / planned) * 100.0)
        return out

    @staticmethod
    def _schedule_dates_by_project_id(project_ids: list[int]) -> dict[int, dict]:
        """Prefer SCL ProjectDates row per project."""
        from project_dates.models import ProjectDates

        rows = (
            ProjectDates.objects.filter(
                project_id__in=project_ids,
                date_type=ProjectDates.DATE_TYPE_SCL,
            )
            .only("project_id", "project_start", "contract_finish", "forecast_finish", "eot_date")
            .order_by("project_id", "id")
        )
        out: dict[int, dict] = {}
        for row in rows:
            if row.project_id in out:
                continue
            out[row.project_id] = {
                "project_start": row.project_start,
                "contract_finish": row.contract_finish,
                "forecast_finish": row.forecast_finish,
                "eot_date": row.eot_date,
            }
        return out

    @staticmethod
    def _latest_approved_eot_date_by_project_id(project_ids: list[int]) -> dict:
        """Latest approved active EOT revised_completion_date per project."""
        from project_dates.eot_models import ProjectEOT

        rows = (
            ProjectEOT.objects.filter(
                project_id__in=project_ids,
                is_active=True,
                status=ProjectEOT.STATUS_APPROVED,
            )
            .only("project_id", "eot_number", "revised_completion_date")
            .order_by("project_id", "-eot_number", "-revised_completion_date", "-id")
        )
        out = {}
        for row in rows:
            if row.project_id not in out and row.revised_completion_date:
                out[row.project_id] = row.revised_completion_date
        return out

    @staticmethod
    def _latest_cost_by_project_id(project_ids: list[int]) -> dict[int, ProjectCostPerformance]:
        rows = (
            ProjectCostPerformance.objects.filter(project_id__in=project_ids)
            .only("id", "project_id", "month_year", "cpi", "bcwp", "acwp")
            .order_by("project_id", "-id")
        )
        latest: dict[int, ProjectCostPerformance] = {}
        for row in rows:
            if row.project_id not in latest:
                latest[row.project_id] = row
        return latest

    @staticmethod
    def _latest_quality_by_name(names: list[str]) -> dict[str, ProjectQualityStatus]:
        rows = (
            ProjectQualityStatus.objects.filter(projectName__in=names)
            .only(
                "projectName",
                "month",
                "year",
                "tests_required",
                "tests_conducted",
                "tests_passed",
                "tests_failed",
            )
            .order_by("projectName", "-year", "-month")
        )
        latest: dict[str, ProjectQualityStatus] = {}
        for row in rows:
            if row.projectName not in latest:
                latest[row.projectName] = row
        return latest

    @staticmethod
    def _safety_by_name(names: list[str]) -> dict[str, HSERecord]:
        rows = HSERecord.objects.filter(projectName__in=names).only(
            "projectName",
            "fatalities",
            "significant",
            "major",
            "minor",
            "nearMiss",
            "totalManhours",
        )
        return {row.projectName: row for row in rows}

    @staticmethod
    def _issue_counts_by_project_id(project_ids: list[int]) -> dict[int, int]:
        rows = (
            Bottleneck.objects.filter(
                project_id__in=project_ids,
                type=Bottleneck.TYPE_ISSUE,
            )
            .values("project_id")
            .annotate(count=Count("id"))
        )
        return {row["project_id"]: row["count"] for row in rows}

    @staticmethod
    def _dpr_counts_by_name(names: list[str]) -> dict[str, int]:
        rows = (
            DailyProgressReport.objects.filter(project_name__in=names)
            .values("project_name")
            .annotate(count=Count("id"))
        )
        return {row["project_name"]: row["count"] for row in rows}

    def _sort_cards(self, cards: list[dict[str, Any]], ordering: str) -> list[dict[str, Any]]:
        ordering = (ordering or self.DEFAULT_ORDERING).strip()
        if ordering not in self.ALLOWED_ORDERING:
            ordering = self.DEFAULT_ORDERING

        reverse = ordering.startswith("-")
        key = ordering.lstrip("-")
        key_map = {
            "name": "project_name",
            "project_name": "project_name",
            "client": "client",
            "client_name": "client",
            "status": "compare_enabled",  # active first when sorting by status proxy
            "updated_at": "last_updated",
            "health_score": "health_score",
        }
        field = key_map.get(key, "last_updated")

        if key == "status":
            # Prefer active projects first when ascending status sort is requested.
            return sorted(
                cards,
                key=lambda c: (0 if c.get("compare_enabled") else 1, c.get("project_name") or ""),
                reverse=reverse,
            )

        def sort_key(card: dict[str, Any]):
            value = card.get(field)
            if value is None:
                return ""
            return value

        return sorted(cards, key=sort_key, reverse=reverse)
