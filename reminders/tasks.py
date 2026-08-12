from celery import shared_task


@shared_task(name="reminders.dispatch_due_reminders")
def dispatch_due_reminders_task(limit: int = 500) -> dict:
    """Periodic Celery entrypoint for due reminder notifications."""
    from reminders.services import dispatch_due_reminders

    return dispatch_due_reminders(limit=limit)
