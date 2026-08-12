"""
Server-side MPR aggregation.

Reuses existing KPI / metrics helpers. Does not invent formulas or unavailable fields.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db.models import Count, Prefetch, Sum
from django.utils import timezone

from bottlenecks.metrics import compute_summary as bottleneck_summary
from bottlenecks.models import Bottleneck
from cashflow.models import CashFlow
from construction_progress.models.construction_progress import ConstructionProgress
from contract_values.controllers.contract_value_metrics import metrics_from_amounts
from contract_values.models import ContractValue
from correspondence.controllers.correspondence_metrics import (
    VIEW_MONTHLY,
    dashboard_response as correspondence_dashboard,
    filter_by_period as filter_correspondence_period,
    metrics_from_queryset as correspondence_metrics_from_qs,
)
from correspondence.models.correspondence import CorrespondenceDocument
from cost_performance.models import ProjectCostPerformance
from cost_performance.serializers import month_year_sort_key
from drawings.controllers.drawing_report import kpi_summary_for_period
from drawings.models.drawing_file import DrawingFile
from drawings.models.drawing_register import DrawingRegisterItem, DrawingWorkflowEvent
from health_safety.models import HealthSafetyRecord
from invoicing.controllers.invoicing_metrics import metrics_from_amounts as invoice_metrics
from invoicing.models import InvoicingInformation
from manpower.models import ProjectManpower
from meeting_documents.models import MeetingDocument
from monthly_scope.models import MonthlyScopeWork
from plant_machinery.models import MachineryMaster, PlantMachineryReport
from project_dates.bg_status import bg_status_payload
from project_dates.eot_models import ProjectEOT
from project_dates.models import ProjectDates
from project_equipment.models.project_equipment import ProjectEquipment
from project_quality_status.controllers.quality_metrics import metrics_from_counts as quality_metrics
from project_quality_status.models.project_quality_status import ProjectQualityStatus
from projects.models import Project
from projects.services.overview_kpis import (
    build_cost_kpi,
    build_progress_kpi,
    build_time_kpi,
    compute_project_status,
    extract_project_code,
    resolve_completion_date,
)
from projects.services.project_overview import ProjectOverviewService
from site_images.models import SiteProgressImage

from .period import MPRPeriod, parse_mpr_month
from .mpr_validation import validate_and_normalize_snapshot


def _next_month_start(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)

logger = logging.getLogger(__name__)

AVAIL_AVAILABLE = "available"
AVAIL_PARTIAL = "partial"
AVAIL_UNAVAILABLE = "unavailable"
AVAIL_MANUAL = "manual_input_required"


def _dec(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _user_label(user) -> str | None:
    if user is None:
        return None
    name = (getattr(user, "get_full_name", lambda: "")() or "").strip()
    if name:
        return name
    return getattr(user, "username", None) or getattr(user, "email", None)


def _assess_hse_data_quality(row) -> dict:
    """
    Diagnose HealthSafetyRecord quality for the reporting month.

    Does not mutate source data. Flags anomalous monthly counts and
    invalid rate denominators for admin/backend consumers.
    """
    warnings: list[str] = []
    fatalities = int(getattr(row, "fatalities", 0) or 0)
    significant = int(getattr(row, "significant", 0) or 0)
    major = int(getattr(row, "major", 0) or 0)
    minor = int(getattr(row, "minor", 0) or 0)
    near_miss = int(getattr(row, "near_miss", 0) or 0)
    total = fatalities + significant + major + minor + near_miss
    manhours = float(getattr(row, "total_manhours", 0) or 0)
    working_days = int(getattr(row, "working_days", 0) or 0)
    adm = float(getattr(row, "average_daily_manpower", 0) or 0)

    if fatalities > 5:
        warnings.append(
            f"Monthly fatalities={fatalities} is unusually high; verify source entry."
        )
    if total > 100:
        warnings.append(
            f"Monthly total incidents={total} is unusually high; verify source entry."
        )
    if fatalities > 0 and manhours > 0 and manhours < 1000:
        warnings.append(
            "Fatalities recorded against a very low manhours denominator."
        )
    if working_days <= 0 or adm <= 0:
        warnings.append(
            "Working days / average daily manpower incomplete; derived rates unsafe."
        )
    if manhours <= 0:
        warnings.append("Manhours missing or zero; derived rates unavailable.")

    status = "valid"
    if warnings:
        status = "invalid" if fatalities > 20 or total > 200 else "warning"
    return {
        "status": status,
        "warnings": warnings,
        "source": "HealthSafetyRecord",
        "period_kind": "monthly",
    }


class MPRService:
    """Build one structured MPR dataset for a project + YYYY-MM period."""

    def __init__(self, project: Project, period: MPRPeriod, *, photo_limit: int | None = None):
        self.project = project
        self.period = period
        self.photo_limit = photo_limit or int(
            getattr(settings, "MPR_PHOTO_LIMIT", 20)
        )
        self._ctx: dict[str, Any] = {}
        self._availability: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def build(self) -> dict[str, Any]:
        self._load_context()
        # Build once — key_indicators / executive_summary reuse these
        physical = self.build_progress_section()
        time_progress = self.build_time_section()
        financial = self.build_financial_section()
        eot = self.build_eot_section()
        bottlenecks = self.build_bottlenecks_section()
        quality = self.build_quality_section()
        hse = self.build_hse_section()
        key_indicators = self.build_key_indicators(
            time_progress=time_progress,
            financial=financial,
            eot=eot,
            bottlenecks=bottlenecks,
        )
        executive = self.build_executive_summary(
            time_progress=time_progress,
            key_indicators=key_indicators,
            physical=physical,
            financial=financial,
            eot=eot,
            bottlenecks=bottlenecks,
            quality=quality,
            hse=hse,
        )
        raw = {
            "project": self.build_project_section(),
            "reporting_period": self.period.reporting_period,
            "executive_summary": executive,
            "key_indicators": key_indicators,
            "physical_progress": physical,
            "time_progress": time_progress,
            "eot": eot,
            "financial_progress": financial,
            "bg": self.build_bg_section(),
            "correspondence": self.build_correspondence_section(),
            "drawings": self.build_drawings_section(),
            "bottlenecks": bottlenecks,
            "quality": quality,
            "hse": hse,
            "manpower": self.build_manpower_section(),
            "equipment": self.build_equipment_section(),
            "site_photos": self.build_photos_section(),
            "meetings": self.build_meetings_section(),
            "next_month_program": self.build_next_month_program_section(),
            "materials": {
                "available": False,
                "records": [],
                "note": "Material received register is not available in the backend.",
            },
            "laboratory_equipment": {
                "available": False,
                "records": [],
                "note": "Laboratory equipment register is not available in the backend.",
            },
            "achievements": {
                "manual_input_required": True,
                "major_achievements": None,
                "next_month_plan": None,
            },
            "client_decisions": self.build_client_decisions(),
            "data_availability": self.build_data_availability(),
        }
        return validate_and_normalize_snapshot(raw)

    # ------------------------------------------------------------------
    # Shared context (bulk loads — avoid N+1)
    # ------------------------------------------------------------------

    def _load_context(self) -> None:
        project = self.project
        period = self.period
        name = project.name

        # Prefetch team lead once
        if project.team_lead_id and not hasattr(project, "_state"):
            pass
        # Ensure team_lead is available
        if project.team_lead_id:
            # select_related may already have loaded it from the view
            _ = project.team_lead

        scl_dates = (
            ProjectDates.objects.filter(
                project_id=project.id,
                date_type=ProjectDates.DATE_TYPE_SCL,
            )
            .prefetch_related("bg_statuses")
            .first()
        )

        eots = list(
            ProjectEOT.objects.filter(project_id=project.id, is_active=True)
            .order_by("-eot_number", "-id")
            .only(
                "id",
                "eot_number",
                "extension_days",
                "reason",
                "approval_date",
                "original_completion_date",
                "revised_completion_date",
                "status",
                "remarks",
                "is_active",
            )
        )
        approved_eots = [
            e for e in eots if e.status == ProjectEOT.STATUS_APPROVED
        ]
        latest_approved = approved_eots[0] if approved_eots else None
        latest_approved_date = (
            latest_approved.revised_completion_date if latest_approved else None
        )

        scope_pct_map = ProjectOverviewService._scope_progress_by_project_id(
            [project.id]
        )
        scope_pct = scope_pct_map.get(project.id)

        scope_agg = MonthlyScopeWork.objects.filter(project_id=project.id).aggregate(
            planned=Sum("planned_quantity"),
            cumulative=Sum("cumulative_quantity"),
            row_count=Count("id"),
        )
        # Month-scoped scopes (plan rows for this calendar month)
        month_scope_agg = MonthlyScopeWork.objects.filter(
            project_id=project.id,
            month=period.start_date,
        ).aggregate(
            planned=Sum("planned_quantity"),
            cumulative=Sum("cumulative_quantity"),
            row_count=Count("id"),
        )

        construction = ConstructionProgress.objects.filter(
            projectName__iexact=name,
            progressMonth=period.month_key,
        ).first()
        construction_history = list(
            ConstructionProgress.objects.filter(projectName__iexact=name)
            .filter(progressMonth__lte=period.month_key)
            .order_by("progressMonth")
            .only(
                "progressMonth",
                "plannedProgress",
                "actualProgress",
                "variance",
                "performancePercentage",
            )[:36]
        )

        cost = ProjectCostPerformance.objects.filter(
            project_id=project.id,
            month_year=period.month_year_abbr,
        ).first()
        if cost is None:
            # Fallback: try project_name + month_year (legacy rows)
            cost = ProjectCostPerformance.objects.filter(
                project_name__iexact=name,
                month_year=period.month_year_abbr,
            ).first()
        cost_history = list(
            ProjectCostPerformance.objects.filter(project_id=project.id)
            .order_by("month_year")
            .only("month_year", "bcws", "bcwp", "acwp", "cpi", "eac", "bac")[:36]
        )
        if not cost_history:
            cost_history = list(
                ProjectCostPerformance.objects.filter(project_name__iexact=name)
                .order_by("month_year")
                .only("month_year", "bcws", "bcwp", "acwp", "cpi", "eac", "bac")[:36]
            )

        cashflow = CashFlow.objects.filter(
            project_name__iexact=name,
            month_year=period.month_year_abbr,
        ).first()
        cashflow_history = list(
            CashFlow.objects.filter(project_name__iexact=name)
            .order_by("month_year")[:36]
        )

        contract_scl = ContractValue.objects.filter(
            project_name__iexact=name,
            contract_type=ContractValue.ContractType.SCL,
        ).first()

        invoices = list(
            InvoicingInformation.objects.filter(project_name__iexact=name)
        )

        quality = ProjectQualityStatus.objects.filter(
            projectName__iexact=name,
            month=period.month,
            year=period.year,
        ).first()

        hse = HealthSafetyRecord.objects.filter(
            project_name__iexact=name,
            month=period.month,
            year=period.year,
        ).first()

        manpower = ProjectManpower.objects.filter(
            project_name__iexact=name,
            month_year=period.month_year_abbr,
        ).first()

        equipment = ProjectEquipment.objects.filter(
            projectName__iexact=name,
            equipmentMonth=period.month_key,
        ).first()

        plant_reports = list(
            PlantMachineryReport.objects.filter(
                project_name__iexact=name,
                report_date__gte=period.start_date,
                report_date__lte=period.end_date,
            )
            .prefetch_related("machinery_items", "machinery_items__machinery_master")
            .order_by("-report_date")[:5]
        )
        # If the reporting month has no report, use the latest report on/before month-end
        # so inventory still lists the full machinery catalogue with counts.
        if not plant_reports:
            latest_plant = (
                PlantMachineryReport.objects.filter(
                    project_name__iexact=name,
                    report_date__lte=period.end_date,
                )
                .prefetch_related("machinery_items", "machinery_items__machinery_master")
                .order_by("-report_date")
                .first()
            )
            if latest_plant is not None:
                plant_reports = [latest_plant]

        machinery_masters = list(
            MachineryMaster.objects.order_by("name").only(
                "id", "name", "unit", "category"
            )
        )

        bottlenecks = list(
            Bottleneck.objects.filter(project_id=project.id)
            .select_related("assigned_to")
            .order_by("-priority", "-created_at")
        )

        photos = list(
            SiteProgressImage.objects.filter(
                project_name__iexact=name,
                month=period.month,
                year=period.year,
            )
            .order_by("-created_at")[: self.photo_limit]
            .only("id", "title", "image_url", "created_at", "month", "year")
        )

        corr_qs = filter_correspondence_period(
            CorrespondenceDocument.objects.all(),
            project_name=name,
            month=period.month,
            year=period.year,
            view=VIEW_MONTHLY,
        )
        # Evaluate once for metrics + sample records
        corr_ids = list(corr_qs.values_list("id", flat=True))
        corr_docs = list(
            CorrespondenceDocument.objects.filter(id__in=corr_ids)
            .order_by("-received_date", "-id")[:40]
            .only(
                "id",
                "sr_no",
                "description",
                "flow_direction",
                "correspondence_type",
                "correspondence_category",
                "delivered_status",
                "received_date",
                "deadline_date",
                "delivered_date",
                "sender",
                "recipient_type",
                "month",
                "year",
            )
        )

        drawing_kpis = kpi_summary_for_period(
            name, period.month, period.year, VIEW_MONTHLY
        )
        pending_drawings = list(
            DrawingRegisterItem.objects.filter(project_id=project.id)
            .filter(submitted_date__isnull=False, approved_date__isnull=True)
            .order_by("submitted_date", "sr_no")[:10]
            .only(
                "id",
                "sr_no",
                "drawing_name",
                "revision",
                "submitted_date",
                "approved_date",
                "remarks",
                "contractor_name",
            )
        )
        drawing_register = list(
            DrawingRegisterItem.objects.filter(project_id=project.id)
            .prefetch_related(
                "workflow_events",
                Prefetch(
                    "files",
                    queryset=DrawingFile.objects.filter(is_active=True).order_by(
                        "created_at", "id"
                    ),
                ),
            )
            .order_by("sr_no", "revision")[:250]
        )
        month_scope_rows = list(
            MonthlyScopeWork.objects.filter(
                project_id=project.id,
                month=period.start_date,
            )
            .select_related("category", "subcategory")
            .order_by("category__display_order", "subcategory__display_order", "id")[:200]
        )
        # Full assigned-scope catalogue for cumulative detail (all months / null month)
        all_scope_rows = list(
            MonthlyScopeWork.objects.filter(project_id=project.id)
            .select_related("category", "subcategory")
            .order_by(
                "category__display_order",
                "subcategory__display_order",
                "month",
                "id",
            )[:500]
        )
        # Do not fall back to other months — wrong-period activities corrupt the MPR.
        next_start = _next_month_start(period.start_date)
        next_month_rows = list(
            MonthlyScopeWork.objects.filter(
                project_id=project.id,
                month=next_start,
            )
            .select_related("category", "subcategory")
            .order_by("category__display_order", "subcategory__display_order", "id")[:100]
        )
        meetings = list(
            MeetingDocument.objects.filter(
                project_id=project.id,
                is_active=True,
                meeting_date__gte=period.start_date,
                meeting_date__lte=period.end_date,
            )
            .order_by("meeting_date", "id")[:40]
            .only(
                "id",
                "meeting_type",
                "title",
                "description",
                "meeting_date",
                "meeting_number",
            )
        )

        self._ctx = {
            "scl_dates": scl_dates,
            "eots": eots,
            "approved_eots": approved_eots,
            "latest_approved_eot": latest_approved,
            "latest_approved_eot_date": latest_approved_date,
            "scope_pct": scope_pct,
            "scope_agg": scope_agg,
            "month_scope_agg": month_scope_agg,
            "month_scope_rows": month_scope_rows,
            "all_scope_rows": all_scope_rows,
            "next_month_rows": next_month_rows,
            "construction": construction,
            "construction_history": construction_history,
            "cost": cost,
            "cost_history": cost_history,
            "cashflow": cashflow,
            "cashflow_history": cashflow_history,
            "contract_scl": contract_scl,
            "invoices": invoices,
            "quality": quality,
            "hse": hse,
            "manpower": manpower,
            "equipment": equipment,
            "plant_reports": plant_reports,
            "machinery_masters": machinery_masters,
            "bottlenecks": bottlenecks,
            "photos": photos,
            "corr_qs": corr_qs,
            "corr_docs": corr_docs,
            "drawing_kpis": drawing_kpis,
            "pending_drawings": pending_drawings,
            "drawing_register": drawing_register,
            "meetings": meetings,
        }

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    def build_project_section(self) -> dict:
        p = self.project
        scl = self._ctx.get("scl_dates")
        latest_eot_date = self._ctx.get("latest_approved_eot_date")
        contract_finish = (
            getattr(scl, "contract_finish", None) if scl else None
        ) or p.contract_finish
        forecast_finish = (
            getattr(scl, "forecast_finish", None) if scl else None
        ) or getattr(p, "forecast_finish", None)
        project_start = (
            getattr(scl, "project_start", None) if scl else None
        ) or p.project_start or p.start_date or p.commencement_date
        current_completion = resolve_completion_date(
            p,
            latest_eot_date=latest_eot_date,
            contract_finish=contract_finish,
        )
        return {
            "project_id": p.id,
            "project_name": p.name,
            "project_code": extract_project_code(p.name) or None,
            "client": p.client_name or None,
            "location": p.location or None,
            "status": p.status,
            "description": (p.description or "").strip() or None,
            "project_start": _iso(project_start),
            "contract_finish": _iso(contract_finish),
            "forecast_finish": _iso(forecast_finish),
            "current_completion_date": _iso(current_completion),
            "team_leader": _user_label(getattr(p, "team_lead", None)),
            "team_leader_id": p.team_lead_id,
            "consultant": "Shrikhande Consultants Limited",
        }

    def build_progress_section(self) -> dict:
        """
        Physical progress splits two independent sources:

        - Monthly: ConstructionProgress for the reporting month only
        - Cumulative: Assigned Scope aggregation
          (ProjectOverviewService._scope_progress_by_project_id)

        Missing monthly data must not invalidate cumulative scope progress,
        and older ConstructionProgress months must not backfill the report month.
        """
        construction = self._ctx.get("construction")
        scope_agg = self._ctx.get("scope_agg") or {}
        month_scope = self._ctx.get("month_scope_agg") or {}
        scope_pct = self._ctx.get("scope_pct")
        month_label = (
            f"{calendar.month_name[self.period.month]} {self.period.year}"
        )

        if construction is not None:
            planned_m = _dec(construction.plannedProgress)
            actual_m = _dec(construction.actualProgress)
            variance_m = _dec(construction.variance)
            if variance_m is None and planned_m is not None and actual_m is not None:
                variance_m = round(actual_m - planned_m, 2)
            monthly = {
                "reporting_month": self.period.month_key,
                "planned_percentage": planned_m,
                "actual_percentage": actual_m,
                "variance_percentage": variance_m,
                "performance_percentage": _dec(construction.performancePercentage),
                "available": True,
                "message": None,
            }
            self._availability["construction_progress"] = {"status": AVAIL_AVAILABLE}
        else:
            monthly = {
                "reporting_month": self.period.month_key,
                "planned_percentage": None,
                "actual_percentage": None,
                "variance_percentage": None,
                "performance_percentage": None,
                "available": False,
                "message": (
                    f"Monthly progress data is not available for {month_label}."
                ),
            }
            self._availability["construction_progress"] = {
                "status": AVAIL_UNAVAILABLE,
                "note": monthly["message"],
            }

        scope_row_count = int(scope_agg.get("row_count") or 0)
        planned_qty = _dec(scope_agg.get("planned"))
        cumulative_qty = _dec(scope_agg.get("cumulative"))
        progress_pct = None
        if scope_row_count > 0:
            planned_for_pct = planned_qty if planned_qty is not None else 0.0
            cum_for_pct = cumulative_qty if cumulative_qty is not None else 0.0
            if scope_pct is not None:
                progress_pct = round(float(scope_pct), 2)
            elif planned_for_pct > 0:
                # Same rule as ProjectOverviewService._scope_progress_by_project_id
                progress_pct = round(
                    min(100.0, (cum_for_pct / planned_for_pct) * 100.0), 2
                )
            # planned_quantity == 0 → progress_pct stays null (no division by zero)

        month_planned = _dec(month_scope.get("planned"))
        month_cum = _dec(month_scope.get("cumulative"))

        def _serialize_scope_row(idx: int, row) -> dict:
            row_planned = _dec(row.planned_quantity)
            completed = _dec(row.cumulative_quantity)
            if row_planned is not None and row_planned > 0 and completed is not None:
                balance = round(max(row_planned - completed, 0.0), 2)
                pct = round(min(100.0, (completed / row_planned) * 100.0), 2)
            else:
                balance = _dec(row.remaining_quantity)
                if balance is None and row_planned is not None and completed is not None:
                    balance = max(row_planned - completed, 0.0)
                pct = _dec(row.progress_percentage)
                if pct is not None:
                    pct = round(min(100.0, max(0.0, pct)), 2)
            item_name = (
                row.get_subcategory_display_name()
                or row.get_category_display_name()
                or (row.description or "").strip()
                or "Scope item"
            )
            category = row.get_category_display_name() or None
            return {
                "sr_no": idx,
                "item": item_name,
                "category": category,
                "description": (row.description or "").strip() or None,
                "unit": row.unit or None,
                "total": row_planned,
                "completed": completed if completed is not None else 0.0,
                "balance": balance,
                "percent_achieved": pct,
                "status": row.status,
                "remarks": None,
                "section": row.section or None,
                "location": row.location or None,
                "scope_id": row.id,
                "scope_month": _iso(row.month),
            }

        activities = [
            _serialize_scope_row(idx, row)
            for idx, row in enumerate(self._ctx.get("month_scope_rows") or [], start=1)
        ]
        scope_items = [
            _serialize_scope_row(idx, row)
            for idx, row in enumerate(self._ctx.get("all_scope_rows") or [], start=1)
        ]

        # Category-wise rollup for charts / detail
        cat_totals: dict[str, dict[str, float]] = {}
        for item in scope_items:
            cat = item.get("category") or "Uncategorized"
            bucket = cat_totals.setdefault(
                cat, {"planned": 0.0, "completed": 0.0, "items": 0}
            )
            bucket["planned"] += float(item.get("total") or 0)
            bucket["completed"] += float(item.get("completed") or 0)
            bucket["items"] += 1
        category_summary = []
        for cat, vals in sorted(cat_totals.items(), key=lambda x: x[0]):
            planned_c = vals["planned"]
            completed_c = vals["completed"]
            pct_c = (
                round(min(100.0, (completed_c / planned_c) * 100.0), 2)
                if planned_c > 0
                else None
            )
            category_summary.append(
                {
                    "category": cat,
                    "item_count": int(vals["items"]),
                    "planned_quantity": round(planned_c, 2),
                    "completed_quantity": round(completed_c, 2),
                    "progress_percentage": pct_c,
                }
            )

        history = []
        for row in self._ctx.get("construction_history") or []:
            history.append(
                {
                    "month": row.progressMonth,
                    "planned_percentage": _dec(row.plannedProgress),
                    "actual_percentage": _dec(row.actualProgress),
                    "variance_percentage": _dec(row.variance),
                    "performance_percentage": _dec(row.performancePercentage),
                }
            )

        scope_available = scope_row_count > 0
        cumulative = {
            "actual_percentage": progress_pct,
            "scope_planned_quantity": planned_qty if scope_available else None,
            "scope_completed_quantity": (
                cumulative_qty if scope_available else None
            ),
            "scope_progress_percentage": progress_pct,
            "available": scope_available,
            "data_source": "scope" if scope_available else None,
            "message": (
                None
                if scope_available
                else "Scope progress data is not available."
            ),
            # Legacy mirrors (kept for existing consumers)
            "planned_percentage": None,
            "variance_percentage": None,
            "item_count": len(scope_items),
            "category_count": len(category_summary),
        }

        # Do not claim "scope activity unavailable" when cumulative scope exists.
        if activities:
            activities_note = None
        elif scope_available:
            activities_note = None
        else:
            activities_note = "Scope progress data is not available."

        return {
            "monthly": monthly,
            "monthly_available": bool(monthly.get("available")),
            "reporting_month": self.period.month_key,
            "reporting_month_label": month_label,
            "activities_available": bool(activities),
            "period_note": monthly.get("message"),
            "activities_note": activities_note,
            "cumulative": cumulative,
            "scope_progress": {
                "planned_quantity": cumulative.get("scope_planned_quantity"),
                "cumulative_quantity": cumulative.get("scope_completed_quantity"),
                "progress_percentage": progress_pct,
                "month_planned_quantity": month_planned,
                "month_cumulative_quantity": month_cum,
                "available": scope_available,
            },
            "scope_items": scope_items,
            "scope_category_summary": category_summary,
            "activities": activities,
            "history": history,
        }

    def build_physical_billed_till_date(self, physical: dict | None = None) -> dict:
        """
        PHYSICAL PROGRESS BILLED TILL DATE.

        Actual = Assigned Scope cumulative execution %
          (same rule as ProjectOverviewService._scope_progress_by_project_id).
        Target = reporting-month ConstructionProgress.plannedProgress only
          (do not backfill from other months).
        """
        physical = physical or {}
        construction = self._ctx.get("construction")
        scope_agg = self._ctx.get("scope_agg") or {}
        planned_qty = _dec(scope_agg.get("planned"))
        cum_qty = _dec(scope_agg.get("cumulative"))
        actual = (physical.get("cumulative") or {}).get("actual_percentage")
        if actual is None:
            actual = self._ctx.get("scope_pct")
            if actual is not None:
                actual = round(float(actual), 2)
            elif planned_qty and planned_qty > 0 and cum_qty is not None:
                actual = round(min(100.0, (cum_qty / planned_qty) * 100.0), 2)

        target = None
        if construction is not None:
            target = _dec(construction.plannedProgress)

        notes = []
        if target is None:
            notes.append(
                f"Reporting-month planned physical progress is not available "
                f"for {self.period.month_key}."
            )
        if actual is None:
            notes.append("Assigned scope cumulative progress is not available.")

        return {
            "target_percentage": target,
            "actual_percentage": actual,
            "planned_quantity": planned_qty,
            "cumulative_quantity": cum_qty,
            "target_available": target is not None,
            "actual_available": actual is not None,
            "available": actual is not None or target is not None,
            "data_source": (
                "assigned_scope_cumulative"
                if actual is not None
                else (
                    "construction_progress_reporting_month"
                    if target is not None
                    else None
                )
            ),
            "notes": notes,
        }

    def build_financial_billed_till_date(self, financial: dict | None = None) -> dict:
        """
        FINANCIAL PROGRESS BILLED TILL DATE.

        Target = SCL revised (else original) contract value.
        Actual = SCL InvoicingInformation.gross_billed (current-state billed KPI).

        InvoicingInformation has no invoice/bill date or status; there is no
        per-invoice history to filter by reporting-month end. CashFlow and
        ProjectCostPerformance ACWP are not used as billed amount.
        """
        financial = financial or {}
        contract = financial.get("contract") or {}
        target = contract.get("revised_contract_value")
        if target is None:
            target = contract.get("original_contract_value")

        invoices = self._ctx.get("invoices") or []
        scl = next(
            (
                inv
                for inv in invoices
                if inv.invoice_type == InvoicingInformation.InvoiceType.SCL
            ),
            None,
        )
        actual = _dec(scl.gross_billed) if scl is not None else None
        certified = (
            _dec(scl.gross_certified_billed) if scl is not None else None
        )

        notes = []
        if target is None:
            notes.append("SCL contract value is not available.")
        if actual is None:
            notes.append(
                "Billing data is not available for the reporting period."
            )
        else:
            notes.append(
                "Billed amount is current-state SCL gross billed "
                "(no invoice date field to filter by month end)."
            )

        return {
            "target_amount": target,
            "actual_amount": actual,
            "certified_amount": certified,
            "target_available": target is not None,
            "actual_available": actual is not None,
            "available": target is not None or actual is not None,
            "data_source": (
                "invoicing_scl_gross_billed"
                if actual is not None
                else (
                    "revised_contract_value"
                    if target is not None
                    else None
                )
            ),
            "notes": notes,
        }

    def build_eot_section(self) -> dict:
        eots = self._ctx.get("eots") or []
        approved = self._ctx.get("approved_eots") or []
        latest = self._ctx.get("latest_approved_eot")

        def serialize(e: ProjectEOT) -> dict:
            return {
                "id": e.id,
                "eot_number": e.eot_number,
                "extension_days": e.extension_days,
                "reason": e.reason or "",
                "approval_date": _iso(e.approval_date),
                "original_completion_date": _iso(e.original_completion_date),
                "revised_completion_date": _iso(e.revised_completion_date),
                "status": e.status,
                "remarks": e.remarks or "",
            }

        history = [serialize(e) for e in eots]
        approved_rows = [serialize(e) for e in approved]
        pending_rows = [
            serialize(e)
            for e in eots
            if e.status
            in (
                getattr(ProjectEOT, "STATUS_PENDING", "pending"),
                getattr(ProjectEOT, "STATUS_SUBMITTED", "submitted"),
                "pending",
                "submitted",
            )
        ]
        rejected_rows = [
            serialize(e)
            for e in eots
            if e.status
            in (getattr(ProjectEOT, "STATUS_REJECTED", "rejected"), "rejected")
        ]
        self._availability["eot"] = {"status": AVAIL_AVAILABLE}
        return {
            "eot_count": len(eots),
            "approved_count": len(approved),
            "pending_count": len(pending_rows),
            "rejected_count": len(rejected_rows),
            "current_eot": serialize(latest) if latest else None,
            "latest_approved_eot": serialize(latest) if latest else None,
            "history": history,
            "approved": approved_rows,
            "pending": pending_rows,
            "rejected": rejected_rows,
        }

    def build_time_section(self) -> dict:
        p = self.project
        scl = self._ctx.get("scl_dates")
        latest_eot_date = self._ctx.get("latest_approved_eot_date")
        contract_finish = (
            getattr(scl, "contract_finish", None) if scl else None
        ) or p.contract_finish
        forecast_finish = (
            getattr(scl, "forecast_finish", None) if scl else None
        ) or getattr(p, "forecast_finish", None)
        project_start = (
            getattr(scl, "project_start", None) if scl else None
        ) or p.project_start or p.start_date or p.commencement_date
        current_completion = resolve_completion_date(
            p,
            latest_eot_date=latest_eot_date,
            contract_finish=contract_finish,
        )

        progress_kpi = build_progress_kpi(
            scope_pct=self._ctx.get("scope_pct"),
            progress_row=self._ctx.get("construction"),
        )
        time_kpi = build_time_kpi(
            p,
            progress_kpi["percentage"],
            latest_eot_date=latest_eot_date,
            contract_finish=contract_finish,
            project_start=project_start,
        )
        project_status = compute_project_status(
            p,
            latest_eot_date=latest_eot_date,
            contract_finish=contract_finish,
        )

        today = date.today()
        elapsed_days = None
        remaining_days = None
        delay_days = None
        if project_start and current_completion:
            elapsed_days = max(0, (min(today, current_completion) - project_start).days)
            remaining_days = (current_completion - today).days
            delay_days = (today - current_completion).days

        self._availability["time_progress"] = {"status": AVAIL_AVAILABLE}
        return {
            "original_contract_finish": _iso(contract_finish),
            "forecast_finish": _iso(forecast_finish),
            "current_completion_date": _iso(current_completion),
            "project_start": _iso(project_start),
            "elapsed_days": elapsed_days,
            "remaining_days": remaining_days,
            "delay_days": delay_days,
            "time_percentage": time_kpi.get("percentage"),
            "status": time_kpi.get("status"),
            "project_status": project_status,
        }

    def build_financial_section(self) -> dict:
        contract_scl = self._ctx.get("contract_scl")
        cost = self._ctx.get("cost")
        cashflow = self._ctx.get("cashflow")
        invoices = self._ctx.get("invoices") or []

        contract = None
        if contract_scl is not None:
            m = metrics_from_amounts(
                contract_scl.original_contract_value,
                contract_scl.excess_value,
                contract_scl.saving,
                getattr(contract_scl, "cos", 0),
            )
            contract = {
                "contract_type": contract_scl.contract_type,
                "original_contract_value": _dec(contract_scl.original_contract_value),
                "excess_value": _dec(contract_scl.excess_value),
                "saving": _dec(contract_scl.saving),
                "cos": _dec(getattr(contract_scl, "cos", 0)),
                "revised_contract_value": _dec(m.get("revised_value")),
                "increase_percentage": _dec(m.get("increase_percentage")),
                "snapshot_note": (
                    "ContractValue is current-state (no month key)."
                ),
            }
            self._availability["contract_value"] = {
                "status": AVAIL_PARTIAL,
                "missing": ["monthly_snapshot"],
                "note": "ContractValue has no historical month key.",
            }
        else:
            self._availability["contract_value"] = {"status": AVAIL_UNAVAILABLE}

        evm = None
        if cost is not None:
            evm = {
                "month_year": cost.month_year,
                "BCWS": _dec(cost.bcws),
                "BCWP": _dec(cost.bcwp),
                "ACWP": _dec(cost.acwp),
                "FCST": _dec(cost.fcst),
                "BAC": _dec(cost.bac),
                "EAC": _dec(cost.eac),
                "CV": _dec(cost.cv),
                "SV": _dec(cost.sv),
                "CPI": _dec(cost.cpi),
                "VAC": _dec(cost.vac),
                "SPI": None,
            }
            self._availability["evm"] = {
                "status": AVAIL_PARTIAL,
                "missing": ["SPI"],
                "note": "SPI is not stored or computed in ProjectCostPerformance.",
            }
        else:
            self._availability["evm"] = {
                "status": AVAIL_UNAVAILABLE,
                "note": f"No ProjectCostPerformance for {self.period.month_year_abbr}.",
            }

        cf = None
        if cashflow is not None:
            cf = {
                "month_year": cashflow.month_year,
                "cash_in_monthly_plan": _dec(cashflow.cash_in_monthly_plan),
                "cash_in_monthly_actual": _dec(cashflow.cash_in_monthly_actual),
                "cash_out_monthly_plan": _dec(cashflow.cash_out_monthly_plan),
                "cash_out_monthly_actual": _dec(cashflow.cash_out_monthly_actual),
                "actual_cost_monthly": _dec(cashflow.actual_cost_monthly),
                "cash_in_cumulative_plan": _dec(cashflow.cash_in_cumulative_plan),
                "cash_in_cumulative_actual": _dec(cashflow.cash_in_cumulative_actual),
                "cash_out_cumulative_plan": _dec(cashflow.cash_out_cumulative_plan),
                "cash_out_cumulative_actual": _dec(cashflow.cash_out_cumulative_actual),
            }
            self._availability["cashflow"] = {"status": AVAIL_AVAILABLE}
        else:
            self._availability["cashflow"] = {"status": AVAIL_UNAVAILABLE}

        inv_rows = []
        for inv in invoices:
            m = invoice_metrics(
                inv.gross_billed,
                inv.gross_certified_billed,
            )
            inv_rows.append(
                {
                    "invoice_type": inv.invoice_type,
                    "contractor_name": inv.contractor_name or None,
                    "gross_billed": _dec(inv.gross_billed),
                    "gross_certified_billed": _dec(inv.gross_certified_billed),
                    "difference": _dec(m.get("difference")),
                    "certification_efficiency": _dec(m.get("certification_efficiency")),
                }
            )
        if inv_rows:
            self._availability["invoicing"] = {
                "status": AVAIL_PARTIAL,
                "missing": ["monthly_snapshot"],
                "note": "InvoicingInformation is current-state (no month key).",
            }
        else:
            self._availability["invoicing"] = {"status": AVAIL_UNAVAILABLE}

        self._availability["formal_vo"] = {
            "status": AVAIL_UNAVAILABLE,
            "note": "No formal VO register; COS/excess/saving are on ContractValue only.",
        }

        history = []
        for row in self._ctx.get("cost_history") or []:
            history.append(
                {
                    "month_year": row.month_year,
                    "BCWS": _dec(row.bcws),
                    "BCWP": _dec(row.bcwp),
                    "ACWP": _dec(row.acwp),
                    "CPI": _dec(row.cpi),
                    "EAC": _dec(row.eac),
                    "BAC": _dec(row.bac),
                }
            )
        report_key = month_year_sort_key(self.period.month_year_abbr)
        history = [
            h
            for h in history
            if month_year_sort_key(str(h.get("month_year") or "")) <= report_key
        ]
        history.sort(key=lambda h: month_year_sort_key(str(h.get("month_year") or "")))

        cashflow_history = []
        for row in self._ctx.get("cashflow_history") or []:
            cashflow_history.append(
                {
                    "month_year": row.month_year,
                    "cash_in_monthly_actual": _dec(row.cash_in_monthly_actual),
                    "cash_out_monthly_actual": _dec(row.cash_out_monthly_actual),
                    "actual_cost_monthly": _dec(row.actual_cost_monthly),
                    "cash_in_cumulative_actual": _dec(row.cash_in_cumulative_actual),
                    "cash_out_cumulative_actual": _dec(row.cash_out_cumulative_actual),
                }
            )
        cashflow_history = [
            h
            for h in cashflow_history
            if month_year_sort_key(str(h.get("month_year") or "")) <= report_key
        ]
        cashflow_history.sort(
            key=lambda h: month_year_sort_key(str(h.get("month_year") or ""))
        )

        return {
            "contract": contract,
            "evm": evm,
            "cashflow": cf,
            "invoicing": {"records": inv_rows} if inv_rows else {"records": []},
            "history": history,
            "cashflow_history": cashflow_history,
        }

    def build_bg_section(self) -> dict:
        payload = bg_status_payload(self.project)
        records = []
        for entry in payload.get("contractor_bg") or []:
            records.append({**entry, "limitations_note": None})
        for entry in payload.get("scl_bg") or []:
            records.append({**entry, "limitations_note": None})

        limitations = [
            "BG amount, bank, BG number, issue date, and claim period are not currently available.",
        ]
        self._availability["bg"] = {
            "status": AVAIL_PARTIAL,
            "missing": ["bg_number", "amount", "issuing_bank", "issue_date", "claim_period"],
        }
        return {
            "available": True,
            "summary": payload.get("bg_summary"),
            "records": records,
            "limitations": limitations,
        }

    def build_correspondence_section(self) -> dict:
        period = self.period
        name = self.project.name
        corr_qs = self._ctx.get("corr_qs")
        docs = self._ctx.get("corr_docs") or []

        overall = correspondence_metrics_from_qs(corr_qs)
        inbound = corr_qs.filter(
            flow_direction=CorrespondenceDocument.FLOW_INBOUND
        ) if hasattr(CorrespondenceDocument, "FLOW_INBOUND") else corr_qs.none()
        outbound = corr_qs.filter(
            flow_direction=getattr(
                CorrespondenceDocument,
                "FLOW_OUTBOUND_SCL",
                "OUTBOUND_SCL",
            )
        ) if corr_qs is not None else CorrespondenceDocument.objects.none()

        try:
            inbound_metrics = correspondence_metrics_from_qs(inbound)
            outbound_metrics = correspondence_metrics_from_qs(outbound)
        except Exception:
            inbound_metrics = overall
            outbound_metrics = correspondence_metrics_from_qs(
                CorrespondenceDocument.objects.none()
            )

        dashboard = None
        try:
            dashboard = correspondence_dashboard(
                name,
                period.month,
                period.year,
                corr_qs,
                view=VIEW_MONTHLY,
            )
        except Exception as exc:
            logger.debug("correspondence dashboard skipped: %s", exc)

        important = []
        for d in docs:
            important.append(
                {
                    "reference_no": d.sr_no,
                    "sr_no": d.sr_no,
                    "description": (d.description or "")[:240],
                    "subject": (d.description or "")[:240],
                    "flow_direction": d.flow_direction,
                    "correspondence_type": d.correspondence_type,
                    "category": getattr(d, "correspondence_category", None) or None,
                    "delivered_status": d.delivered_status,
                    "received_date": _iso(d.received_date),
                    "deadline_date": _iso(d.deadline_date),
                    "delivered_date": _iso(d.delivered_date),
                    "sender": d.sender or None,
                    "recipient": getattr(d, "recipient_type", None) or None,
                }
            )

        self._availability["correspondence"] = {
            "status": AVAIL_AVAILABLE if important or overall.get("received") else AVAIL_UNAVAILABLE
        }
        return {
            "summary": {
                "total_received": overall.get("received", 0),
                "total_delivered": overall.get("delivered", 0),
                "pending": overall.get("pending", 0),
                "late": overall.get("late_deliveries", 0),
                "on_time": overall.get("on_time", 0),
                "record": overall.get("record", 0),
                "delivery_efficiency": overall.get("delivery_efficiency"),
                "inbound_received": inbound_metrics.get("received", 0),
                "outbound_received": outbound_metrics.get("received", 0),
            },
            "dashboard": dashboard,
            "important_records": important,
        }

    def build_drawings_section(self) -> dict:
        kpis = self._ctx.get("drawing_kpis") or {}
        pending = self._ctx.get("pending_drawings") or []
        submitted = kpis.get("submitted_drawings", 0)
        approved = kpis.get("approved_drawings", 0)
        total_register = DrawingRegisterItem.objects.filter(
            project_id=self.project.id
        ).count()

        pending_rows = [
            {
                "id": d.id,
                "sr_no": d.sr_no,
                "drawing_name": d.drawing_name,
                "revision": d.revision,
                "submitted_date": _iso(d.submitted_date),
                "remarks": d.remarks or "",
                "contractor_name": d.contractor_name or None,
            }
            for d in pending
        ]

        register_items = []
        for d in self._ctx.get("drawing_register") or []:
            events = []
            for ev in d.workflow_events.all():
                events.append(
                    {
                        "action": ev.action,
                        "action_label": dict(DrawingWorkflowEvent.ACTION_CHOICES).get(
                            ev.action, ev.action
                        ),
                        "event_date": _iso(ev.event_date),
                        "notes": (ev.notes or "").strip() or None,
                    }
                )
            # Fallback chronology from direct date fields when no workflow events
            if not events:
                if d.submitted_date:
                    events.append(
                        {
                            "action": DrawingWorkflowEvent.ACTION_SUBMITTED,
                            "action_label": "Submission by Contractor",
                            "event_date": _iso(d.submitted_date),
                            "notes": None,
                        }
                    )
                if d.consultant_comments_date:
                    events.append(
                        {
                            "action": DrawingWorkflowEvent.ACTION_CONSULTANT_COMMENTED,
                            "action_label": "Comments/Approval by Consultant",
                            "event_date": _iso(d.consultant_comments_date),
                            "notes": None,
                        }
                    )
                if d.resubmitted_date:
                    events.append(
                        {
                            "action": DrawingWorkflowEvent.ACTION_RESUBMITTED,
                            "action_label": "Re-submission by Contractor",
                            "event_date": _iso(d.resubmitted_date),
                            "notes": None,
                        }
                    )
                if d.approved_date:
                    events.append(
                        {
                            "action": DrawingWorkflowEvent.ACTION_APPROVED,
                            "action_label": "Approved by Consultant",
                            "event_date": _iso(d.approved_date),
                            "notes": None,
                        }
                    )

            contractor_dates = [
                e["event_date"]
                for e in events
                if e["action"]
                in (
                    DrawingWorkflowEvent.ACTION_SUBMITTED,
                    DrawingWorkflowEvent.ACTION_RESUBMITTED,
                )
                and e.get("event_date")
            ]
            scl_dates = [
                e["event_date"]
                for e in events
                if e["action"]
                in (
                    DrawingWorkflowEvent.ACTION_CONSULTANT_COMMENTED,
                    DrawingWorkflowEvent.ACTION_APPROVED,
                )
                and e.get("event_date")
            ]
            register_items.append(
                {
                    "id": d.id,
                    "sr_no": d.sr_no,
                    "drawing_name": d.drawing_name,
                    "revision": d.revision,
                    "contractor_name": d.contractor_name or None,
                    "remarks": d.remarks or "",
                    "submitted_date": _iso(d.submitted_date),
                    "consultant_comments_date": _iso(d.consultant_comments_date),
                    "resubmitted_date": _iso(d.resubmitted_date),
                    "approved_date": _iso(d.approved_date),
                    "submission_by_contractor": contractor_dates,
                    "reply_by_scl": scl_dates,
                    "events": events,
                    "drawing_file_count": sum(
                        1 for f in d.files.all() if getattr(f, "is_active", True)
                    ),
                    "files": [
                        {
                            "id": f.id,
                            "original_filename": f.original_filename,
                            "revision": f.revision,
                            "file_url": f.file_url,
                            "content_type": f.content_type,
                        }
                        for f in d.files.all()
                        if f.is_active
                    ],
                }
            )

        approved_total = DrawingRegisterItem.objects.filter(
            project_id=self.project.id, approved_date__isnull=False
        ).count()
        submitted_total = DrawingRegisterItem.objects.filter(
            project_id=self.project.id, submitted_date__isnull=False
        ).count()
        pending_with_pmc = DrawingRegisterItem.objects.filter(
            project_id=self.project.id,
            submitted_date__isnull=False,
            approved_date__isnull=True,
        ).count()

        self._availability["drawings"] = {
            "status": AVAIL_PARTIAL,
            "missing": ["rejected", "under_review_as_status_enum"],
            "note": (
                "Drawing KPIs use DrawingRegisterItem period counts "
                "(submitted/approved). No formal rejected status enum."
            ),
        }
        return {
            "total_register": total_register,
            "submitted": submitted,
            "approved": approved,
            "variance": kpis.get("variance"),
            "approval_rate": kpis.get("approval_rate"),
            "under_review": None,
            "rejected": None,
            "pending": max(submitted - approved, 0),
            "pending_items": pending_rows,
            "register_items": register_items,
            "received_summary": {
                "total_drawings": total_register,
                "received": submitted_total,
                "reviewed": submitted_total,
                "approved": approved_total,
                "pending": max(total_register - approved_total, 0),
            },
            "balance_summary": {
                "pending_drawings": max(total_register - approved_total, 0),
                "pending_with_contractor": max(total_register - submitted_total, 0),
                "pending_with_pmc": pending_with_pmc,
                "pending_with_client": None,
            },
        }

    def build_bottlenecks_section(self) -> dict:
        items = self._ctx.get("bottlenecks") or []
        qs = Bottleneck.objects.filter(project_id=self.project.id)
        summary = bottleneck_summary(qs)
        period = self.period

        new_count = sum(
            1
            for b in items
            if b.created_at
            and period.start_date
            <= timezone.localdate(b.created_at)
            <= period.end_date
        )
        # Cannot accurately determine monthly resolved without closed_at
        resolved_count = None

        open_items = [
            b
            for b in items
            if b.status in (Bottleneck.STATUS_OPEN, Bottleneck.STATUS_IN_PROGRESS)
        ]
        critical = [
            b for b in open_items if b.priority == Bottleneck.PRIORITY_CRITICAL
        ]
        overdue = [b for b in open_items if b.is_overdue]

        today = timezone.localdate()

        def serialize(b: Bottleneck) -> dict:
            created = timezone.localdate(b.created_at) if b.created_at else None
            ageing = (today - created).days if created else None
            action = None
            if b.is_overdue:
                action = "Overdue — action required"
            elif b.priority == Bottleneck.PRIORITY_CRITICAL:
                action = "Critical — priority attention"
            elif b.status != Bottleneck.STATUS_CLOSED:
                action = "Monitor / resolve"
            return {
                "description": b.description,
                "type": b.type,
                "category": b.type,
                "priority": b.priority,
                "status": b.status,
                "target_date": _iso(b.target_date),
                "date_raised": _iso(created) if created else _iso(b.created_at),
                "created_at": _iso(b.created_at),
                "updated_at": _iso(b.updated_at),
                "ageing_days": ageing,
                "days_open": ageing,
                "assigned_to": _user_label(b.assigned_to),
                "is_overdue": b.is_overdue,
                "action_required": action,
            }

        # Cap records for response size
        records = [serialize(b) for b in open_items[:25]]

        self._availability["bottlenecks"] = {
            "status": AVAIL_PARTIAL if open_items else AVAIL_AVAILABLE,
            "missing": ["closed_at", "monthly_resolved_count"],
            "note": "Resolution duration is not calculated because closed date is not stored.",
        }
        return {
            "summary": summary,
            "opening_count": None,
            "new_count": new_count,
            "resolved_count": resolved_count,
            "closing_count": summary.get("closed_items"),
            "critical_count": len(critical),
            "overdue_count": summary.get("overdue_items", len(overdue)),
            "open_count": summary.get("open_items", 0)
            + summary.get("in_progress_items", 0),
            "records": records,
        }

    def build_quality_section(self) -> dict:
        row = self._ctx.get("quality")
        self._availability["ncr"] = {
            "status": AVAIL_UNAVAILABLE,
            "note": "NCR register is not currently available.",
        }
        if row is None:
            self._availability["quality"] = {
                "status": AVAIL_UNAVAILABLE,
                "note": "No ProjectQualityStatus for this month.",
            }
            return {
                "available": False,
                "tests_required": None,
                "tests_conducted": None,
                "tests_passed": None,
                "tests_failed": None,
                "pass_percentage": None,
            }

        metrics = quality_metrics(
            row.tests_required,
            row.tests_conducted,
            row.tests_passed,
            row.tests_failed,
        )
        self._availability["quality"] = {"status": AVAIL_AVAILABLE}
        # MPR client pass/fail % use conducted denominator (not tests_required).
        conducted = row.tests_conducted or 0
        passed = row.tests_passed or 0
        failed = row.tests_failed or 0
        pass_pct = (
            round((passed / conducted) * 100.0, 2) if conducted > 0 else None
        )
        fail_pct = (
            round((failed / conducted) * 100.0, 2) if conducted > 0 else None
        )
        return {
            "available": True,
            "tests_required": row.tests_required,
            "tests_conducted": row.tests_conducted,
            "tests_passed": row.tests_passed,
            "tests_failed": row.tests_failed,
            "pass_percentage": pass_pct,
            "fail_percentage": fail_pct,
            "quality_performance": metrics.get("quality_performance"),
            "shortfall": metrics.get("shortfall"),
        }

    def build_hse_section(self) -> dict:
        row = self._ctx.get("hse")
        if row is None:
            self._availability["hse"] = {
                "status": AVAIL_UNAVAILABLE,
                "note": "No HealthSafetyRecord for this month.",
            }
            return {"available": False, "record": None}

        quality = _assess_hse_data_quality(row)
        manhours = _dec(row.total_manhours)
        man_hours_worked = _dec(row.man_hours_worked)
        denom = man_hours_worked if man_hours_worked and man_hours_worked > 0 else manhours
        ltifr = None
        incident_rate = None
        rates_available = False
        if (
            quality["status"] != "invalid"
            and denom
            and denom > 0
            and (row.working_days or 0) > 0
            and (row.average_daily_manpower or 0) > 0
        ):
            loss = float(row.loss_of_manhours or 0)
            ltifr = round((loss / float(denom)) * 1_000_000, 2)
            incident_rate = round((row.total_incidents / float(denom)) * 1_000_000, 2)
            rates_available = True
            if ltifr > 50_000 or incident_rate > 50_000:
                ltifr = None
                incident_rate = None
                rates_available = False
                quality["warnings"].append(
                    "Derived safety rates suppressed due to absurd frequency values."
                )
                quality["status"] = "warning"

        if not rates_available:
            self._availability["hse"] = {
                "status": AVAIL_PARTIAL if quality["status"] != "invalid" else AVAIL_PARTIAL,
                "note": "HSE counts preserved; derived rates unavailable or unsafe.",
            }
            if quality["status"] == "valid":
                quality["status"] = "warning"
        else:
            self._availability["hse"] = {"status": AVAIL_AVAILABLE}

        return {
            "available": True,
            "rates_available": rates_available,
            "data_quality": quality,
            "record": {
                "month": row.month,
                "year": row.year,
                "fatalities": row.fatalities,
                "significant": row.significant,
                "major": row.major,
                "minor": row.minor,
                "near_miss": row.near_miss,
                "total_incidents": row.total_incidents,
                "total_manhours": manhours,
                "loss_of_manhours": _dec(row.loss_of_manhours),
                "man_hours_worked": man_hours_worked,
                "reportable_accident_lti": row.reportable_accident_lti,
                "ltifr": ltifr,
                "incident_rate": incident_rate,
                "average_daily_manpower": _dec(row.average_daily_manpower),
                "working_days": row.working_days,
                "man_days_worked": _dec(getattr(row, "man_days_worked", None)),
            },
        }

    def build_manpower_section(self) -> dict:
        row = self._ctx.get("manpower")
        if row is None:
            self._availability["manpower"] = {
                "status": AVAIL_UNAVAILABLE,
                "note": f"No ProjectManpower for {self.period.month_year_abbr}.",
            }
            return {
                "available": False,
                "limitations": [
                    "Skill breakdown (engineers/skilled/unskilled) is not available.",
                ],
            }

        self._availability["manpower"] = {
            "status": AVAIL_PARTIAL,
            "missing": ["skill_breakdown"],
            "note": "No engineers/skilled/unskilled split on ProjectManpower.",
        }
        return {
            "available": True,
            "month_year": row.month_year,
            "planned_headcount": row.planned_manpower,
            "actual_headcount": row.actual_manpower,
            "planned_manhours": _dec(row.planned_mh),
            "actual_manhours": _dec(row.actual_mh),
            "planned_manhours_cumulative": _dec(row.planned_mh_cumulative),
            "actual_manhours_cumulative": _dec(row.actual_mh_cumulative),
            "working_hours_per_day": row.working_hours_per_day,
            "working_days_per_month": row.working_days_per_month,
            "limitations": [
                "Skill breakdown (engineers/skilled/unskilled) is not available.",
            ],
        }

    def build_equipment_section(self) -> dict:
        eq = self._ctx.get("equipment")
        plant_reports = self._ctx.get("plant_reports") or []
        masters = self._ctx.get("machinery_masters") or []

        equipment_kpi = None
        if eq is not None:
            equipment_kpi = {
                "equipment_month": eq.equipmentMonth,
                "planned_equipment": eq.plannedEquipment,
                "actual_equipment": eq.actualEquipment,
                "variance": _dec(eq.variance),
                "performance_percentage": _dec(eq.performancePercentage),
                "remarks": eq.remarks or "",
            }

        # Prefer the most recent report for inventory counts.
        primary_report = plant_reports[0] if plant_reports else None
        qty_by_master: dict[int, Any] = {}
        if primary_report is not None:
            for item in primary_report.machinery_items.all():
                mid = item.machinery_master_id
                if mid is None:
                    continue
                # Keep first (prefetch order); reports are unique per master
                if mid not in qty_by_master:
                    qty_by_master[mid] = item

        inventory = []
        for idx, master in enumerate(masters, start=1):
            item = qty_by_master.get(master.id)
            qty = int(item.qty) if item is not None else 0
            inventory.append(
                {
                    "sr_no": idx,
                    "name": master.name,
                    "unit": master.unit or "Nos",
                    "category": (master.category or "").strip() or None,
                    "qty": qty,
                    "status": (
                        item.status
                        if item is not None
                        else "Not Available"
                    ),
                    "remark": (
                        (item.remark or "").strip()
                        if item is not None
                        else ""
                    ),
                }
            )

        plant = []
        for report in plant_reports:
            items = []
            for item in report.machinery_items.all():
                master = getattr(item, "machinery_master", None)
                items.append(
                    {
                        "name": master.name if master else None,
                        "unit": master.unit if master else None,
                        "qty": int(item.qty) if item.qty is not None else 0,
                        "status": item.status,
                        "remark": (item.remark or "").strip() or None,
                    }
                )
            plant.append(
                {
                    "report_date": _iso(report.report_date),
                    "report_id": report.id,
                    "item_count": len(items),
                    "items": items,
                }
            )

        total_qty = sum(int(row.get("qty") or 0) for row in inventory)
        utilization = None  # not reliably calculable
        status = (
            AVAIL_PARTIAL
            if (equipment_kpi or inventory or plant)
            else AVAIL_UNAVAILABLE
        )
        self._availability["equipment"] = {
            "status": status,
            "missing": ["utilization_percentage"],
            "note": (
                "Full Machinery Master catalogue listed; quantities from the "
                "latest plant report on/before the reporting month end "
                "(missing types shown with qty 0)."
            ),
        }
        return {
            "kpi": equipment_kpi,
            "deployment_summary": (
                {
                    "label": "Equipment Deployment Summary",
                    "planned": equipment_kpi.get("planned_equipment"),
                    "actual": equipment_kpi.get("actual_equipment"),
                    "performance_percentage": equipment_kpi.get(
                        "performance_percentage"
                    ),
                    "remarks": equipment_kpi.get("remarks") or "",
                }
                if equipment_kpi
                else None
            ),
            "inventory": inventory,
            "count": len(inventory),
            "total_quantity": total_qty,
            "source_report_date": (
                _iso(primary_report.report_date) if primary_report else None
            ),
            "plant_machinery_reports": plant,
            "utilization_percentage": utilization,
            "limitations": [
                "Equipment utilization percentage is not reliably available.",
            ],
        }

    def build_photos_section(self) -> dict:
        photos = self._ctx.get("photos") or []
        self._availability["site_photos"] = {
            "status": AVAIL_AVAILABLE if photos else AVAIL_UNAVAILABLE,
        }
        return {
            "count": len(photos),
            "limit": self.photo_limit,
            "photos": [
                {
                    "id": p.id,
                    "title": p.title or "",
                    "image_url": p.image_url,
                    "created_at": _iso(p.created_at),
                    "month": p.month,
                    "year": p.year,
                }
                for p in photos
            ],
        }

    def build_executive_summary(
        self,
        *,
        time_progress: dict | None = None,
        key_indicators: dict | None = None,
        physical: dict | None = None,
        financial: dict | None = None,
        eot: dict | None = None,
        bottlenecks: dict | None = None,
        quality: dict | None = None,
        hse: dict | None = None,
    ) -> dict:
        time = time_progress or {}
        keys = key_indicators or {}
        physical = physical or {}
        financial = financial or {}
        eot = eot or {}
        bottlenecks = bottlenecks or {}
        quality = quality or {}
        hse = hse or {}
        bn = self._ctx.get("bottlenecks") or []
        open_risks = sum(
            1
            for b in bn
            if b.status != Bottleneck.STATUS_CLOSED
            and b.type in (Bottleneck.TYPE_RISK, Bottleneck.TYPE_ISSUE)
        )

        month_key = self.period.month_key
        statements = []

        physical_billed = self.build_physical_billed_till_date(physical)
        financial_billed = self.build_financial_billed_till_date(financial)

        if physical_billed.get("actual_available"):
            statements.append(
                {
                    "topic": "Physical Progress",
                    "text": (
                        f"Cumulative physical progress "
                        f"{physical_billed.get('actual_percentage')}%"
                        + (
                            f" (planned {physical_billed.get('target_percentage')}% "
                            f"for {month_key})."
                            if physical_billed.get("target_available")
                            else f"; reporting-month planned target for {month_key} "
                            f"is not available."
                        )
                    ),
                }
            )
        elif physical.get("monthly_available"):
            m = physical.get("monthly") or {}
            statements.append(
                {
                    "topic": "Physical Progress",
                    "text": (
                        f"Reporting-month planned {m.get('planned_percentage')}%, "
                        f"actual {m.get('actual_percentage')}%."
                    ),
                }
            )
        else:
            statements.append(
                {
                    "topic": "Physical Progress",
                    "text": f"Physical progress data for {month_key} is currently unavailable.",
                }
            )

        if financial_billed.get("actual_available"):
            actual_amt = financial_billed.get("actual_amount")
            target_amt = financial_billed.get("target_amount")
            text = f"Cumulative billed Rs. {float(actual_amt):,.2f}"
            if target_amt is not None:
                text += f" against contract target Rs. {float(target_amt):,.2f}."
            else:
                text += "."
            statements.append({"topic": "Financial Billed", "text": text})

        statements.append(
            {
                "topic": "Time Status",
                "text": (
                    f"Project status: {time.get('project_status') or keys.get('project_status') or 'Not Available'}; "
                    f"time progress {time.get('time_percentage') if time.get('time_percentage') is not None else 'Not Available'}%."
                ),
            }
        )

        latest = eot.get("latest_approved_eot")
        if latest:
            statements.append(
                {
                    "topic": "EOT",
                    "text": (
                        f"Latest approved EOT-{latest.get('eot_number')} "
                        f"({latest.get('extension_days')} days); revised completion "
                        f"{latest.get('revised_completion_date') or 'Not Available'}."
                    ),
                }
            )
        else:
            statements.append(
                {
                    "topic": "EOT",
                    "text": "No approved EOT is currently recorded.",
                }
            )

        statements.append(
            {
                "topic": "Financial",
                "text": (
                    f"Cost status: {keys.get('cost_status') or 'Not Available'}; "
                    f"CPI {keys.get('CPI') if keys.get('CPI') is not None else 'Not Available'}."
                ),
            }
        )

        if quality.get("available"):
            statements.append(
                {
                    "topic": "Quality",
                    "text": (
                        f"Pass {quality.get('pass_percentage')}% "
                        f"({quality.get('tests_passed')}/{quality.get('tests_conducted')} conducted)."
                    ),
                }
            )
        else:
            statements.append(
                {
                    "topic": "Quality",
                    "text": f"Quality performance data for {month_key} is currently unavailable.",
                }
            )

        if hse.get("available"):
            dq = (hse.get("data_quality") or {}).get("status")
            if dq in ("warning", "invalid"):
                statements.append(
                    {
                        "topic": "Safety",
                        "text": (
                            "Safety incident counts are recorded for the period; "
                            "derived rates are not shown due to data-quality concerns."
                        ),
                    }
                )
            else:
                rec = hse.get("record") or {}
                statements.append(
                    {
                        "topic": "Safety",
                        "text": (
                            f"Total incidents {rec.get('total_incidents')}; "
                            f"LTIFR {rec.get('ltifr') if rec.get('ltifr') is not None else 'Not Available'}."
                        ),
                    }
                )
        else:
            statements.append(
                {
                    "topic": "Safety",
                    "text": f"Safety data for {month_key} is currently unavailable.",
                }
            )

        statements.append(
            {
                "topic": "Bottlenecks",
                "text": (
                    f"Open bottlenecks: {bottlenecks.get('open_count') or 0}; "
                    f"overdue: {bottlenecks.get('overdue_count') or 0}; "
                    f"critical: {bottlenecks.get('critical_count') or 0}."
                ),
            }
        )

        decisions = []
        for item in (self.build_client_decisions().get("items") or [])[:5]:
            decisions.append(item.get("description"))

        self._availability["executive_narrative"] = {
            "status": AVAIL_MANUAL,
            "note": "Narrative text fields are not stored; factual auto summary only.",
        }
        self._availability["materials"] = {
            "status": AVAIL_UNAVAILABLE,
            "note": "Material received register is not available.",
        }
        self._availability["laboratory_equipment"] = {
            "status": AVAIL_UNAVAILABLE,
            "note": "Laboratory equipment register is not available.",
        }
        return {
            "manual_input_required": True,
            "executive_summary": None,
            "major_achievements": None,
            "next_month_plan": None,
            "recommendations": None,
            "physical_progress_billed_till_date": physical_billed,
            "financial_progress_billed_till_date": financial_billed,
            "factual_statements": statements,
            "critical_decisions": [d for d in decisions if d],
            "auto": {
                "overall_status": time.get("project_status") or keys.get("project_status"),
                "progress_percentage": keys.get("progress_percentage"),
                "progress_status": keys.get("progress_status"),
                "time_percentage": time.get("time_percentage"),
                "time_status": time.get("status"),
                "cost_status": keys.get("cost_status"),
                "cost_percentage": keys.get("cost_percentage"),
                "key_risks_count": open_risks,
            },
        }

    def build_client_decisions(self) -> dict:
        items = []
        for b in self._ctx.get("bottlenecks") or []:
            if (
                b.type == Bottleneck.TYPE_ACTION
                and b.status != Bottleneck.STATUS_CLOSED
            ):
                items.append(
                    {
                        "source": "bottleneck_action",
                        "id": b.id,
                        "description": b.description,
                        "priority": b.priority,
                        "status": b.status,
                        "target_date": _iso(b.target_date),
                    }
                )
        for d in self._ctx.get("corr_docs") or []:
            if d.delivered_status == CorrespondenceDocument.STATUS_PENDING:
                items.append(
                    {
                        "source": "correspondence_pending",
                        "id": d.id,
                        "description": (d.description or "")[:240],
                        "deadline_date": _iso(d.deadline_date),
                        "delivered_status": d.delivered_status,
                    }
                )
        self._availability["client_decisions"] = {
            "status": AVAIL_PARTIAL,
            "note": "Derived from ACTION bottlenecks and pending correspondence only.",
        }
        return {"items": items[:40]}

    def build_key_indicators(
        self,
        *,
        time_progress: dict | None = None,
        financial: dict | None = None,
        eot: dict | None = None,
        bottlenecks: dict | None = None,
    ) -> dict:
        progress_kpi = build_progress_kpi(
            scope_pct=self._ctx.get("scope_pct"),
            progress_row=self._ctx.get("construction"),
        )
        construction = self._ctx.get("construction")
        cost = self._ctx.get("cost")
        cost_kpi = build_cost_kpi(cost)
        time = time_progress or {}
        contract = (financial or {}).get("contract") or {}
        bn_summary = (bottlenecks or {}).get("summary") or {}

        return {
            "progress_percentage": progress_kpi.get("percentage"),
            "progress_status": progress_kpi.get("status"),
            "planned_progress_percentage": _dec(
                getattr(construction, "plannedProgress", None)
            ),
            "actual_progress_percentage": _dec(
                getattr(construction, "actualProgress", None)
            ),
            "progress_variance": _dec(getattr(construction, "variance", None)),
            "time_percentage": time.get("time_percentage"),
            "delay_days": time.get("delay_days"),
            "project_status": time.get("project_status"),
            "contract_value": contract.get("original_contract_value"),
            "revised_contract_value": contract.get("revised_contract_value"),
            "approved_vo": None,
            "pending_vo": None,
            "BAC": _dec(getattr(cost, "bac", None)),
            "CPI": _dec(getattr(cost, "cpi", None)),
            "SPI": None,
            "EAC": _dec(getattr(cost, "eac", None)),
            "BCWS": _dec(getattr(cost, "bcws", None)),
            "BCWP": _dec(getattr(cost, "bcwp", None)),
            "ACWP": _dec(getattr(cost, "acwp", None)),
            "cost_percentage": cost_kpi.get("percentage"),
            "cost_status": cost_kpi.get("status"),
            "eot_count": (eot or {}).get("eot_count", 0),
            "open_bottlenecks": (bn_summary.get("open_items") or 0)
            + (bn_summary.get("in_progress_items") or 0),
            "overdue_bottlenecks": bn_summary.get("overdue_items"),
        }

    def build_meetings_section(self) -> dict:
        rows = []
        for m in self._ctx.get("meetings") or []:
            rows.append(
                {
                    "id": m.id,
                    "meeting_type": m.meeting_type,
                    "title": m.title,
                    "description": (m.description or "").strip() or None,
                    "meeting_date": _iso(m.meeting_date),
                    "meeting_number": m.meeting_number or None,
                }
            )
        self._availability["meetings"] = {
            "status": AVAIL_AVAILABLE if rows else AVAIL_UNAVAILABLE,
        }
        return {"available": bool(rows), "records": rows}

    def build_next_month_program_section(self) -> dict:
        rows = []
        for idx, row in enumerate(self._ctx.get("next_month_rows") or [], start=1):
            item_name = (
                row.get_subcategory_display_name()
                or row.get_category_display_name()
                or (row.description or "").strip()
                or "Planned activity"
            )
            rows.append(
                {
                    "sr_no": idx,
                    "activity": item_name,
                    "target": _dec(row.planned_quantity),
                    "unit": row.unit or None,
                    "planned_completion": _iso(row.end_date),
                    "remarks": (row.description or "").strip() or None,
                    "status": row.status,
                }
            )
        self._availability["next_month_program"] = {
            "status": AVAIL_AVAILABLE if rows else AVAIL_UNAVAILABLE,
        }
        return {
            "available": bool(rows),
            "month": _iso(_next_month_start(self.period.start_date)),
            "records": rows,
        }

    def build_data_availability(self) -> dict:
        # Ensure weather flagged even if no section called it
        self._availability.setdefault(
            "weather",
            {"status": AVAIL_UNAVAILABLE, "note": "No weather model/API in backend."},
        )
        self._availability.setdefault(
            "formal_vo",
            {
                "status": AVAIL_UNAVAILABLE,
                "note": "No formal VO register.",
            },
        )
        self._availability.setdefault(
            "executive_narrative",
            {"status": AVAIL_MANUAL},
        )
        self._availability.setdefault(
            "ncr",
            {
                "status": AVAIL_UNAVAILABLE,
                "note": "NCR register is not currently available.",
            },
        )
        return dict(self._availability)


def build_mpr_preview(project: Project, month: str, *, photo_limit: int | None = None) -> dict:
    period = parse_mpr_month(month)
    return MPRService(project, period, photo_limit=photo_limit).build()
