"""
Drawing summary KPI calculations — computed at read time, never stored in DB.
"""


def compute_variance(submitted: int, approved: int) -> int:
    return int(submitted or 0) - int(approved or 0)


def compute_approval_rate(approved: int, submitted: int) -> float:
    submitted = int(submitted or 0)
    if submitted == 0:
        return 0.0
    return round((int(approved or 0) / submitted) * 100, 2)


def metrics_from_counts(submitted: int, approved: int) -> dict:
    submitted = int(submitted or 0)
    approved = int(approved or 0)
    return {
        "submitted_drawings": submitted,
        "approved_drawings": approved,
        "variance": compute_variance(submitted, approved),
        "approval_rate": compute_approval_rate(approved, submitted),
    }


def metrics_from_record(record) -> dict:
    if record is None:
        return metrics_from_counts(0, 0)
    return metrics_from_counts(
        record.submitted_drawings,
        record.approved_drawings,
    )


def monthly_response(record) -> dict:
    if record is None:
        return None
    return {
        "project_name": record.project_name,
        "month": record.month,
        "year": record.year,
        **metrics_from_record(record),
    }


def compact_metrics(record) -> dict:
    """Dashboard subset (same fields as monthly metrics)."""
    return metrics_from_record(record)
