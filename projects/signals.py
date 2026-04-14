from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from .models import Project
from services.notifications import notify_project_assigned


@receiver(m2m_changed, sender=Project.assigned_users.through)
def project_assigned_users_changed(sender, instance, action, reverse, model, pk_set, **kwargs):
    """
    Signal handler for when users are added to or removed from project.assigned_users.
    """
    if action == 'post_add' and pk_set:
        # Users were added to assigned_users
        for user_id in pk_set:
            try:
                user = model.objects.get(pk=user_id)
                notify_project_assigned(instance, user)
            except model.DoesNotExist:
                pass  # User doesn't exist, skip