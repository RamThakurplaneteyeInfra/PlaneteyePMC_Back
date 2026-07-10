"""Export helpers for Planned vs Actual (CSV / Excel / PDF)."""

from __future__ import annotations

import csv
import io
from decimal import Decimal

from django.http import HttpResponse

EXPORT_COLUMNS = [
    "project_name",
    "planned_type",
    "contractor_name",
    "month",
    "year",
    "planned_value",
    "actual_value",
    "collection",
    "difference",
    "achievement_percentage",
    "collection_percentage",
    "variance_percentage",
    "variance_status",
    "reason_for_difference",
    "remarks",
]

EXPORT_HEADERS = {
    "project_name": "Project Name",
    "planned_type": "Type",
    "contractor_name": "Contractor",
    "month": "Month",
    "year": "Year",
    "planned_value": "Planned Value",
    "actual_value": "Actual Value",
    "collection": "Collection",
    "difference": "Difference",
    "achievement_percentage": "Achievement %",
    "collection_percentage": "Collection %",
    "variance_percentage": "Variance %",
    "variance_status": "Variance Status",
    "reason_for_difference": "Reason for Difference",
    "remarks": "Remarks",
}


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


def planned_vs_actual_rows(queryset) -> list[dict]:
    rows = []
    for record in queryset.select_related("contractor"):
        rows.append(
            {
                "project_name": record.project_name,
                "planned_type": record.planned_type,
                "contractor_name": record.contractor_name or "",
                "month": record.month,
                "year": record.year,
                "planned_value": _fmt(record.planned_value),
                "actual_value": _fmt(record.actual_value),
                "collection": _fmt(record.collection),
                "difference": _fmt(record.difference),
                "achievement_percentage": _fmt(record.achievement_percentage),
                "collection_percentage": _fmt(record.collection_percentage),
                "variance_percentage": _fmt(record.variance_percentage),
                "variance_status": record.variance_status,
                "reason_for_difference": record.reason_for_difference or "",
                "remarks": record.remarks or "",
            }
        )
    return rows


def csv_response(rows: list[dict], filename: str = "planned_vs_actual.csv") -> HttpResponse:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writerow(EXPORT_HEADERS)
    for row in rows:
        writer.writerow(row)
    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def excel_response(rows: list[dict], filename: str = "planned_vs_actual.xlsx") -> HttpResponse:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Planned vs Actual"
    sheet.append([EXPORT_HEADERS[col] for col in EXPORT_COLUMNS])
    for row in rows:
        sheet.append([row.get(col, "") for col in EXPORT_COLUMNS])

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _pdf_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_response(rows: list[dict], filename: str = "planned_vs_actual.pdf") -> HttpResponse:
    lines = ["Planned vs Actual Export", "=" * 72]
    for row in rows:
        lines.append(
            f"{row['project_name']} | {row['planned_type']} | "
            f"{row.get('contractor_name') or '-'} | "
            f"{row['month']:02}/{row['year']} | "
            f"PV={row['planned_value']} AV={row['actual_value']} "
            f"Coll={row['collection']} Diff={row['difference']} | "
            f"Status={row['variance_status']}"
        )
        if row.get("reason_for_difference"):
            lines.append(f"  Reason: {row['reason_for_difference']}")
        lines.append("-" * 72)
    if len(lines) == 2:
        lines.append("No records found.")

    content_lines = []
    y = 800
    for line in lines:
        content_lines.append(f"BT /F1 9 Tf 40 {y} Td ({_pdf_escape(line[:110])}) Tj ET")
        y -= 12
        if y < 40:
            break
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream)} >>stream\n".encode("ascii")
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(buffer.tell())
        buffer.write(obj)
    xref_pos = buffer.tell()
    buffer.write(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    buffer.write(
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def export_response(rows: list[dict], export_format: str) -> HttpResponse:
    fmt = (export_format or "csv").lower()
    if fmt in {"excel", "xlsx", "xls"}:
        return excel_response(rows)
    if fmt == "pdf":
        return pdf_response(rows)
    return csv_response(rows)
