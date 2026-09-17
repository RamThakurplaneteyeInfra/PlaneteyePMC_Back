"""
MPR PDF presentation settings (SCL branding).

Values come from Django settings.MPR_REPORT_CONFIG (env-overridable defaults).
No database fields required.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings

# Extracted from client reference DOCX (Shrikhande Consultants logo asset).
SCL_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "scl_logo.jpeg"

DEFAULT_MPR_REPORT_CONFIG: dict[str, Any] = {
    "consultant_name": "SHRIKHANDE CONSULTANTS LIMITED",
    "consultant_short_name": "SCL",
    "consultant_tagline": "Project Management Consultants",
    "consultant_address": [
        "Office No. 2012 – 2013, 2nd Floor,",
        "Akshar Business Park Wing – D,",
        "Plot No. 3, Sector – 25, Near APMC,",
        "Vashi, Navi Mumbai – 400 703",
    ],
    "consultant_phone": "Tel. No.: (022) 2784 4440 / 3305 / 4199",
    "consultant_email": "E-mail: scplvashi@gmail.com",
    "consultant_web": "Web: www.scplasia.com",
    "logo_path": str(SCL_LOGO_PATH),
    # Brand colours from SCL logo
    "primary_brand_color": "#0072BC",
    "secondary_brand_color": "#4DB87E",
    "border_color": "#333333",
    "header_bg_color": "#F2F2F2",
    # Legacy keys retained for backward compatibility (unused by PDF body)
    "reference_prefix": "SCPL/SITE/",
    "recipient_designation": "",
    "recipient_organization": "",
    "recipient_address": [],
    "signatory_designation": "",
    "signatory_title": "",
    "salutation": "",
}


@dataclass(frozen=True)
class MPRStyleConfig:
    """Centralized typography / colour tokens for the engineering MPR PDF."""

    font_family: str = "Times-Roman"
    heading_font: str = "Times-Bold"
    body_font: str = "Times-Roman"
    cover_title_size: float = 18
    cover_subtitle_size: float = 14
    heading1_size: float = 12
    heading2_size: float = 11
    body_size: float = 10
    table_font_size: float = 8.5
    line_spacing: float = 13
    primary_brand_color: str = "#0072BC"
    secondary_brand_color: str = "#4DB87E"
    border_color: str = "#333333"
    header_bg_color: str = "#F2F2F2"
    header_spacing: float = 8
    footer_spacing: float = 8


def get_mpr_report_config(overrides: dict | None = None) -> dict[str, Any]:
    """Merge defaults ← settings.MPR_REPORT_CONFIG ← optional overrides."""
    cfg = deepcopy(DEFAULT_MPR_REPORT_CONFIG)
    configured = getattr(settings, "MPR_REPORT_CONFIG", None) or {}
    if isinstance(configured, dict):
        cfg.update({k: v for k, v in configured.items() if v is not None})
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})
    addr = cfg.get("consultant_address") or []
    if isinstance(addr, str):
        cfg["consultant_address"] = [
            line.strip() for line in addr.splitlines() if line.strip()
        ]
    legacy_addr = cfg.get("recipient_address") or []
    if isinstance(legacy_addr, str):
        cfg["recipient_address"] = [
            line.strip() for line in legacy_addr.splitlines() if line.strip()
        ]
    if not cfg.get("logo_path"):
        cfg["logo_path"] = str(SCL_LOGO_PATH)
    return cfg


def get_mpr_style_config(report_cfg: dict | None = None) -> MPRStyleConfig:
    cfg = report_cfg or get_mpr_report_config()
    return MPRStyleConfig(
        primary_brand_color=str(cfg.get("primary_brand_color") or "#0072BC"),
        secondary_brand_color=str(cfg.get("secondary_brand_color") or "#4DB87E"),
        border_color=str(cfg.get("border_color") or "#333333"),
        header_bg_color=str(cfg.get("header_bg_color") or "#F2F2F2"),
    )


def build_reference_number(config: dict, project: dict | None = None) -> str:
    """Legacy helper retained for tests / callers; not used on the MPR cover."""
    prefix = str(config.get("reference_prefix") or "SCPL/SITE/").strip()
    if not prefix.endswith("/"):
        prefix = prefix + "/"
    code = ""
    if isinstance(project, dict):
        code = (project.get("project_code") or "").strip()
    if code:
        return f"{prefix}{code}/"
    return prefix


def month_year_label(period: dict | None) -> tuple[str, int | None, str]:
    """
    Return (MonthName, year, 'MonthName Year') from reporting_period.month YYYY-MM.
    """
    import calendar

    period = period or {}
    month_key = period.get("month") or ""
    try:
        year_s, month_s = str(month_key).split("-", 1)
        year = int(year_s)
        month = int(month_s)
        name = calendar.month_name[month]
        return name, year, f"{name} {year}"
    except Exception:
        return "Unknown", None, "Unknown"


def resolve_logo_path(config: dict | None = None) -> Path | None:
    cfg = config or get_mpr_report_config()
    path = Path(str(cfg.get("logo_path") or SCL_LOGO_PATH))
    if path.is_file():
        return path
    if SCL_LOGO_PATH.is_file():
        return SCL_LOGO_PATH
    return None
