import logging
import mimetypes
from email.mime.image import MIMEImage
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

LOGO_CONTENT_ID = "pmc-brand-logo"


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


def _attach_inline_logo(message: EmailMultiAlternatives) -> bool:
    """Attach the configured brand logo as a CID image for email clients."""
    logo_path = Path(getattr(settings, "EMAIL_LOGO_PATH", "") or "")
    if not logo_path.is_file():
        logger.warning("Email logo not found path=%s", logo_path)
        return False

    content_type, _ = mimetypes.guess_type(logo_path.name)
    subtype = (content_type or "image/jpeg").split("/", 1)[-1]
    image = MIMEImage(logo_path.read_bytes(), _subtype=subtype)
    image.add_header("Content-ID", f"<{LOGO_CONTENT_ID}>")
    image.add_header(
        "Content-Disposition",
        "inline",
        filename=logo_path.name,
    )
    message.attach(image)
    return True


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

        render_context = dict(context or {})
        render_context.setdefault("email_logo_cid", f"cid:{LOGO_CONTENT_ID}")
        html_content = render_to_string(template_path, render_context)
        text_content = strip_tags(html_content)

        timeout = _smtp_timeout_seconds()
        connection = get_connection(timeout=timeout)

        message = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=recipient_list,
            connection=connection,
        )
        message.attach_alternative(html_content, "text/html")
        _attach_inline_logo(message)
        result = message.send(fail_silently=False)

        if result == 1:
            logger.info(f"Email sent successfully to {recipient_list}")
            return True
        else:
            logger.error(f"Failed to send email to {recipient_list}")
            return False

    except Exception as e:
        logger.error(f"Error sending email to {recipient_list}: {str(e)}")
        return False
