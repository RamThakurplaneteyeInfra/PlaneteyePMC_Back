"""CSV export for Project Dates including BG Status summary."""

import csv
import io

from django.http import HttpResponse

from .bg_status import bg_status_for_project_date
from .models import ProjectDates

EXPORT_COLUMNS = [
    "project_name",
    "date_type",
    "contractor_name",
    "project_start",
    "contract_finish",
    "forecast_finish",
    "eot_date",
    "bg_total",
    "bg_updated",
    "bg_yet_to_update",
    "bg_not_updated",
    "bg_compliance_percentage",
]


def _date_str(value) -> str:
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def project_dates_rows(queryset) -> list[dict]:
    """Build one export row per ProjectDates record."""
    rows = []
    for record in queryset.select_related("project").prefetch_related("bg_statuses"):
        bg = bg_status_for_project_date(record)
        summary = bg["bg_summary"]
        rows.append(
            {
                "project_name": record.project.name,
                "date_type": record.date_type,
                "contractor_name": record.contractor_name or "",
                "project_start": _date_str(record.project_start),
                "contract_finish": _date_str(record.contract_finish),
                "forecast_finish": _date_str(record.forecast_finish),
                "eot_date": _date_str(record.eot_date),
                "bg_total": summary["total_bg"],
                "bg_updated": summary["updated"],
                "bg_yet_to_update": summary["yet_to_update"],
                "bg_not_updated": summary["not_updated"],
                "bg_compliance_percentage": summary["compliance_percentage"],
            }
        )
    return rows


def project_dates_csv_response(rows: list[dict], filename: str = "project_dates.csv") -> HttpResponse:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
