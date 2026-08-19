import logging
import mimetypes
import smtplib
from email.mime.image import MIMEImage
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

LOGO_CONTENT_ID = "pmc-brand-logo"

_PERMANENT_SMTP_ERRORS = (
    smtplib.SMTPAuthenticationError,
    smtplib.SMTPSenderRefused,
    smtplib.SMTPRecipientsRefused,
)


def is_retryable_smtp_error(exc: BaseException) -> bool:
    """Transient network/4xx SMTP errors may retry; auth and 5xx must not."""
    if isinstance(exc, _PERMANENT_SMTP_ERRORS):
        return False
    if isinstance(exc, smtplib.SMTPResponseException):
        code = int(getattr(exc, "smtp_code", 0) or 0)
        return 400 <= code < 500
    if isinstance(
        exc,
        (
            TimeoutError,
            ConnectionError,
            BrokenPipeError,
            OSError,
            smtplib.SMTPServerDisconnected,
            smtplib.SMTPConnectError,
        ),
    ):
        return True
    # Unknown errors (including RuntimeError from a False SMTP result): retry
    # within the bounded attempt cap, not forever.
    return True


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


def _normalize_recipient_list(recipient_list) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in recipient_list or []:
        email = item.strip() if isinstance(item, str) else str(item or "").strip()
        if not email:
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(email)
    return out


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
    Raises SMTP/network exceptions so callers can classify retry vs permanent.
    """
    recipients = _normalize_recipient_list(recipient_list)
    recipient_count = len(recipients)
    if not recipients:
        logger.warning("send_html_email skipped template=%s recipient_count=0", template_name)
        return False

    connection = None
    try:
        if from_email is None:
            from_email = settings.DEFAULT_FROM_EMAIL

        template_path = f"emails/{template_name}.html"
        logger.debug("Rendering email template: %s", template_path)

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
            to=recipients,
            connection=connection,
        )
        message.attach_alternative(html_content, "text/html")
        _attach_inline_logo(message)
        result = message.send(fail_silently=False)

        if result >= 1:
            logger.info(
                "Email sent successfully template=%s recipient_count=%s",
                template_name,
                recipient_count,
            )
            return True
        logger.error(
            "Failed to send email template=%s recipient_count=%s result=%s",
            template_name,
            recipient_count,
            result,
        )
        return False

    except Exception as exc:
        logger.error(
            "Error sending email template=%s recipient_count=%s err_type=%s",
            template_name,
            recipient_count,
            type(exc).__name__,
        )
        raise
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                logger.debug("SMTP connection close failed template=%s", template_name)
