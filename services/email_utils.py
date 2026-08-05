from django.core.mail import get_connection, send_mail
from django.template.loader import render_to_string
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def _smtp_timeout_seconds() -> float | None:
    """Blocking SMTP timeout (connect + read). None = Django default (no timeout)."""
    raw = getattr(settings, "EMAIL_TIMEOUT", None)
    if raw is None or raw == "":
        return 30.0
    try:
        value = float(raw)
        return value if value > 0 else 30.0
    except (TypeError, ValueError):
        return 30.0


def send_html_email(subject, template_name, context, recipient_list, from_email=None):
    """
    Send an HTML email using a Django template.

    Uses EMAIL_TIMEOUT so worker threads cannot block indefinitely on SMTP.
    """
    try:
        if from_email is None:
            from_email = settings.DEFAULT_FROM_EMAIL

        template_path = f'emails/{template_name}.html'
        logger.debug(f"Rendering email template: {template_path}")

        html_content = render_to_string(template_path, context)

        timeout = _smtp_timeout_seconds()
        connection = get_connection(timeout=timeout)

        result = send_mail(
            subject=subject,
            message='',
            html_message=html_content,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=False,
            connection=connection,
        )

        if result == 1:
            logger.info(f"Email sent successfully to {recipient_list}")
            return True
        else:
            logger.error(f"Failed to send email to {recipient_list}")
            return False

    except Exception as e:
        logger.error(f"Error sending email to {recipient_list}: {str(e)}")
        return False
