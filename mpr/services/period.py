"""Reporting-period helpers for MPR (YYYY-MM)."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class InvalidMPRMonth(ValueError):
    """Raised when month query param is not YYYY-MM."""


@dataclass(frozen=True)
class MPRPeriod:
    year: int
    month: int
    month_key: str  # YYYY-MM
    start_date: date
    end_date: date
    month_year_abbr: str  # Jan-2026 (manpower/cashflow/cost)

    @property
    def reporting_period(self) -> dict:
        return {
            "month": self.month_key,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
        }


def parse_mpr_month(value: str | None) -> MPRPeriod:
    raw = (value or "").strip()
    match = _MONTH_RE.match(raw)
    if not match:
        raise InvalidMPRMonth(
            "month query parameter is required and must be YYYY-MM (e.g. 2026-07)."
        )
    year = int(match.group(1))
    month = int(match.group(2))
    if year < 2000 or year > 2100:
        raise InvalidMPRMonth("month year must be between 2000 and 2100.")
    last_day = calendar.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, last_day)
    abbr = start.strftime("%b-%Y")
    return MPRPeriod(
        year=year,
        month=month,
        month_key=f"{year:04d}-{month:02d}",
        start_date=start,
        end_date=end,
        month_year_abbr=abbr,
    )
