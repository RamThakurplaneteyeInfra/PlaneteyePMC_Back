"""
Executive DPR digest for PMC Head and Head Office.

Builds a single summary email covering:
  - DPR status counts for a report date
  - Pending approvals (compact list)
  - Active projects with no DPR submitted for that date
  - Responsible Team Leader / site engineer contacts
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from accounts.rbac import ROLE_HEAD_OFFICE, ROLE_HO_ALIAS, ROLE_PMC_HEAD
from dpr.models import DailyProgressReport
from projects.models import Project

logger = logging.getLogger("pmc.dpr.digest")
User = get_user_model()

_FILLED_STATUSES = (
    DailyProgressReport.Status.PENDING_TEAM_LEAD,
    DailyProgressReport.Status.PENDING_COORDINATOR,
    DailyProgressReport.Status.PENDING_PMC_HEAD,
    DailyProgressReport.Status.APPROVED,
    DailyProgressReport.Status.REJECTED,
)

_PENDING_STATUSES = (
    DailyProgressReport.Status.PENDING_TEAM_LEAD,
    DailyProgressReport.Status.PENDING_COORDINATOR,
    DailyProgressReport.Status.PENDING_PMC_HEAD,
)


@dataclass
class DigestCounts:
    total_filled: int = 0
    pending_team_lead: int = 0
    pending_pmc_manager: int = 0
    pending_pmc_head: int = 0
    pending_total: int = 0
    approved: int = 0
    rejected: int = 0
    draft_only: int = 0
    projects_missing: int = 0
    projects_active: int = 0


@dataclass
class PendingDprRow:
    dpr_id: int
    project_name: str
    status: str
    status_label: str
    waiting_on: str
    submitted_by: str
    team_lead: str


@dataclass
class MissingProjectRow:
    project_id: int
    project_name: str
    team_lead: str
    team_lead_email: str
    site_engineers: str


@dataclass
class ExecutiveDigest:
    report_date: date
    generated_at: str
    counts: DigestCounts = field(default_factory=DigestCounts)
    pending_items: list[PendingDprRow] = field(default_factory=list)
    missing_projects: list[MissingProjectRow] = field(default_factory=list)

    def to_context(self) -> dict[str, Any]:
        """
        Flat scalar aliases keep Django ``{{ }}`` tags on one line in HTML
        templates (formatters often break dotted lookups across lines, which
        Brevo then rejects as leftover markers).
        """
        from django.utils.html import escape

        counts = asdict(self.counts)
        missing_rows_html = []
        for row in self.missing_projects:
            missing_rows_html.append(
                "<tr>"
                f'<td style="padding:10px 12px;border-top:1px solid #f3d0d0;font-size:13px;color:#123047;font-weight:600;">{escape(row.project_name)}</td>'
                f'<td style="padding:10px 12px;border-top:1px solid #f3d0d0;font-size:12px;color:#4f6272;">{escape(row.team_lead)}<br><span style="color:#7a8b99;">{escape(row.team_lead_email)}</span></td>'
                f'<td style="padding:10px 12px;border-top:1px solid #f3d0d0;font-size:12px;color:#4f6272;">{escape(row.site_engineers)}</td>'
                "</tr>"
            )
        pending_rows_html = []
        for row in self.pending_items:
            pending_rows_html.append(
                "<tr>"
                f'<td style="padding:10px 12px;border-top:1px solid #f0e0b8;font-size:13px;color:#123047;font-weight:600;">{escape(row.project_name)}</td>'
                f'<td style="padding:10px 12px;border-top:1px solid #f0e0b8;font-size:12px;color:#4f6272;">{escape(row.waiting_on)}</td>'
                f'<td style="padding:10px 12px;border-top:1px solid #f0e0b8;font-size:12px;color:#4f6272;">{escape(row.submitted_by)}</td>'
                "</tr>"
            )
        return {
            "report_date": self.report_date.isoformat(),
            "report_date_display": self.report_date.strftime("%d %b %Y"),
            "generated_at": self.generated_at,
            "counts": counts,
            # Flat aliases for template safety
            "c_filled": counts["total_filled"],
            "c_pending": counts["pending_total"],
            "c_missing": counts["projects_missing"],
            "c_active": counts["projects_active"],
            "c_tl": counts["pending_team_lead"],
            "c_mgr": counts["pending_pmc_manager"],
            "c_head": counts["pending_pmc_head"],
            "c_approved": counts["approved"],
            "c_rejected": counts["rejected"],
            "pending_items": [asdict(row) for row in self.pending_items],
            "missing_projects": [asdict(row) for row in self.missing_projects],
            "missing_rows_html": "".join(missing_rows_html),
            "pending_rows_html": "".join(pending_rows_html),
            "has_pending": bool(self.pending_items),
            "has_missing": bool(self.missing_projects),
        }


def _user_display(user) -> str:
    if not user:
        return "Not assigned"
    return (user.get_full_name() or user.username or "Unknown").strip()


def _site_engineer_names(project: Project) -> str:
    names: list[str] = []
    seen: set[int] = set()
    for user in (
        project.billing_site_engineer,
        project.qaqc_site_engineer,
        getattr(project, "hse_site_engineer", None),
        project.site_engineer,
    ):
        if user and user.id not in seen:
            seen.add(user.id)
            names.append(_user_display(user))
    for user in project.site_engineers.all():
        if user.id not in seen:
            seen.add(user.id)
            names.append(_user_display(user))
    return ", ".join(names) if names else "Not assigned"


def resolve_digest_recipients() -> list:
    """
    PMC Head + Head Office users with an email address.
    Deduplicated by user id.
    """
    qs = (
        User.objects.filter(is_active=True)
        .exclude(email="")
        .filter(
            Q(groups__name=ROLE_PMC_HEAD)
            | Q(groups__name=ROLE_HEAD_OFFICE)
            | Q(groups__name=ROLE_HO_ALIAS)
        )
        .distinct()
        .order_by("id")
    )
    return list(qs)


def build_executive_digest(*, report_date: date | None = None) -> ExecutiveDigest:
    """
    Aggregate DPR + missing-project status for one calendar day.

    A project is "filled" when at least one non-draft DPR exists for that date.
    Draft-only DPRs do not count as submitted.
    """
    if report_date is None:
        report_date = timezone.localdate()

    digest = ExecutiveDigest(
        report_date=report_date,
        generated_at=timezone.localtime().strftime("%d %b %Y, %H:%M"),
    )

    active_projects = list(
        Project.objects.filter(status="active")
        .select_related(
            "team_lead",
            "site_engineer",
            "billing_site_engineer",
            "qaqc_site_engineer",
            "hse_site_engineer",
        )
        .prefetch_related("site_engineers")
        .order_by("name")
    )
    digest.counts.projects_active = len(active_projects)
    projects_by_name = {p.name.strip().casefold(): p for p in active_projects if p.name}

    day_reports = list(
        DailyProgressReport.objects.filter(report_date=report_date)
        .select_related("submitted_by")
        .order_by("project_name", "-id")
    )

    by_project: dict[str, list[DailyProgressReport]] = defaultdict(list)
    for dpr in day_reports:
        key = (dpr.project_name or "").strip().casefold()
        by_project[key].append(dpr)

    filled_project_keys: set[str] = set()

    for key, reports in by_project.items():
        non_draft = [r for r in reports if r.status != DailyProgressReport.Status.DRAFT]
        if not non_draft:
            digest.counts.draft_only += 1
            continue
        filled_project_keys.add(key)
        # Use latest non-draft row for status rollup (highest id already ordered)
        latest = non_draft[0]
        digest.counts.total_filled += 1
        if latest.status == DailyProgressReport.Status.PENDING_TEAM_LEAD:
            digest.counts.pending_team_lead += 1
        elif latest.status == DailyProgressReport.Status.PENDING_COORDINATOR:
            digest.counts.pending_pmc_manager += 1
        elif latest.status == DailyProgressReport.Status.PENDING_PMC_HEAD:
            digest.counts.pending_pmc_head += 1
        elif latest.status == DailyProgressReport.Status.APPROVED:
            digest.counts.approved += 1
        elif latest.status == DailyProgressReport.Status.REJECTED:
            digest.counts.rejected += 1

        if latest.status in _PENDING_STATUSES:
            project = projects_by_name.get(key)
            digest.pending_items.append(
                PendingDprRow(
                    dpr_id=latest.id,
                    project_name=latest.project_name,
                    status=latest.status,
                    status_label=latest.get_status_display(),
                    waiting_on=latest.current_approver_role or latest.get_status_display(),
                    submitted_by=_user_display(latest.submitted_by),
                    team_lead=_user_display(project.team_lead) if project else "Not assigned",
                )
            )

    digest.counts.pending_total = (
        digest.counts.pending_team_lead
        + digest.counts.pending_pmc_manager
        + digest.counts.pending_pmc_head
    )

    for project in active_projects:
        key = project.name.strip().casefold()
        if key in filled_project_keys:
            continue
        digest.counts.projects_missing += 1
        tl = project.team_lead
        digest.missing_projects.append(
            MissingProjectRow(
                project_id=project.id,
                project_name=project.name,
                team_lead=_user_display(tl),
                team_lead_email=(tl.email if tl and tl.email else "—"),
                site_engineers=_site_engineer_names(project),
            )
        )

    return digest


def default_digest_report_date() -> date:
    """Business date for digests — Asia/Kolkata calendar day."""
    from dpr.services.executive_digest import business_localdate

    return business_localdate()
