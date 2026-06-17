"""CSV export for client frequency-chart format."""

import csv
import io

from django.http import HttpResponse

from .frequency_chart_report import CLIENT_COLUMNS


def client_report_csv_response(
    rows: list[dict],
    filename: str = "frequency_chart_report.csv",
) -> HttpResponse:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CLIENT_COLUMNS, extrasaction="ignore")
    writer.writeheader()

    for row in rows:
        writer.writerow(
            {
                key: (row.get(key) if row.get(key) is not None else "-")
                for key in CLIENT_COLUMNS
            }
        )

    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
