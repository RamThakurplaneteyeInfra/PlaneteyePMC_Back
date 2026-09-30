import logging

from django.conf import settings

from .models import OrganizationRegistration

logger = logging.getLogger(__name__)


def notify_organization_registration(registration) -> bool:
    """
    Email PlanetEye about a new onboarding request.

    The recipient is configured by the backend, never by submitted form data.
    """
    try:
        recipient = getattr(settings, "ORG_REGISTRATION_NOTIFY_EMAIL", "").strip()
        if not recipient:
            logger.error(
                "Organization registration email not sent id=%s reason=missing_recipient",
                registration.pk,
            )
            return False
        if getattr(settings, "EMAIL_TRANSPORT", "").strip().lower() == "disabled":
            logger.error(
                "Organization registration email not sent id=%s reason=transport_disabled",
                registration.pk,
            )
            return False
        if not getattr(settings, "EMAIL_TRANSPORT", "").strip() and not getattr(
            settings, "DPR_EMAIL_ENABLED", True
        ):
            logger.error(
                "Organization registration email not sent id=%s reason=transport_disabled",
                registration.pk,
            )
            return False
        from_email = (
            getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""
        ).strip() or recipient
        logo_name = registration.logo_original_name or (
            registration.logo.name.rsplit("/", 1)[-1] if registration.logo else ""
        )
        from services.email_utils import send_html_email

        sent = send_html_email(
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
        if not sent:
            logger.warning(
                "Organization registration email not sent id=%s reason=provider_rejected",
                registration.pk,
            )
            return False
        logger.info(
            "Organization registration email queued recipient=%s id=%s",
            recipient,
            getattr(registration, "pk", None),
        )
        return True
    except Exception as exc:
        logger.error(
            "Failed to email PlanetEye about organization registration id=%s error_type=%s",
            getattr(registration, "pk", None),
            type(exc).__name__,
        )
        return False


def attempt_organization_registration_notification(registration) -> bool:
    """Persist a retryable delivery result without deleting the registration."""
    registration.notification_status = OrganizationRegistration.NOTIFICATION_PENDING
    registration.save(update_fields=["notification_status"])

    sent = notify_organization_registration(registration)
    registration.notification_status = (
        OrganizationRegistration.NOTIFICATION_SENT
        if sent
        else OrganizationRegistration.NOTIFICATION_FAILED
    )
    registration.save(update_fields=["notification_status"])
    return sent
