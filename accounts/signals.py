"""
Signals to automatically create UserProfile when User is created.
"""
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    """
    Ensure every User has exactly one UserProfile.

    Uses get_or_create so Django admin (User + UserProfile inline) does not
    raise IntegrityError / 500 when both the signal and the inline try to
    create a profile for a new user.
    """
    UserProfile.objects.get_or_create(user=instance)
