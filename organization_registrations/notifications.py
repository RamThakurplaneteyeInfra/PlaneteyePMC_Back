import logging

from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_NOTIFY_EMAIL = "planetedevm@gmail.com"


def notify_organization_registration(registration) -> None:
    """
    Email PlanetEye about a new onboarding request.

    Must never raise — email failure cannot fail the public API.
    """
    try:
        recipient = (
            getattr(settings, "ORGANIZATION_REGISTRATION_NOTIFY_EMAIL", "") or DEFAULT_NOTIFY_EMAIL
        ).strip() or DEFAULT_NOTIFY_EMAIL
        from_email = (
            getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""
        ).strip() or DEFAULT_NOTIFY_EMAIL
        logo_name = registration.logo_original_name or (
            registration.logo.name.rsplit("/", 1)[-1] if registration.logo else ""
        )
        from services.email_utils import send_html_email

        send_html_email(
            subject=f"New organization registration: {registration.display_name}",
            template_name="organization_registration_submitted",
            context={
                "registration": registration,
                "logo_filename": logo_name,
                "logo_url": registration.logo_public_url(),
            },
            recipient_list=[recipient],
            from_email=from_email,
        )
        logger.info(
            "Organization registration email queued recipient=%s id=%s",
            recipient,
            getattr(registration, "pk", None),
        )
    except Exception:
        logger.exception(
            "Failed to email PlanetEye about organization registration id=%s",
            getattr(registration, "pk", None),
        )
