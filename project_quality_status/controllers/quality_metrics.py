"""
Quality KPI calculations — computed at read time, never stored in DB.
"""


def compute_shortfall(tests_required: int, tests_conducted: int) -> int:
    return max(int(tests_required or 0) - int(tests_conducted or 0), 0)


def compute_quality_performance(tests_passed: int, tests_conducted: int) -> float:
    conducted = int(tests_conducted or 0)
    if conducted == 0:
        return 0.0
    return round((int(tests_passed or 0) / conducted) * 100, 2)


def compute_pass_rate(tests_passed: int, tests_required: int) -> float:
    required = int(tests_required or 0)
    if required == 0:
        return 0.0
    return round((int(tests_passed or 0) / required) * 100, 2)


def compute_fail_rate(tests_failed: int, tests_conducted: int) -> float:
    conducted = int(tests_conducted or 0)
    if conducted == 0:
        return 0.0
    return round((int(tests_failed or 0) / conducted) * 100, 2)


def quality_status_from_performance(pct: float) -> str:
    """
    Dashboard quality badge bands (shared by serializers + overview).
      >= 95 → excellent
      >= 80 → good
      >= 60 → average
      < 60  → poor
    """
    value = float(pct or 0)
    if value >= 95:
        return "excellent"
    if value >= 80:
        return "good"
    if value >= 60:
        return "average"
    return "poor"


def metrics_from_counts(
    tests_required: int,
    tests_conducted: int,
    tests_passed: int,
    tests_failed: int,
    *,
    include_rates: bool = True,
) -> dict:
    """Build dashboard/monthly metrics dict from raw counts."""
    tests_required = int(tests_required or 0)
    tests_conducted = int(tests_conducted or 0)
    tests_passed = int(tests_passed or 0)
    tests_failed = int(tests_failed or 0)

    data = {
        "tests_required": tests_required,
        "tests_conducted": tests_conducted,
        "shortfall": compute_shortfall(tests_required, tests_conducted),
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "quality_performance": compute_quality_performance(
            tests_passed, tests_conducted
        ),
    }

    if include_rates:
        data["pass_rate"] = compute_pass_rate(tests_passed, tests_required)
        data["fail_rate"] = compute_fail_rate(tests_failed, tests_conducted)

    return data


def metrics_from_record(record, *, include_rates: bool = True) -> dict:
    if record is None:
        return metrics_from_counts(0, 0, 0, 0, include_rates=include_rates)
    return metrics_from_counts(
        record.tests_required,
        record.tests_conducted,
        record.tests_passed,
        record.tests_failed,
        include_rates=include_rates,
    )


def monthly_response(record) -> dict:
    """Full monthly endpoint payload."""
    if record is None:
        return None
    data = metrics_from_record(record, include_rates=True)
    return {
        "project_name": record.projectName,
        "month": record.month,
        "year": record.year,
        **data,
    }


def dashboard_response(record) -> dict:
    """Compact dashboard payload (subset of metrics)."""
    if record is None:
        return metrics_from_counts(0, 0, 0, 0, include_rates=False)
    return metrics_from_record(record, include_rates=False)
