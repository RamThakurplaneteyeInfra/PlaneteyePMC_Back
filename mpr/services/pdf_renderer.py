"""
MPR PDF renderer — SCL-branded engineering Monthly Progress Report.

Consumes snapshot_json only (no DB queries). Presentation from report_config.
Matches client MPR structure (cover → index → numbered sections). No forwarding letter.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

from mpr.services.report_config import (
    get_mpr_report_config,
    get_mpr_style_config,
    month_year_label,
    resolve_logo_path,
)

logger = logging.getLogger(__name__)

INDEX_ENTRIES: list[tuple[str, str]] = [
    ("1", "Executive Summary"),
    ("2", "Salient Features of the Project"),
    ("3", "Contractual Obligations"),
    ("4", "Progress"),
    ("4.1", "Physical Progress"),
    ("4.2", "Bar Chart (Planned vs. Actual)"),
    ("4.3", "Financial Progress & Gross Monthly Work Done Value"),
    ("4.4", "Important Events"),
    ("5", "Quality Performance"),
    ("5.1", "Material Testing / Frequency Chart"),
    ("6", "Bottlenecks"),
    ("7", "Next Month Program"),
    ("8", "List of Plant and Machinery"),
    ("9", "Laboratory Equipment at Site"),
    ("10", "Status of Drawings"),
    ("10.1", "Drawings Received"),
    ("10.2", "Drawings Balance"),
    ("11", "Material Received at Site"),
    ("12", "Safety Aspect"),
    ("13", "Meetings / Site Visits"),
    ("14", "Manpower Deployed (PMC)"),
    ("15", "Labour Man-Day Bar Chart"),
    ("16", "Photographs"),
]


def _has_lab_equipment(snapshot: dict) -> bool:
    eq = snapshot.get("equipment") or {}
    inventory = eq.get("inventory") or []
    if any(
        ("lab" in (i.get("name") or "").lower()
         or "test" in (i.get("name") or "").lower()
         or "cube" in (i.get("name") or "").lower())
        and int(i.get("qty") or 0) > 0
        for i in inventory
    ):
        return True
    for report in eq.get("plant_machinery_reports") or []:
        for item in report.get("items") or []:
            name = (item.get("name") or "").lower()
            if ("lab" in name or "test" in name or "cube" in name) and int(
                item.get("qty") or 0
            ) > 0:
                return True
    return False


def _has_materials(snapshot: dict) -> bool:
    materials = snapshot.get("materials") or {}
    return bool(materials.get("available") and materials.get("records"))


def _has_meetings(snapshot: dict) -> bool:
    meetings = snapshot.get("meetings") or {}
    if meetings.get("records"):
        return True
    for rec in (snapshot.get("correspondence") or {}).get("important_records") or []:
        if "meet" in (rec.get("description") or "").lower():
            return True
    return False


def _has_labour_chart(snapshot: dict) -> bool:
    hse = (snapshot.get("hse") or {}).get("record") or {}
    mp = snapshot.get("manpower") or {}
    return any(
        v is not None
        for v in (
            hse.get("man_days_worked"),
            hse.get("average_daily_manpower"),
            mp.get("actual_headcount"),
            mp.get("planned_headcount"),
        )
    )


def _has_safety(snapshot: dict) -> bool:
    return bool((snapshot.get("hse") or {}).get("available"))


def build_index_entries(snapshot: dict | None = None) -> list[tuple[str, str]]:
    """Omit empty backend sections that would only show 'not available'."""
    if not snapshot:
        return list(INDEX_ENTRIES)
    omit = set()
    if not _has_lab_equipment(snapshot):
        omit.add("9")
    if not _has_materials(snapshot):
        omit.add("11")
    if not _has_safety(snapshot):
        omit.add("12")
    if not _has_meetings(snapshot):
        omit.add("13")
    if not _has_labour_chart(snapshot):
        omit.add("15")
    return [(sr, subject) for sr, subject in INDEX_ENTRIES if sr not in omit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _s(value: Any, default: str = "—") -> str:
    if value is None or value == "":
        return default
    return escape(str(value))


def _plain(value: Any, default: str = "") -> str:
    if value is None or value == "":
        return default
    return str(value)


def _money(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"Rs. {float(value):,.2f}"
    except (TypeError, ValueError):
        return _plain(value, "—")


def _pct(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return _plain(value, "—")


def _num(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        f = float(value)
        if f == int(f):
            return str(int(f))
        return f"{f:.2f}"
    except (TypeError, ValueError):
        return _plain(value, "—")


def _fmt_date(value: Any) -> str:
    if not value:
        return "—"
    text = str(value)
    if "T" in text:
        text = text.split("T", 1)[0]
    # YYYY-MM-DD -> DD/MM/YYYY
    parts = text.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return text


def _fetch_image(url: str, timeout: int = 5) -> BytesIO | None:
    if not url or not str(url).startswith(("http://", "https://")):
        return None
    if "example.com" in str(url):
        return None
    try:
        req = Request(url, headers={"User-Agent": "PMC-MPR/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            data = resp.read(3 * 1024 * 1024)
        if "html" in ctype or len(data) < 100:
            return None
        from PIL import Image as PILImage

        img = PILImage.open(BytesIO(data))
        img.load()
        img.thumbnail((520, 390))
        out = BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=78)
        out.seek(0)
        return out
    except Exception:
        logger.debug("MPR photo fetch skipped url=%s", url, exc_info=True)
        return None


def _styles(style_cfg):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    base = getSampleStyleSheet()
    brand = colors.HexColor(style_cfg.primary_brand_color)
    return {
        "cover_brand": ParagraphStyle(
            "MPRCoverBrand",
            parent=base["Normal"],
            fontName=style_cfg.heading_font,
            fontSize=style_cfg.cover_subtitle_size,
            alignment=TA_CENTER,
            textColor=brand,
            spaceAfter=6,
            leading=18,
        ),
        "cover_title": ParagraphStyle(
            "MPRCoverTitle",
            parent=base["Normal"],
            fontName=style_cfg.heading_font,
            fontSize=style_cfg.cover_title_size,
            alignment=TA_CENTER,
            spaceBefore=10,
            spaceAfter=8,
            leading=22,
        ),
        "cover_project": ParagraphStyle(
            "MPRCoverProject",
            parent=base["Normal"],
            fontName=style_cfg.heading_font,
            fontSize=13,
            alignment=TA_CENTER,
            spaceBefore=6,
            spaceAfter=4,
            leading=17,
        ),
        "cover_sub": ParagraphStyle(
            "MPRCoverSub",
            parent=base["Normal"],
            fontName=style_cfg.body_font,
            fontSize=11,
            alignment=TA_CENTER,
            leading=14,
            spaceAfter=4,
        ),
        "index_title": ParagraphStyle(
            "MPRIndexTitle",
            parent=base["Normal"],
            fontName=style_cfg.heading_font,
            fontSize=14,
            alignment=TA_CENTER,
            spaceAfter=10,
            leading=18,
        ),
        "h1": ParagraphStyle(
            "MPRH1",
            parent=base["Normal"],
            fontName=style_cfg.heading_font,
            fontSize=style_cfg.heading1_size,
            alignment=TA_LEFT,
            spaceBefore=12,
            spaceAfter=6,
            leading=15,
            textColor=brand,
        ),
        "h2": ParagraphStyle(
            "MPRH2",
            parent=base["Normal"],
            fontName=style_cfg.heading_font,
            fontSize=style_cfg.heading2_size,
            alignment=TA_LEFT,
            spaceBefore=8,
            spaceAfter=4,
            leading=14,
        ),
        "body": ParagraphStyle(
            "MPRBody",
            parent=base["Normal"],
            fontName=style_cfg.body_font,
            fontSize=style_cfg.body_size,
            alignment=TA_JUSTIFY,
            leading=style_cfg.line_spacing,
            spaceAfter=4,
        ),
        "left": ParagraphStyle(
            "MPRLeft",
            parent=base["Normal"],
            fontName=style_cfg.body_font,
            fontSize=style_cfg.body_size,
            alignment=TA_LEFT,
            leading=style_cfg.line_spacing,
            spaceAfter=2,
        ),
        "center": ParagraphStyle(
            "MPRCenter",
            parent=base["Normal"],
            fontName=style_cfg.body_font,
            fontSize=style_cfg.body_size,
            alignment=TA_CENTER,
            leading=style_cfg.line_spacing,
        ),
        "muted": ParagraphStyle(
            "MPRMuted",
            parent=base["Normal"],
            fontName="Times-Italic",
            fontSize=9,
            textColor=colors.HexColor("#555555"),
            leading=12,
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "MPRSmall",
            parent=base["Normal"],
            fontName=style_cfg.body_font,
            fontSize=style_cfg.table_font_size,
            leading=11,
        ),
        "small_center": ParagraphStyle(
            "MPRSmallCenter",
            parent=base["Normal"],
            fontName=style_cfg.body_font,
            fontSize=style_cfg.table_font_size,
            alignment=TA_CENTER,
            leading=11,
        ),
        "header": ParagraphStyle(
            "MPRHeader",
            parent=base["Normal"],
            fontName=style_cfg.heading_font,
            fontSize=8,
            alignment=TA_CENTER,
            leading=10,
        ),
        "footer": ParagraphStyle(
            "MPRFooter",
            parent=base["Normal"],
            fontName=style_cfg.body_font,
            fontSize=8,
            alignment=TA_CENTER,
            leading=10,
        ),
        "right": ParagraphStyle(
            "MPRRight",
            parent=base["Normal"],
            fontName=style_cfg.body_font,
            fontSize=style_cfg.body_size,
            alignment=TA_RIGHT,
            leading=style_cfg.line_spacing,
        ),
    }


def _table_style(style_cfg, *, header=True):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    border = colors.HexColor(style_cfg.border_color)
    header_bg = colors.HexColor(style_cfg.header_bg_color)
    cmds = [
        ("GRID", (0, 0), (-1, -1), 0.5, border),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    if header:
        cmds.append(("BACKGROUND", (0, 0), (-1, 0), header_bg))
        cmds.append(("FONTNAME", (0, 0), (-1, 0), style_cfg.heading_font))
    return TableStyle(cmds)


def _kv_table(story, pairs, styles, style_cfg, col_widths=None):
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table

    data = [
        [Paragraph(f"<b>{_s(k)}</b>", styles["small"]), Paragraph(_s(v), styles["small"])]
        for k, v in pairs
        if v is not None and v != ""
    ]
    if not data:
        story.append(Paragraph("Data not available.", styles["muted"]))
        return
    t = Table(data, colWidths=col_widths or [55 * mm, 125 * mm])
    t.setStyle(_table_style(style_cfg, header=False))
    story.append(t)


def _cell_paragraph(value, styles, *, allow_breaks: bool = False):
    from reportlab.platypus import Paragraph

    if value is None:
        return Paragraph("—", styles["small"])
    if isinstance(value, (list, tuple)):
        parts = [_s(v) for v in value if v not in (None, "")]
        if not parts:
            return Paragraph("—", styles["small"])
        return Paragraph("<br/>".join(parts), styles["small"])
    text = str(value)
    if allow_breaks and ("\n" in text or "<br" in text.lower()):
        text = text.replace("<br/>", "\n").replace("<br>", "\n")
        parts = [_s(p.strip()) for p in text.split("\n") if p.strip()]
        return Paragraph("<br/>".join(parts) if parts else "—", styles["small"])
    return Paragraph(_s(value), styles["small"])


def _grid_table(
    story,
    headers,
    rows,
    styles,
    style_cfg,
    col_widths=None,
    *,
    empty="Data not available.",
    break_cols: set[int] | None = None,
):
    from reportlab.platypus import Paragraph, Table

    if not rows:
        story.append(Paragraph(empty, styles["muted"]))
        return
    break_cols = break_cols or set()
    data = [[Paragraph(f"<b>{_s(h)}</b>", styles["small"]) for h in headers]]
    for row in rows:
        cells = []
        for i, c in enumerate(row):
            if i in break_cols or isinstance(c, (list, tuple)):
                cells.append(_cell_paragraph(c, styles, allow_breaks=True))
            else:
                sty = styles["small_center"] if i == 0 else styles["small"]
                cells.append(Paragraph(_s(c), sty))
        data.append(cells)
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(_table_style(style_cfg))
    story.append(t)


def _na(story, styles, msg: str = "Data not available."):
    from reportlab.platypus import Paragraph

    story.append(Paragraph(msg, styles["muted"]))


def _bar_chart(categories, series_map, *, title="", y_label="%", width=460, height=200):
    """Build a professional grouped bar chart from snapshot chart series."""
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.legends import Legend
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors

    if not categories or not series_map:
        return None
    keys = list(series_map.keys())
    data = []
    for k in keys:
        vals = series_map[k]
        if len(vals) != len(categories):
            return None
        data.append([float(v or 0) for v in vals])
    if not any(any(row) for row in data):
        return None

    max_cats = 12
    if len(categories) > max_cats:
        categories = categories[-max_cats:]
        data = [row[-max_cats:] for row in data]

    drawing = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x = 50
    chart.y = 40
    chart.height = height - 75
    chart.width = width - 90
    chart.data = data
    labels = []
    for c in categories:
        label = str(c)
        if "-" in label:
            parts = label.split("-")
            if len(parts[-1]) == 4:
                label = f"{parts[0][:3]}-{parts[-1][-2:]}"
        labels.append(label)
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.boxAnchor = "ne"
    chart.categoryAxis.labels.angle = 45 if len(labels) > 4 else 0
    chart.categoryAxis.labels.fontSize = 6
    chart.categoryAxis.labels.fontName = "Times-Roman"
    chart.valueAxis.valueMin = 0
    ymax = max(max(row) for row in data)
    chart.valueAxis.valueMax = max(ymax * 1.15, 1)
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labels.fontName = "Times-Roman"
    chart.barWidth = max(4, min(10, int(300 / max(len(labels), 1))))
    chart.groupSpacing = 10
    chart.barSpacing = 1
    palette = [
        colors.HexColor("#0072BC"),
        colors.HexColor("#4DB87E"),
        colors.HexColor("#666666"),
        colors.HexColor("#C45C26"),
    ]
    for i in range(len(data)):
        chart.bars[i].fillColor = palette[i % len(palette)]
        chart.bars[i].strokeColor = colors.black
        chart.bars[i].strokeWidth = 0.3
    drawing.add(chart)
    if title:
        drawing.add(
            String(
                width / 2,
                height - 12,
                title,
                fontName="Times-Bold",
                fontSize=9,
                textAnchor="middle",
            )
        )
    if y_label:
        drawing.add(
            String(14, height / 2, y_label, fontName="Times-Roman", fontSize=7, textAnchor="middle")
        )
    legend = Legend()
    legend.x = 50
    legend.y = 8
    legend.fontName = "Times-Roman"
    legend.fontSize = 7
    legend.boxAnchor = "w"
    legend.columnMaximum = 4
    legend.colorNamePairs = [
        (palette[i % len(palette)], keys[i]) for i in range(len(keys))
    ]
    drawing.add(legend)
    return drawing


# ---------------------------------------------------------------------------
# Pages / sections
# ---------------------------------------------------------------------------


def render_cover_page(snapshot, config, meta, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, Spacer

    story: list = []
    project = snapshot.get("project") or {}
    period = snapshot.get("reporting_period") or {}
    _, _, month_year = month_year_label(period)
    project_name = _plain(project.get("project_name"), "Project")
    consultant = _plain(config.get("consultant_name"), "SHRIKHANDE CONSULTANTS LIMITED")

    story.append(Spacer(1, 25 * mm))
    logo = resolve_logo_path(config)
    if logo is not None:
        try:
            story.append(Image(str(logo), width=90 * mm, height=25 * mm, kind="proportional"))
            story.append(Spacer(1, 8 * mm))
        except Exception:
            logger.debug("SCL logo embed failed", exc_info=True)

    story.append(Paragraph(_s(consultant), styles["cover_brand"]))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("MONTHLY PROGRESS REPORT", styles["cover_title"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(_s(project_name.upper()), styles["cover_project"]))
    story.append(Paragraph(f"FOR {_s(month_year.upper())}", styles["cover_sub"]))
    story.append(Spacer(1, 8 * mm))
    story.append(
        Paragraph(
            _s(config.get("consultant_tagline") or "Project Management Consultants").upper(),
            styles["cover_sub"],
        )
    )

    extras = []
    if project.get("project_code"):
        extras.append(("Project Code", project["project_code"]))
    if period.get("start_date") and period.get("end_date"):
        extras.append(
            (
                "Reporting Period",
                f"{_fmt_date(period['start_date'])} – {_fmt_date(period['end_date'])}",
            )
        )
    version = meta.get("version")
    if version:
        extras.append(("MPR Version", f"v{version}"))
    if extras:
        story.append(Spacer(1, 16 * mm))
        _kv_table(story, extras, styles, style_cfg, col_widths=[45 * mm, 80 * mm])

    story.append(Spacer(1, 20 * mm))
    for line in config.get("consultant_address") or []:
        story.append(Paragraph(_s(line), styles["center"]))
    if config.get("consultant_phone"):
        story.append(Paragraph(_s(config["consultant_phone"]), styles["center"]))
    if config.get("consultant_email"):
        story.append(Paragraph(_s(config["consultant_email"]), styles["center"]))
    if config.get("consultant_web"):
        story.append(Paragraph(_s(config["consultant_web"]), styles["center"]))
    return story


def render_index_page(styles, style_cfg, snapshot: dict | None = None) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table

    story: list = []
    story.append(Paragraph("I N D E X", styles["index_title"]))
    story.append(Spacer(1, 4 * mm))
    rows = [["<b>Sr. No.</b>", "<b>SUBJECT</b>"]]
    for sr, subject in build_index_entries(snapshot):
        indent = "&nbsp;&nbsp;&nbsp;&nbsp;" if "." in sr else ""
        rows.append([sr, f"{indent}{escape(subject)}"])
    data = [[Paragraph(c, styles["small"]) for c in row] for row in rows]
    t = Table(data, colWidths=[25 * mm, 155 * mm], repeatRows=1)
    t.setStyle(_table_style(style_cfg))
    story.append(t)
    return story


def render_executive_summary(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    story: list = []
    story.append(Paragraph("1. EXECUTIVE SUMMARY", styles["h1"]))
    keys = snapshot.get("key_indicators") or {}
    physical = snapshot.get("physical_progress") or {}
    fin = snapshot.get("financial_progress") or {}
    exec_sum = snapshot.get("executive_summary") or {}
    period = (snapshot.get("reporting_period") or {}).get("month") or "the reporting period"

    phys_billed = exec_sum.get("physical_progress_billed_till_date") or {}
    fin_billed = exec_sum.get("financial_progress_billed_till_date") or {}

    # Prefer explicit billed-till-date snapshot; fall back to legacy fields.
    if phys_billed:
        phys_target = phys_billed.get("target_percentage")
        phys_actual = phys_billed.get("actual_percentage")
        phys_available = bool(phys_billed.get("available"))
    else:
        monthly = physical.get("monthly") or {}
        cum = physical.get("cumulative") or {}
        phys_target = monthly.get("planned_percentage")
        phys_actual = cum.get("actual_percentage")
        if phys_actual is None:
            phys_actual = monthly.get("actual_percentage") or keys.get(
                "actual_progress_percentage"
            )
        if phys_target is None:
            phys_target = keys.get("planned_progress_percentage")
        phys_available = bool(physical.get("monthly_available") or phys_actual is not None)

    def _pct_display(value):
        return _pct(value) if value is not None else "Not Available"

    def _money_display(value):
        return _money(value) if value is not None else "Not Available"

    story.append(Paragraph("<b>PHYSICAL PROGRESS BILLED TILL DATE</b>", styles["h2"]))
    if phys_available:
        _kv_table(
            story,
            [
                ("Target", _pct_display(phys_target)),
                ("Actual", _pct_display(phys_actual)),
            ],
            styles,
            style_cfg,
            col_widths=[40 * mm, 60 * mm],
        )
    else:
        _na(story, styles, f"Physical progress data for {period} is currently unavailable.")

    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("<b>FINANCIAL PROGRESS BILLED TILL DATE</b>", styles["h2"]))
    if fin_billed:
        fin_target = fin_billed.get("target_amount")
        fin_actual = fin_billed.get("actual_amount")
        fin_available = bool(fin_billed.get("available"))
    else:
        contract = fin.get("contract") or {}
        fin_target = keys.get("BAC") or contract.get("revised_contract_value") or contract.get(
            "original_contract_value"
        )
        evm = fin.get("evm") or {}
        fin_actual = evm.get("ACWP") or evm.get("BCWP")
        fin_available = fin_target is not None or fin_actual is not None

    if fin_available:
        _kv_table(
            story,
            [
                ("Target", _money_display(fin_target)),
                ("Actual", _money_display(fin_actual)),
            ],
            styles,
            style_cfg,
            col_widths=[40 * mm, 60 * mm],
        )
    else:
        _na(
            story,
            styles,
            "Financial billed progress data is currently unavailable.",
        )
    story.append(Spacer(1, 3 * mm))

    statements = exec_sum.get("factual_statements") or []
    if statements:
        story.append(Paragraph("<b>STATUS SUMMARY</b>", styles["h2"]))
        for stmt in statements:
            topic = stmt.get("topic") or ""
            text = stmt.get("text") or ""
            story.append(Paragraph(f"<b>{_s(topic)}:</b> {_s(text)}", styles["left"]))

    decisions = exec_sum.get("critical_decisions") or []
    if decisions:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph("<b>CRITICAL DECISIONS REQUIRED</b>", styles["h2"]))
        for i, d in enumerate(decisions, start=1):
            story.append(Paragraph(f"{i}. {_s(d)}", styles["left"]))

    auto = exec_sum.get("auto") or {}
    kpi_pairs = [
        ("Overall Status", auto.get("overall_status") or keys.get("project_status")),
        ("Progress Status", auto.get("progress_status") or keys.get("progress_status")),
        ("Time Progress", _pct(auto.get("time_percentage") or keys.get("time_percentage"))),
        ("Cost Status", auto.get("cost_status") or keys.get("cost_status")),
        ("Open Bottlenecks", keys.get("open_bottlenecks")),
        ("EOT Count", keys.get("eot_count")),
        ("CPI", keys.get("CPI") if keys.get("CPI") is not None else "Not Available"),
        ("SPI", keys.get("SPI") if keys.get("SPI") is not None else "Not Available"),
    ]
    story.append(Spacer(1, 3 * mm))
    _kv_table(story, kpi_pairs, styles, style_cfg)
    return story


def render_salient_features(snapshot, styles, style_cfg) -> list:
    from reportlab.platypus import Paragraph

    story: list = []
    story.append(Paragraph("2. SALIENT FEATURES OF THE PROJECT", styles["h1"]))
    p = snapshot.get("project") or {}
    tp = snapshot.get("time_progress") or {}
    fin = (snapshot.get("financial_progress") or {}).get("contract") or {}
    eot = snapshot.get("eot") or {}
    latest = eot.get("latest_approved_eot") or {}

    pairs = [
        ("A) Project", p.get("project_name")),
        ("B) Client", p.get("client")),
        ("C) Consultant", p.get("consultant") or "Shrikhande Consultants Limited"),
        ("D) Location", p.get("location")),
        ("Project Brief", p.get("description")),
        ("Project Start Date", _fmt_date(p.get("project_start") or tp.get("project_start"))),
        ("Original Contract Completion Date", _fmt_date(p.get("contract_finish") or tp.get("original_contract_finish"))),
        ("Current Completion Date", _fmt_date(p.get("current_completion_date") or tp.get("current_completion_date"))),
        ("Contract Value", _money(fin.get("original_contract_value"))),
        ("Revised Contract Value", _money(fin.get("revised_contract_value"))),
        ("Project Duration (elapsed days)", tp.get("elapsed_days")),
        ("Approved EOT Count", eot.get("approved_count")),
        (
            "Latest Approved EOT",
            (
                f"EOT-{latest.get('eot_number')} ({latest.get('extension_days')} days) — "
                f"{latest.get('reason')}"
                if latest
                else None
            ),
        ),
        ("Team Leader", p.get("team_leader")),
        ("Project Code", p.get("project_code")),
    ]
    _kv_table(story, pairs, styles, style_cfg)
    return story


def render_contractual_obligations(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    story: list = []
    story.append(Paragraph("3. CONTRACTUAL OBLIGATIONS", styles["h1"]))
    rows = []
    sr = 1
    bg = snapshot.get("bg") or {}
    for rec in bg.get("records") or []:
        rows.append(
            [
                sr,
                rec.get("bg_name") or rec.get("bg_type") or "Bank Guarantee",
                "As per contract",
                f"Status: {rec.get('status') or '—'}",
                _fmt_date(rec.get("due_date")),
            ]
        )
        sr += 1
    fin = (snapshot.get("financial_progress") or {}).get("contract") or {}
    if fin.get("original_contract_value") is not None:
        rows.append(
            [
                sr,
                "Contract Value",
                _money(fin.get("original_contract_value")),
                f"Revised: {_money(fin.get('revised_contract_value'))}",
                "—",
            ]
        )
        sr += 1
    _grid_table(
        story,
        ["Sr. No.", "Particulars", "Contract Provision", "Details / Status", "Validity"],
        rows,
        styles,
        style_cfg,
        col_widths=[15 * mm, 40 * mm, 40 * mm, 55 * mm, 30 * mm],
        empty="Contractual obligation details are not available.",
    )

    eot = snapshot.get("eot") or {}
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("EOT Status", styles["h2"]))
    eot_rows = []
    for rec in eot.get("history") or []:
        eot_rows.append(
            [
                rec.get("eot_number"),
                _fmt_date(rec.get("original_completion_date")),
                rec.get("extension_days"),
                _fmt_date(rec.get("revised_completion_date")),
                rec.get("reason") or "",
                rec.get("status") or "",
                _fmt_date(rec.get("approval_date")),
            ]
        )
    _grid_table(
        story,
        [
            "EOT No.",
            "Original Completion",
            "Extension Days",
            "Revised Completion",
            "Reason",
            "Status",
            "Approval Date",
        ],
        eot_rows,
        styles,
        style_cfg,
        col_widths=[16 * mm, 28 * mm, 22 * mm, 28 * mm, 40 * mm, 20 * mm, 24 * mm],
        empty="No EOT records available.",
    )
    latest = eot.get("latest_approved_eot")
    if latest:
        story.append(Spacer(1, 2 * mm))
        story.append(
            Paragraph(
                f"Official completion (latest approved EOT): "
                f"{_s(_fmt_date(latest.get('revised_completion_date')))}",
                styles["left"],
            )
        )
    return story


def _append_scope_detail_tables(story, physical, styles, style_cfg) -> None:
    """Detailed assigned-scope breakdown (items + category rollup + chart)."""
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    categories = physical.get("scope_category_summary") or []
    items = physical.get("scope_items") or []
    if not categories and not items:
        return

    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("<b>Cumulative Scope Detail by Category</b>", styles["h2"]))
    if categories:
        cat_rows = []
        for c in categories:
            cat_rows.append(
                [
                    c.get("category"),
                    c.get("item_count"),
                    _num(c.get("planned_quantity")),
                    _num(c.get("completed_quantity")),
                    _pct(c.get("progress_percentage"))
                    if c.get("progress_percentage") is not None
                    else "Not Available",
                ]
            )
        _grid_table(
            story,
            ["Category", "Items", "Planned Qty", "Completed Qty", "Progress %"],
            cat_rows,
            styles,
            style_cfg,
            col_widths=[50 * mm, 18 * mm, 30 * mm, 32 * mm, 28 * mm],
        )
        # Category progress chart
        labels = [str(c.get("category") or "")[:18] for c in categories]
        planned_series = [float(c.get("planned_quantity") or 0) for c in categories]
        completed_series = [float(c.get("completed_quantity") or 0) for c in categories]
        if labels and (any(planned_series) or any(completed_series)):
            chart = _bar_chart(
                labels,
                {"Planned Qty": planned_series, "Completed Qty": completed_series},
                title="Scope Progress by Category (Quantity)",
                y_label="Qty",
            )
            if chart:
                story.append(Spacer(1, 2 * mm))
                story.append(chart)

    if items:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("<b>Assigned Scope Item Progress</b>", styles["h2"]))
        item_rows = []
        for a in items:
            item_rows.append(
                [
                    a.get("sr_no"),
                    a.get("category") or "",
                    a.get("item"),
                    a.get("unit") or "",
                    _num(a.get("total")),
                    _num(a.get("completed") if a.get("completed") is not None else 0),
                    _num(a.get("balance")),
                    (
                        _pct(a.get("percent_achieved"))
                        if a.get("percent_achieved") is not None
                        else "Not Available"
                    ),
                    a.get("status") or "",
                    _fmt_date(a.get("scope_month")) if a.get("scope_month") else "—",
                ]
            )
        _grid_table(
            story,
            [
                "Sr.",
                "Category",
                "Item",
                "Unit",
                "Planned",
                "Completed",
                "Balance",
                "%",
                "Status",
                "Scope Month",
            ],
            item_rows,
            styles,
            style_cfg,
            col_widths=[
                10 * mm,
                28 * mm,
                36 * mm,
                12 * mm,
                16 * mm,
                18 * mm,
                16 * mm,
                14 * mm,
                18 * mm,
                20 * mm,
            ],
        )


def render_progress_section(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    story: list = []
    story.append(Paragraph("4. PROGRESS", styles["h1"]))
    physical = snapshot.get("physical_progress") or {}
    story.append(Paragraph("4.1 Physical Progress", styles["h2"]))

    monthly = physical.get("monthly") or {}
    cum = physical.get("cumulative") or {}
    scope = physical.get("scope_progress") or {}
    reporting_period = snapshot.get("reporting_period") or {}
    _, _, period_label = month_year_label(reporting_period)
    month_label = period_label if period_label != "Unknown" else (
        physical.get("reporting_month_label")
        or monthly.get("reporting_month")
        or reporting_period.get("month")
        or "the reporting period"
    )

    def _pct_na(value):
        return _pct(value) if value is not None else "Not Available"

    def _num_na(value):
        return _num(value) if value is not None else "Not Available"

    monthly_available = monthly.get("available")
    if monthly_available is None:
        monthly_available = (
            monthly.get("planned_percentage") is not None
            or monthly.get("actual_percentage") is not None
        )

    story.append(Paragraph("<b>Monthly Progress</b>", styles["h2"]))
    if monthly_available:
        _kv_table(
            story,
            [
                ("Monthly Planned %", _pct_na(monthly.get("planned_percentage"))),
                ("Monthly Actual %", _pct_na(monthly.get("actual_percentage"))),
                ("Variance %", _pct_na(monthly.get("variance_percentage"))),
            ],
            styles,
            style_cfg,
            col_widths=[55 * mm, 50 * mm],
        )
    else:
        _na(
            story,
            styles,
            monthly.get("message")
            or f"Monthly Progress Data: Not available for {month_label}.",
        )
        _kv_table(
            story,
            [
                ("Monthly Planned %", "Not Available"),
                ("Monthly Actual %", "Not Available"),
                ("Variance %", "Not Available"),
            ],
            styles,
            style_cfg,
            col_widths=[55 * mm, 50 * mm],
        )

    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("<b>Cumulative Progress</b>", styles["h2"]))
    cum_actual = cum.get("actual_percentage")
    planned_qty = cum.get("scope_planned_quantity")
    if planned_qty is None:
        planned_qty = scope.get("planned_quantity")
    completed_qty = cum.get("scope_completed_quantity")
    if completed_qty is None:
        completed_qty = scope.get("cumulative_quantity")
    scope_pct = cum.get("scope_progress_percentage")
    if scope_pct is None:
        scope_pct = scope.get("progress_percentage")

    if cum.get("available") or cum_actual is not None or planned_qty is not None:
        _kv_table(
            story,
            [
                ("Cumulative Actual %", _pct_na(cum_actual)),
                ("Scope Planned Qty", _num_na(planned_qty)),
                ("Scope Completed Qty", _num_na(completed_qty)),
                ("Scope Progress %", _pct_na(scope_pct)),
                ("Scope Items", cum.get("item_count") or len(physical.get("scope_items") or [])),
                ("Categories", cum.get("category_count") or len(physical.get("scope_category_summary") or [])),
            ],
            styles,
            style_cfg,
            col_widths=[55 * mm, 50 * mm],
        )
        _append_scope_detail_tables(story, physical, styles, style_cfg)
    else:
        _na(
            story,
            styles,
            cum.get("message") or "Scope progress data is not available.",
        )

    activities = physical.get("activities") or []
    if activities and not (physical.get("scope_items") or []):
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("<b>Reporting-Month Scope Activities</b>", styles["h2"]))
        rows = []
        for a in activities:
            rows.append(
                [
                    a.get("sr_no"),
                    a.get("item"),
                    a.get("unit") or "",
                    _num(a.get("total")),
                    _num(a.get("completed")),
                    _num(a.get("balance")),
                    _pct(a.get("percent_achieved")),
                    a.get("remarks") or a.get("status") or "",
                ]
            )
        _grid_table(
            story,
            [
                "Sr. No.",
                "Item",
                "Unit",
                "Total",
                "Completed",
                "Balance",
                "% Achieved",
                "Remarks",
            ],
            rows,
            styles,
            style_cfg,
            col_widths=[14 * mm, 42 * mm, 14 * mm, 18 * mm, 20 * mm, 18 * mm, 20 * mm, 24 * mm],
        )

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("4.2 Bar Chart (Planned vs. Actual)", styles["h2"]))
    chart_data = physical.get("chart") or {}
    report_month = (
        reporting_period.get("month")
        or chart_data.get("reporting_month")
    )
    # Label must follow reporting_period — never infer from last CP history month
    report_label = month_label
    if chart_data.get("reporting_month") == report_month and chart_data.get(
        "reporting_month_label"
    ):
        report_label = chart_data.get("reporting_month_label") or report_label
    available_periods = chart_data.get("available_periods") or chart_data.get("periods") or []
    planned_series = chart_data.get("planned") or []
    actual_series = chart_data.get("actual") or []
    reporting_month_available = chart_data.get("reporting_month_available")
    if reporting_month_available is None:
        reporting_month_available = bool(chart_data.get("includes_reporting_month"))
    render_mode = chart_data.get("render_mode")
    if not render_mode:
        render_mode = "chart" if len(available_periods) >= 2 else "info_block"
    chart_message = chart_data.get("message") or chart_data.get("subtitle")
    if not chart_message and not reporting_month_available and report_label:
        chart_message = (
            f"Monthly Construction Progress data is not available for {report_label}."
        )

    title = chart_data.get("title") or f"Physical Progress — {report_label}"
    story.append(Paragraph(f"<b>{_s(title)}</b>", styles["h2"]))
    _na(story, styles, f"REPORTING PERIOD: {str(report_label).upper()}")

    def _append_cumulative_kpi():
        scope_pairs = []
        if chart_data.get("cumulative_scope_progress") is not None or cum_actual is not None:
            scope_pairs.append(
                (
                    "Cumulative Scope Progress",
                    _pct_na(
                        chart_data.get("cumulative_scope_progress")
                        if chart_data.get("cumulative_scope_progress") is not None
                        else cum_actual
                    ),
                )
            )
        planned_kpi = chart_data.get("cumulative_scope_planned_quantity")
        if planned_kpi is None:
            planned_kpi = planned_qty
        completed_kpi = chart_data.get("cumulative_scope_completed_quantity")
        if completed_kpi is None:
            completed_kpi = completed_qty
        if planned_kpi is not None:
            scope_pairs.append(("Scope Planned", _num_na(planned_kpi)))
        if completed_kpi is not None:
            scope_pairs.append(("Scope Completed", _num_na(completed_kpi)))
        if scope_pairs:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph("<b>Cumulative Scope KPI</b>", styles["left"]))
            _kv_table(
                story,
                scope_pairs,
                styles,
                style_cfg,
                col_widths=[55 * mm, 50 * mm],
            )

    # Compact professional block when too few CP periods for a meaningful chart.
    # Never invent a reporting-month point or plot missing values as zero.
    if render_mode == "info_block" or len(available_periods) < 2:
        hist_rows = chart_data.get("historical_rows") or []
        if not hist_rows and available_periods:
            for i, p in enumerate(available_periods):
                hist_rows.append(
                    {
                        "month": p,
                        "month_label": p,
                        "planned_percentage": (
                            planned_series[i] if i < len(planned_series) else None
                        ),
                        "actual_percentage": (
                            actual_series[i] if i < len(actual_series) else None
                        ),
                    }
                )
        story.append(Paragraph("<b>Historical Construction Progress</b>", styles["left"]))
        if hist_rows:
            for row in hist_rows:
                _na(
                    story,
                    styles,
                    (
                        f"{row.get('month_label') or row.get('month')}: "
                        f"Planned {_pct_na(row.get('planned_percentage'))}, "
                        f"Actual {_pct_na(row.get('actual_percentage'))}"
                    ),
                )
        else:
            _na(story, styles, "No historical monthly Construction Progress records.")

        story.append(Spacer(1, 2 * mm))
        story.append(
            Paragraph(
                f"<b>Current reporting month ({_s(report_label)})</b>",
                styles["left"],
            )
        )
        if reporting_month_available:
            _kv_table(
                story,
                [
                    ("Monthly Planned %", _pct_na(monthly.get("planned_percentage"))),
                    ("Monthly Actual %", _pct_na(monthly.get("actual_percentage"))),
                ],
                styles,
                style_cfg,
                col_widths=[55 * mm, 50 * mm],
            )
        else:
            _na(
                story,
                styles,
                chart_message
                or f"Monthly Construction Progress data is not available for {report_label}.",
            )
        _append_cumulative_kpi()
    elif (
        available_periods
        and planned_series
        and actual_series
        and len(available_periods) == len(planned_series)
    ):
        # Historical trend only — periods never include fabricated report-month zeros
        chart = _bar_chart(
            available_periods,
            {"Planned": planned_series, "Actual": actual_series},
            title=f"{title} (Historical Construction Progress)",
        )
        if chart:
            story.append(chart)
            if not reporting_month_available and chart_message:
                _na(story, styles, chart_message)
            _append_cumulative_kpi()
        else:
            _na(story, styles, "Physical progress chart data is not available.")
            _append_cumulative_kpi()
    else:
        # Reporting-month CP exists but no multi-period history yet
        has_monthly_vals = (
            monthly.get("planned_percentage") is not None
            or monthly.get("actual_percentage") is not None
        )
        if reporting_month_available and has_monthly_vals and report_month:
            chart = _bar_chart(
                [report_month],
                {
                    "Planned": [monthly.get("planned_percentage")],
                    "Actual": [monthly.get("actual_percentage")],
                },
                title=title,
            )
            if chart:
                story.append(chart)
            else:
                _na(story, styles, "Physical progress chart data is not available.")
            _append_cumulative_kpi()
        else:
            _na(
                story,
                styles,
                chart_message
                or f"Monthly Construction Progress data is not available for {report_label}.",
            )
            _append_cumulative_kpi()

    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph("4.3 Financial Progress & Gross Monthly Work Done Value", styles["h2"])
    )
    fin = snapshot.get("financial_progress") or {}
    contract = fin.get("contract") or {}
    evm = fin.get("evm") or {}
    cf = fin.get("cashflow") or {}
    keys = snapshot.get("key_indicators") or {}
    _kv_table(
        story,
        [
            ("Contract Value", _money(contract.get("original_contract_value"))),
            ("Revised Contract Value", _money(contract.get("revised_contract_value"))),
            ("Monthly Work Done (ACWP)", _money(evm.get("ACWP"))),
            ("Cumulative Work Done (BCWP)", _money(evm.get("BCWP"))),
            ("Planned Value (BCWS)", _money(evm.get("BCWS"))),
            ("Financial Progress %", _pct(keys.get("cost_percentage"))),
            ("CPI", _num(evm.get("CPI") or keys.get("CPI"))),
            ("SPI", _num(evm.get("SPI") or keys.get("SPI"))),
            ("EAC", _money(evm.get("EAC"))),
            ("BAC", _money(evm.get("BAC"))),
            ("Cash In (Monthly Actual)", _money(cf.get("cash_in_monthly_actual"))),
            ("Cash Out (Monthly Actual)", _money(cf.get("cash_out_monthly_actual"))),
        ],
        styles,
        style_cfg,
    )
    fin_chart = fin.get("chart") or {}
    fin_periods = fin_chart.get("periods") or []
    if len(fin_periods) >= 2:
        chart = _bar_chart(
            fin_periods,
            {
                "Planned (BCWS)": fin_chart.get("planned") or [],
                "Actual (ACWP)": fin_chart.get("actual") or [],
            },
            title=fin_chart.get("title") or "Monthly Planned vs Actual Financial Progress",
            y_label="Value",
        )
        if chart:
            story.append(Spacer(1, 3 * mm))
            story.append(chart)
    elif not fin_periods:
        _na(story, styles, "Historical monthly financial data is not available.")

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("4.4 Important Events", styles["h2"]))
    events = []
    for rec in (snapshot.get("correspondence") or {}).get("important_records") or []:
        events.append(
            (
                rec.get("received_date") or "",
                [
                    _fmt_date(rec.get("received_date")),
                    rec.get("correspondence_type") or "Correspondence",
                    rec.get("description") or "",
                    rec.get("delivered_status") or "",
                ],
            )
        )
    for rec in (snapshot.get("eot") or {}).get("history") or []:
        events.append(
            (
                rec.get("approval_date") or rec.get("revised_completion_date") or "",
                [
                    _fmt_date(rec.get("approval_date") or rec.get("revised_completion_date")),
                    f"EOT-{rec.get('eot_number')}",
                    rec.get("reason") or "",
                    rec.get("status") or "",
                ],
            )
        )
    for rec in ((snapshot.get("bottlenecks") or {}).get("records") or [])[:5]:
        events.append(
            (
                rec.get("created_at") or "",
                [
                    _fmt_date(rec.get("created_at")),
                    rec.get("type") or "Bottleneck",
                    rec.get("description") or "",
                    rec.get("status") or "",
                ],
            )
        )
    events.sort(key=lambda x: x[0] or "9999")
    _grid_table(
        story,
        ["Date", "Event", "Description", "Status"],
        [row for _, row in events],
        styles,
        style_cfg,
        col_widths=[28 * mm, 35 * mm, 85 * mm, 25 * mm],
        empty="No important events recorded for the reporting period.",
    )
    return story


def render_quality(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    story: list = []
    story.append(Paragraph("5. QUALITY PERFORMANCE", styles["h1"]))
    q = snapshot.get("quality") or {}
    if not q.get("available"):
        _na(story, styles, "Quality performance data is not available for the reporting period.")
    else:
        _kv_table(
            story,
            [
                ("Tests Required", q.get("tests_required")),
                ("Tests Conducted", q.get("tests_conducted")),
                ("Tests Passed", q.get("tests_passed")),
                ("Tests Failed", q.get("tests_failed")),
                ("Pass %", _pct(q.get("pass_percentage"))),
                ("Fail %", _pct(q.get("fail_percentage"))),
                ("Quality Performance", q.get("quality_performance")),
                ("Shortfall", q.get("shortfall")),
            ],
            styles,
            style_cfg,
        )
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("5.1 Material Testing / Frequency Chart", styles["h2"]))
    if q.get("available") and q.get("tests_required") is not None:
        chart = _bar_chart(
            ["Required", "Conducted", "Passed", "Failed"],
            {
                "Count": [
                    q.get("tests_required") or 0,
                    q.get("tests_conducted") or 0,
                    q.get("tests_passed") or 0,
                    q.get("tests_failed") or 0,
                ]
            },
            title="Material Testing Summary",
            y_label="Nos",
        )
        if chart:
            story.append(chart)
        else:
            _na(story, styles, "Material testing chart data is not available.")
    else:
        _na(story, styles, "Material testing / frequency data is not available.")
    return story


def render_bottlenecks(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph

    story: list = []
    story.append(Paragraph("6. BOTTLENECKS", styles["h1"]))
    rows = []
    for i, rec in enumerate((snapshot.get("bottlenecks") or {}).get("records") or [], start=1):
        rows.append(
            [
                i,
                rec.get("description") or "",
                rec.get("category") or rec.get("type") or "",
                rec.get("assigned_to") or "",
                _fmt_date(rec.get("date_raised") or rec.get("created_at")),
                _fmt_date(rec.get("target_date")),
                rec.get("status") or "",
                rec.get("days_open") if rec.get("days_open") is not None else "",
                rec.get("action_required") or "",
            ]
        )
    _grid_table(
        story,
        [
            "Sr. No.",
            "Bottleneck",
            "Category",
            "Responsible Party",
            "Date Raised",
            "Target Resolution",
            "Status",
            "Days Open",
            "Action Required",
        ],
        rows,
        styles,
        style_cfg,
        col_widths=[12 * mm, 38 * mm, 18 * mm, 24 * mm, 20 * mm, 22 * mm, 16 * mm, 14 * mm, 22 * mm],
        empty="No open bottlenecks for the reporting period.",
    )
    return story


def render_next_month(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph

    story: list = []
    story.append(Paragraph("7. NEXT MONTH PROGRAM", styles["h1"]))
    prog = snapshot.get("next_month_program") or {}
    rows = []
    for rec in prog.get("records") or []:
        target = rec.get("target")
        unit = rec.get("unit") or ""
        target_txt = f"{_num(target)} {unit}".strip() if target is not None else "—"
        rows.append(
            [
                rec.get("sr_no"),
                rec.get("activity"),
                target_txt,
                _fmt_date(rec.get("planned_completion")),
                rec.get("remarks") or "",
            ]
        )
    _grid_table(
        story,
        ["Sr. No.", "Activity", "Target", "Planned Completion", "Remarks"],
        rows,
        styles,
        style_cfg,
        col_widths=[15 * mm, 55 * mm, 30 * mm, 35 * mm, 40 * mm],
        empty="Next month programme data is not available.",
    )
    return story


def render_plant_machinery(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph

    story: list = []
    story.append(Paragraph("8. LIST OF PLANT AND MACHINERY", styles["h1"]))
    eq = snapshot.get("equipment") or {}
    rows = []
    sr = 1
    summary = eq.get("deployment_summary") or {}
    kpi = eq.get("kpi") or {}
    if summary or kpi:
        rows.append(
            [
                sr,
                summary.get("label") or "Equipment Deployment Summary",
                _num(summary.get("planned") if summary else kpi.get("planned_equipment")),
                _num(summary.get("actual") if summary else kpi.get("actual_equipment")),
                f"{_pct(summary.get('performance_percentage') if summary else kpi.get('performance_percentage'))}",
                (summary.get("remarks") if summary else kpi.get("remarks")) or "",
            ]
        )
        sr += 1

    inventory = eq.get("inventory") or []
    if inventory:
        source_date = eq.get("source_report_date")
        count = eq.get("count")
        if count is None:
            count = len(inventory)
        total_qty = eq.get("total_quantity")
        if total_qty is None:
            total_qty = sum(int(i.get("qty") or 0) for i in inventory)
        note = f"Total plant & machinery types: {count} | Total quantity: {total_qty}"
        if source_date:
            note += f" | Source report date: {_fmt_date(source_date)}"
        _na(story, styles, note)
        for item in inventory:
            qty = item.get("qty")
            if qty is None:
                qty = 0
            rows.append(
                [
                    sr,
                    item.get("name") or "Equipment",
                    item.get("unit") or "",
                    _num(qty),
                    item.get("status") or "",
                    item.get("remark") or "",
                ]
            )
            sr += 1
    else:
        for report in eq.get("plant_machinery_reports") or []:
            for item in report.get("items") or []:
                qty = item.get("qty")
                if qty is None:
                    qty = 0
                rows.append(
                    [
                        sr,
                        item.get("name") or "Equipment",
                        item.get("unit") or "",
                        _num(qty),
                        item.get("status") or "",
                        f"Report {_fmt_date(report.get('report_date'))}",
                    ]
                )
                sr += 1

    _grid_table(
        story,
        [
            "Sr. No.",
            "Equipment / Plant",
            "Unit / Planned",
            "Available / Actual",
            "Deployment Status",
            "Remarks",
        ],
        rows,
        styles,
        style_cfg,
        col_widths=[14 * mm, 45 * mm, 28 * mm, 28 * mm, 30 * mm, 30 * mm],
        empty="Plant and machinery data is not available.",
    )
    return story


def render_lab_equipment(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph

    if not _has_lab_equipment(snapshot):
        return []
    story: list = []
    story.append(Paragraph("9. LABORATORY EQUIPMENT AT SITE", styles["h1"]))
    rows = []
    sr = 1
    eq = snapshot.get("equipment") or {}

    def _is_lab(name: str) -> bool:
        n = (name or "").lower()
        return "lab" in n or "test" in n or "cube" in n

    inventory = eq.get("inventory") or []
    if inventory:
        for item in inventory:
            if not _is_lab(item.get("name") or ""):
                continue
            qty = item.get("qty")
            if qty is None:
                qty = 0
            rows.append(
                [
                    sr,
                    item.get("name"),
                    _num(qty),
                    item.get("status") or "",
                    _fmt_date(eq.get("source_report_date")),
                ]
            )
            sr += 1
    else:
        for report in eq.get("plant_machinery_reports") or []:
            for item in report.get("items") or []:
                if not _is_lab(item.get("name") or ""):
                    continue
                qty = item.get("qty")
                if qty is None:
                    qty = 0
                rows.append(
                    [
                        sr,
                        item.get("name"),
                        _num(qty),
                        item.get("status") or "",
                        _fmt_date(report.get("report_date")),
                    ]
                )
                sr += 1
    _grid_table(
        story,
        ["Sr. No.", "Equipment", "Quantity", "Status", "Report Date"],
        rows,
        styles,
        style_cfg,
        col_widths=[14 * mm, 55 * mm, 25 * mm, 35 * mm, 30 * mm],
        empty="Laboratory equipment register is not available.",
    )
    return story


def render_drawings(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    story: list = []
    story.append(Paragraph("10. STATUS OF DRAWINGS", styles["h1"]))
    story.append(
        Paragraph("STATEMENT SHOWING DESIGN & DRAWING STATUS", styles["h2"])
    )
    drawings = snapshot.get("drawings") or {}
    items = drawings.get("register_items") or []
    rows = []
    for item in items:
        submission_dates = [
            _fmt_date(d) for d in (item.get("submission_by_contractor") or []) if d
        ]
        reply_dates = [_fmt_date(d) for d in (item.get("reply_by_scl") or []) if d]
        if not submission_dates and item.get("submitted_date"):
            submission_dates = [_fmt_date(item.get("submitted_date"))]
        if not reply_dates and item.get("approved_date"):
            reply_dates = [_fmt_date(item.get("approved_date"))]
        name = item.get("drawing_name") or ""
        rev = item.get("revision")
        if rev:
            name = f"{name} (Rev {rev})"
        remarks = item.get("remarks") or ""
        if item.get("approved_date"):
            remarks = (remarks + f" Approved on {_fmt_date(item.get('approved_date'))}").strip()
        rows.append(
            [
                item.get("sr_no"),
                name,
                submission_dates or "—",
                reply_dates or "—",
                item.get("status") or "—",
                remarks or "—",
            ]
        )
    if not rows:
        for item in drawings.get("pending_items") or []:
            rows.append(
                [
                    item.get("sr_no"),
                    item.get("drawing_name"),
                    _fmt_date(item.get("submitted_date")),
                    "—",
                    "Under Review",
                    item.get("remarks") or "Pending",
                ]
            )
    _grid_table(
        story,
        [
            "Sr. No.",
            "Design / Drawing",
            "Submission by Contractor",
            "Reply by SCL",
            "Status",
            "Remarks",
        ],
        rows,
        styles,
        style_cfg,
        col_widths=[12 * mm, 48 * mm, 32 * mm, 32 * mm, 22 * mm, 34 * mm],
        empty="Drawing status information is not available.",
        break_cols={2, 3},
    )

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("10.1 Drawings Received", styles["h2"]))
    recv = drawings.get("received_summary") or {
        "total_drawings": drawings.get("total_register"),
        "received": drawings.get("submitted"),
        "reviewed": drawings.get("submitted"),
        "approved": drawings.get("approved"),
        "pending": drawings.get("pending"),
    }
    recv_chart = _bar_chart(
        ["Total", "Received", "Reviewed", "Approved", "Pending"],
        {
            "Drawings": [
                float(recv.get("total_drawings") or 0),
                float(recv.get("received") or 0),
                float(recv.get("reviewed") or 0),
                float(recv.get("approved") or 0),
                float(recv.get("pending") or 0),
            ]
        },
        title="Drawings Received Summary",
        y_label="Nos",
    )
    if recv_chart:
        story.append(recv_chart)
        story.append(Spacer(1, 2 * mm))
    _kv_table(
        story,
        [
            ("Total Drawings", recv.get("total_drawings")),
            ("Received", recv.get("received")),
            ("Reviewed", recv.get("reviewed")),
            ("Approved", recv.get("approved")),
            ("Pending", recv.get("pending")),
        ],
        styles,
        style_cfg,
    )

    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("10.2 Drawings Balance", styles["h2"]))
    bal = drawings.get("balance_summary") or {}
    bal_chart = _bar_chart(
        ["Pending", "Contractor", "PMC/SCL", "Client"],
        {
            "Balance": [
                float(bal.get("pending_drawings") or 0),
                float(bal.get("pending_with_contractor") or 0),
                float(bal.get("pending_with_pmc") or 0),
                float(bal.get("pending_with_client") or 0),
            ]
        },
        title="Drawings Balance Summary",
        y_label="Nos",
    )
    if bal_chart:
        story.append(bal_chart)
        story.append(Spacer(1, 2 * mm))
    _kv_table(
        story,
        [
            ("Pending Drawings", bal.get("pending_drawings")),
            ("Pending with Contractor", bal.get("pending_with_contractor")),
            ("Pending with PMC/SCL", bal.get("pending_with_pmc")),
            ("Pending with Client/Authority", bal.get("pending_with_client")),
        ],
        styles,
        style_cfg,
    )
    return story


def render_materials(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph

    if not _has_materials(snapshot):
        return []
    story: list = []
    story.append(Paragraph("11. MATERIAL RECEIVED AT SITE", styles["h1"]))
    materials = snapshot.get("materials") or {}
    rows = []
    for i, rec in enumerate(materials.get("records") or [], start=1):
        rows.append(
            [
                i,
                rec.get("material"),
                rec.get("unit"),
                rec.get("received_this_month"),
                rec.get("cumulative_received"),
                rec.get("remarks") or "",
            ]
        )
    _grid_table(
        story,
        ["Sr. No.", "Material", "Unit", "Received This Month", "Cumulative", "Remarks"],
        rows,
        styles,
        style_cfg,
        col_widths=[14 * mm, 45 * mm, 18 * mm, 30 * mm, 28 * mm, 35 * mm],
    )
    return story


def render_safety(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    if not _has_safety(snapshot):
        return []
    story: list = []
    story.append(Paragraph("12. SAFETY ASPECT", styles["h1"]))
    hse = snapshot.get("hse") or {}
    rec = hse.get("record") or {}
    ltifr = rec.get("ltifr")
    incident_rate = rec.get("incident_rate")
    if hse.get("rates_available") is False:
        ltifr_display = "Not Available"
        incident_display = "Not Available"
    else:
        ltifr_display = ltifr if ltifr is not None else "Not Available"
        incident_display = incident_rate if incident_rate is not None else "Not Available"

    incident_values = [
        float(rec.get("near_miss") or 0),
        float(rec.get("minor") or 0),
        float(rec.get("major") or 0),
        float(rec.get("significant") or 0),
        float(rec.get("fatalities") or 0),
        float(rec.get("reportable_accident_lti") or 0),
    ]
    if any(incident_values):
        chart = _bar_chart(
            ["Near Miss", "Minor", "Major", "Significant", "Fatalities", "LTI"],
            {"Incidents": incident_values},
            title="Safety Incident Breakdown",
            y_label="Nos",
        )
        if chart:
            story.append(chart)
            story.append(Spacer(1, 2 * mm))

    _kv_table(
        story,
        [
            ("Total Manhours", _num(rec.get("total_manhours") or rec.get("man_hours_worked"))),
            ("Man-Days Worked", _num(rec.get("man_days_worked"))),
            ("Average Daily Manpower", _num(rec.get("average_daily_manpower"))),
            ("Working Days", rec.get("working_days")),
            ("Total Incidents", rec.get("total_incidents")),
            ("Near Miss", rec.get("near_miss")),
            ("Major Incidents", rec.get("major")),
            ("Minor Incidents", rec.get("minor")),
            ("Significant Incidents", rec.get("significant")),
            ("Fatalities", rec.get("fatalities")),
            ("Reportable Accident (LTI)", rec.get("reportable_accident_lti")),
            ("LTIFR", ltifr_display),
            ("Incident Rate", incident_display),
            ("Loss of Manhours", _num(rec.get("loss_of_manhours"))),
        ],
        styles,
        style_cfg,
    )
    return story


def render_meetings(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph

    if not _has_meetings(snapshot):
        return []
    story: list = []
    story.append(Paragraph("13. MEETINGS / SITE VISITS", styles["h1"]))
    rows = []
    for i, rec in enumerate((snapshot.get("meetings") or {}).get("records") or [], start=1):
        rows.append(
            [
                i,
                _fmt_date(rec.get("meeting_date")),
                f"{rec.get('meeting_type') or ''} {rec.get('meeting_number') or ''}".strip()
                or (rec.get("title") or "Meeting"),
                "",
                rec.get("title") or "",
                rec.get("description") or "",
            ]
        )
    if not rows:
        for i, rec in enumerate(
            (snapshot.get("correspondence") or {}).get("important_records") or [], start=1
        ):
            if "meet" not in (rec.get("description") or "").lower():
                continue
            rows.append(
                [
                    i,
                    _fmt_date(rec.get("received_date")),
                    "Correspondence",
                    rec.get("sender") or "",
                    rec.get("description") or "",
                    rec.get("delivered_status") or "",
                ]
            )
    _grid_table(
        story,
        [
            "Sr. No.",
            "Date",
            "Meeting / Site Visit",
            "Participants",
            "Purpose / Discussion",
            "Action / Outcome",
        ],
        rows,
        styles,
        style_cfg,
        col_widths=[12 * mm, 22 * mm, 35 * mm, 28 * mm, 45 * mm, 35 * mm],
    )
    return story


def render_manpower(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph

    story: list = []
    story.append(Paragraph("14. MANPOWER DEPLOYED (PMC)", styles["h1"]))
    mp = snapshot.get("manpower") or {}
    if not mp.get("available"):
        _na(story, styles, "PMC manpower data is not available for the reporting period.")
        return story
    rows = [
        [1, "Planned Headcount", _num(mp.get("planned_headcount"))],
        [2, "Actual Headcount", _num(mp.get("actual_headcount"))],
        [3, "Planned Manhours", _num(mp.get("planned_manhours"))],
        [4, "Actual Manhours", _num(mp.get("actual_manhours"))],
    ]
    _grid_table(
        story,
        ["Sr. No.", "Designation / Category", "Quantity"],
        rows,
        styles,
        style_cfg,
        col_widths=[20 * mm, 100 * mm, 40 * mm],
    )
    return story


def render_labour_chart(snapshot, styles, style_cfg) -> list:
    from reportlab.platypus import Paragraph, Spacer

    if not _has_labour_chart(snapshot):
        return []
    story: list = []
    story.append(Paragraph("15. LABOUR MAN-DAY BAR CHART", styles["h1"]))
    hse = (snapshot.get("hse") or {}).get("record") or {}
    mp = snapshot.get("manpower") or {}
    values = {}
    if hse.get("man_days_worked") is not None:
        values["Man-Days Worked"] = float(hse["man_days_worked"] or 0)
    if hse.get("average_daily_manpower") is not None:
        values["Avg Daily Manpower"] = float(hse["average_daily_manpower"] or 0)
    if mp.get("actual_headcount") is not None:
        values["Actual Headcount"] = float(mp["actual_headcount"] or 0)
    if mp.get("planned_headcount") is not None:
        values["Planned Headcount"] = float(mp["planned_headcount"] or 0)
    chart = _bar_chart(
        list(values.keys()),
        {"Labour": list(values.values())},
        title="Labour / Manpower Summary",
        y_label="Nos",
    )
    if chart:
        story.append(chart)
    story.append(Spacer(1, 2))
    return story


def render_photographs(snapshot, styles, style_cfg) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, Spacer, Table

    story: list = []
    story.append(Paragraph("16. PHOTOGRAPHS", styles["h1"]))
    photos = (snapshot.get("site_photos") or {}).get("photos") or []
    if not photos:
        _na(story, styles, "Site photographs are not available for the reporting period.")
        return story

    cells = []
    for photo in photos:
        block = []
        img_buf = _fetch_image(photo.get("image_url") or "")
        if img_buf is not None:
            try:
                block.append(Image(img_buf, width=75 * mm, height=55 * mm, kind="proportional"))
            except Exception:
                block.append(Paragraph("(Image unavailable)", styles["muted"]))
        else:
            block.append(Paragraph("(Image unavailable)", styles["muted"]))
        caption = photo.get("title") or "Site Photograph"
        block.append(Paragraph(f"<b>{_s(caption)}</b>", styles["small_center"]))
        created = photo.get("created_at")
        if created:
            block.append(Paragraph(_s(_fmt_date(created)), styles["small_center"]))
        cells.append(block)

    # 2-column grid
    for i in range(0, len(cells), 2):
        left = cells[i]
        right = cells[i + 1] if i + 1 < len(cells) else [Paragraph("", styles["small"])]
        t = Table([[left, right]], colWidths=[90 * mm, 90 * mm])
        t.setStyle(_table_style(style_cfg, header=False))
        story.append(t)
        story.append(Spacer(1, 3 * mm))
    return story


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def render_pdf(
    snapshot: dict,
    *,
    meta: dict | None = None,
    config_overrides: dict | None = None,
) -> bytes:
    """Render MPR PDF bytes from snapshot_json only."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer

    meta = meta or {}
    cfg = get_mpr_report_config(config_overrides)
    style_cfg = get_mpr_style_config(cfg)
    styles = _styles(style_cfg)
    snapshot = snapshot or {}

    project = snapshot.get("project") or {}
    period = snapshot.get("reporting_period") or {}
    _, _, month_year = month_year_label(period)
    project_name = _plain(project.get("project_name"), "Project")
    consultant = _plain(cfg.get("consultant_name"), "SHRIKHANDE CONSULTANTS LIMITED")

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=f"MPR — {project_name} — {month_year}",
        author=consultant,
    )

    def _header_footer(canvas, doc_):
        canvas.saveState()
        page = canvas.getPageNumber()
        if page > 1:
            canvas.setFont("Times-Bold", 8)
            canvas.drawCentredString(
                A4[0] / 2, A4[1] - 10 * mm, project_name[:90]
            )
            canvas.setFont("Times-Roman", 8)
            canvas.drawCentredString(
                A4[0] / 2,
                A4[1] - 14 * mm,
                f"Monthly Progress Report — {month_year}",
            )
            canvas.setStrokeColorRGB(0, 0.45, 0.74)
            canvas.setLineWidth(0.6)
            canvas.line(15 * mm, A4[1] - 16 * mm, A4[0] - 15 * mm, A4[1] - 16 * mm)
            canvas.setFont("Times-Roman", 8)
            canvas.drawString(15 * mm, 10 * mm, consultant)
            canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {page}")
            canvas.setStrokeColorRGB(0.3, 0.3, 0.3)
            canvas.line(15 * mm, 13 * mm, A4[0] - 15 * mm, 13 * mm)
        canvas.restoreState()

    story: list = []
    story.extend(render_cover_page(snapshot, cfg, meta, styles, style_cfg))
    story.append(PageBreak())
    story.extend(render_index_page(styles, style_cfg, snapshot=snapshot))
    story.append(PageBreak())
    story.extend(render_executive_summary(snapshot, styles, style_cfg))
    story.append(Spacer(1, 4 * mm))
    story.extend(render_salient_features(snapshot, styles, style_cfg))
    story.append(Spacer(1, 4 * mm))
    story.extend(render_contractual_obligations(snapshot, styles, style_cfg))
    story.append(PageBreak())
    story.extend(render_progress_section(snapshot, styles, style_cfg))
    story.append(Spacer(1, 4 * mm))
    story.extend(render_quality(snapshot, styles, style_cfg))
    story.append(Spacer(1, 4 * mm))
    story.extend(render_bottlenecks(snapshot, styles, style_cfg))
    story.append(Spacer(1, 4 * mm))
    story.extend(render_next_month(snapshot, styles, style_cfg))
    story.append(Spacer(1, 4 * mm))
    story.extend(render_plant_machinery(snapshot, styles, style_cfg))
    lab = render_lab_equipment(snapshot, styles, style_cfg)
    if lab:
        story.append(Spacer(1, 4 * mm))
        story.extend(lab)
    story.append(PageBreak())
    story.extend(render_drawings(snapshot, styles, style_cfg))
    materials = render_materials(snapshot, styles, style_cfg)
    if materials:
        story.append(Spacer(1, 4 * mm))
        story.extend(materials)
    safety = render_safety(snapshot, styles, style_cfg)
    if safety:
        story.append(Spacer(1, 4 * mm))
        story.extend(safety)
    meetings = render_meetings(snapshot, styles, style_cfg)
    if meetings:
        story.append(Spacer(1, 4 * mm))
        story.extend(meetings)
    story.append(Spacer(1, 4 * mm))
    story.extend(render_manpower(snapshot, styles, style_cfg))
    labour = render_labour_chart(snapshot, styles, style_cfg)
    if labour:
        story.append(Spacer(1, 4 * mm))
        story.extend(labour)
    story.append(PageBreak())
    story.extend(render_photographs(snapshot, styles, style_cfg))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buffer.getvalue()
