"""
Correspondence KPI calculations — computed at read time, never stored in DB.
"""


def compute_pending_correspondence(received: int, delivered: int) -> int:
    return max(int(received or 0) - int(delivered or 0), 0)


def compute_delivery_efficiency(delivered: int, received: int) -> float:
    received = int(received or 0)
    if received == 0:
        return 0.0
    return round((int(delivered or 0) / received) * 100, 2)


def metrics_from_counts(received: int, delivered: int) -> dict:
    received = int(received or 0)
    delivered = int(delivered or 0)
    return {
        "correspondence_received": received,
        "correspondence_delivered": delivered,
        "pending_correspondence": compute_pending_correspondence(received, delivered),
        "delivery_efficiency": compute_delivery_efficiency(delivered, received),
    }


def metrics_from_record(record) -> dict:
    if record is None:
        return metrics_from_counts(0, 0)
    return metrics_from_counts(
        record.correspondence_received,
        record.correspondence_delivered,
    )


def monthly_type_response(record) -> dict:
    if record is None:
        return metrics_from_counts(0, 0)
    return metrics_from_record(record)


def monthly_full_response(project_name: str, month: int, year: int, client, contractor) -> dict:
    return {
        "project_name": project_name,
        "month": month,
        "year": year,
        "client": monthly_type_response(client),
        "contractor": monthly_type_response(contractor),
    }


def dual_type_summary(project_name: str, client_metrics: dict, contractor_metrics: dict, **extra) -> dict:
    return {
        "project_name": project_name,
        **extra,
        "client": client_metrics,
        "contractor": contractor_metrics,
    }
