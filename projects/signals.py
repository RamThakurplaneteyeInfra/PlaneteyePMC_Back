from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from .models import Project
from services.notifications import notify_project_assigned


@receiver(m2m_changed, sender=Project.assigned_users.through)
def project_assigned_users_changed(sender, instance, action, reverse, model, pk_set, **kwargs):
    """
    Signal handler for when users are added to or removed from project.assigned_users.
    """
    if action == "post_add" and pk_set:
        for user_id in pk_set:
            try:
                user = model.objects.get(pk=user_id)
                notify_project_assigned(instance, user)
            except model.DoesNotExist:
                pass

    if action in {"post_add", "post_remove", "post_clear"}:
        from projects.services.project_overview import invalidate_project_overview_cache

        invalidate_project_overview_cache()


@receiver(m2m_changed, sender=Project.site_engineers.through)
def project_site_engineers_changed(sender, action, **kwargs):
    if action in {"post_add", "post_remove", "post_clear"}:
        from projects.services.project_overview import invalidate_project_overview_cache

        invalidate_project_overview_cache()


@receiver(post_save, sender=Project)
@receiver(post_delete, sender=Project)
def invalidate_overview_on_project_change(sender, **kwargs):
    from projects.services.project_overview import invalidate_project_overview_cache

    invalidate_project_overview_cache()


def _invalidate_overview(*_args, **_kwargs):
    from projects.services.project_overview import invalidate_project_overview_cache

    invalidate_project_overview_cache()


def connect_overview_invalidation_signals():
    """Subscribe to KPI source models without importing them at module import time."""
    from bottlenecks.models import Bottleneck
    from construction_progress.models.construction_progress import ConstructionProgress
    from cost_performance.models import ProjectCostPerformance
    from dpr.models import DailyProgressReport
    from health_safety.models import HSERecord
    from project_quality_status.models.project_quality_status import ProjectQualityStatus

    for model in (
        ConstructionProgress,
        ProjectCostPerformance,
        ProjectQualityStatus,
        HSERecord,
        Bottleneck,
        DailyProgressReport,
    ):
        post_save.connect(_invalidate_overview, sender=model, weak=False)
        post_delete.connect(_invalidate_overview, sender=model, weak=False)


connect_overview_invalidation_signals()
