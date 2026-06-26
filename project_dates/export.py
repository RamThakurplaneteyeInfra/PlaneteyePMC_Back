"""CSV export for Project Dates including BG Status summary."""

import csv
import io
from collections import defaultdict

from django.http import HttpResponse

from projects.models import Project

from .bg_status import bg_status_payload
from .models import ProjectDates

EXPORT_COLUMNS = [
    "project_name",
    "scl_project_start",
    "scl_contract_finish",
    "scl_forecast_finish",
    "scl_eot_date",
    "contractor_project_start",
    "contractor_contract_finish",
    "contractor_forecast_finish",
    "contractor_eot_date",
    "bg_total",
    "bg_updated",
    "bg_yet_to_update",
    "bg_not_updated",
    "bg_compliance_percentage",
    "contractor_bg_count",
    "scl_bg_count",
]


def _date_str(value) -> str:
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def project_dates_rows(queryset) -> list[dict]:
    """Build one export row per project from ProjectDates queryset."""
    by_project: dict[int, dict] = defaultdict(
        lambda: {
            "project_name": "",
            "scl_project_start": "",
            "scl_contract_finish": "",
            "scl_forecast_finish": "",
            "scl_eot_date": "",
            "contractor_project_start": "",
            "contractor_contract_finish": "",
            "contractor_forecast_finish": "",
            "contractor_eot_date": "",
            "bg_total": 0,
            "bg_updated": 0,
            "bg_yet_to_update": 0,
            "bg_not_updated": 0,
            "bg_compliance_percentage": 0.0,
            "contractor_bg_count": 0,
            "scl_bg_count": 0,
        }
    )

    for record in queryset.select_related("project"):
        pid = record.project_id
        row = by_project[pid]
        row["project_name"] = record.project.name

        prefix = "scl" if record.date_type == ProjectDates.DATE_TYPE_SCL else "contractor"
        row[f"{prefix}_project_start"] = _date_str(record.project_start)
        row[f"{prefix}_contract_finish"] = _date_str(record.contract_finish)
        row[f"{prefix}_forecast_finish"] = _date_str(record.forecast_finish)
        row[f"{prefix}_eot_date"] = _date_str(record.eot_date)

    for pid, row in by_project.items():
        project = Project.objects.filter(pk=pid).first()
        bg = bg_status_payload(project)
        summary = bg["bg_summary"]
        row["bg_total"] = summary["total_bg"]
        row["bg_updated"] = summary["updated"]
        row["bg_yet_to_update"] = summary["yet_to_update"]
        row["bg_not_updated"] = summary["not_updated"]
        row["bg_compliance_percentage"] = summary["compliance_percentage"]
        row["contractor_bg_count"] = len(bg["contractor_bg"])
        row["scl_bg_count"] = len(bg["scl_bg"])

    return list(by_project.values())


def project_dates_csv_response(rows: list[dict], filename: str = "project_dates.csv") -> HttpResponse:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
