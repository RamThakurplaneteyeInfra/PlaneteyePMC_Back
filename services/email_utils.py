import base64
import json
import logging
import mimetypes
import re
import smtplib
import urllib.error
import urllib.request
from email.mime.image import MIMEImage
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template import engines
from django.template.loader import get_template, render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

LOGO_CONTENT_ID = "pmc-brand-logo"
_BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

# Formatters sometimes wrap long Django tags across lines, which leaves raw
# ``{{`` / ``{%`` in the rendered HTML and Brevo rejects / fails delivery.
_DJANGO_TAG_RE = re.compile(r"(\{\{.*?\}\}|\{%.*?%\})", re.DOTALL)


def _collapse_multiline_django_tags(source: str) -> str:
    """Collapse whitespace inside Django tags so multiline tags still parse."""

    def _one_line(match: re.Match) -> str:
        return re.sub(r"\s+", " ", match.group(0))

    return _DJANGO_TAG_RE.sub(_one_line, source or "")


def _render_email_html(template_name: str, context: dict) -> str:
    """
    Render ``emails/<template_name>.html`` with a safety net for multiline tags.

    Prefer the normal loader; if the on-disk source contains multiline tags,
    re-render from a collapsed copy so delivery is not blocked by formatting.
    """
    template_path = f"emails/{template_name}.html"
    try:
        tpl = get_template(template_path)
        origin = getattr(tpl, "origin", None)
        source_path = getattr(origin, "name", None) if origin else None
        if source_path:
            raw = Path(source_path).read_text(encoding="utf-8")
            repaired = _collapse_multiline_django_tags(raw)
            if repaired != raw:
                logger.warning(
                    "Email template had multiline Django tags; auto-collapsed "
                    "template=%s path=%s",
                    template_name,
                    source_path,
                )
                return engines["django"].from_string(repaired).render(context)
    except Exception:
        logger.exception(
            "Email template repair path failed template=%s; falling back to loader",
            template_name,
        )
    return render_to_string(template_path, context)

_PERMANENT_SMTP_ERRORS = (
    smtplib.SMTPAuthenticationError,
    smtplib.SMTPSenderRefused,
    smtplib.SMTPRecipientsRefused,
)


class BrevoAPIError(Exception):
    """Raised when Brevo transactional API rejects or fails a send."""

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = True):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def is_retryable_smtp_error(exc: BaseException) -> bool:
    """Transient network/4xx SMTP/API errors may retry; auth and permanent must not."""
    if isinstance(exc, BrevoAPIError):
        return bool(exc.retryable)
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
            urllib.error.URLError,
        ),
    ):
        return True
    # Unknown errors (including RuntimeError from a False SMTP result): retry
    # within the bounded attempt cap, not forever.
    return True


def _smtp_timeout_seconds() -> float:
    """Blocking SMTP/API timeout (connect + read)."""
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


def _email_enabled() -> bool:
    return bool(getattr(settings, "DPR_EMAIL_ENABLED", True))


def _email_transport() -> str:
    """
    Resolve transport:
    - disabled: no-op success for callers that only care about non-blocking notify
    - brevo_api: HTTP transactional API (preferred when xkeysib key is set)
    - smtp: Django SMTP backend (Brevo SMTP relay / locmem in tests)
    """
    forced = (getattr(settings, "EMAIL_TRANSPORT", "") or "").strip().lower()
    if forced in {"brevo_api", "smtp", "disabled"}:
        return forced
    if not _email_enabled():
        return "disabled"
    api_key = (getattr(settings, "BREVO_API_KEY", "") or "").strip()
    if api_key.startswith("xkeysib-"):
        return "brevo_api"
    return "smtp"


def _logo_path() -> Path:
    configured = Path(getattr(settings, "EMAIL_LOGO_PATH", "") or "")
    if configured.is_file():
        return configured
    fallback = Path(settings.BASE_DIR) / "mpr" / "assets" / "email_scl_logo.png"
    if fallback.is_file():
        return fallback
    legacy = Path(settings.BASE_DIR) / "mpr" / "assets" / "scl_logo.jpeg"
    return legacy


def _logo_public_url() -> str:
    return (getattr(settings, "EMAIL_LOGO_URL", "") or "").strip()


def _attach_inline_logo(message: EmailMultiAlternatives) -> bool:
    """Attach the configured brand logo as a CID image for SMTP clients."""
    if _logo_public_url():
        # Prefer hosted HTTPS logo in HTML; skip CID when URL is available.
        return False
    logo_path = _logo_path()
    if not logo_path.is_file():
        logger.warning("Email logo not found path=%s", logo_path)
        return False

    content_type, _ = mimetypes.guess_type(logo_path.name)
    subtype = (content_type or "image/png").split("/", 1)[-1]
    image = MIMEImage(logo_path.read_bytes(), _subtype=subtype)
    image.add_header("Content-ID", f"<{LOGO_CONTENT_ID}>")
    image.add_header(
        "Content-Disposition",
        "inline",
        filename=logo_path.name,
    )
    message.attach(image)
    return True


def _logo_attachment_payload() -> dict | None:
    """CID attachment for Brevo only when no public logo URL is configured."""
    if _logo_public_url():
        return None
    logo_path = _logo_path()
    if not logo_path.is_file():
        logger.warning("Email logo not found path=%s", logo_path)
        return None
    return {
        "name": logo_path.name,
        "content": base64.b64encode(logo_path.read_bytes()).decode("ascii"),
        "contentId": LOGO_CONTENT_ID,
    }


def _resolve_logo_src() -> tuple[str, str]:
    """
    Returns (context_key_value_for_url, context_key_value_for_cid_compat).
    Prefer public HTTPS URL for Outlook/webmail reliability.
    """
    public_url = _logo_public_url()
    if public_url:
        return public_url, public_url
    return "", f"cid:{LOGO_CONTENT_ID}"


def _send_via_brevo_api(
    *,
    subject: str,
    html_content: str,
    text_content: str,
    recipients: list[str],
    from_email: str,
) -> bool:
    api_key = (getattr(settings, "BREVO_API_KEY", "") or "").strip()
    if not api_key:
        raise BrevoAPIError("BREVO_API_KEY is not configured", status_code=None, retryable=False)

    sender_name = (getattr(settings, "BREVO_FROM_NAME", "") or "").strip() or "PMC"
    payload: dict = {
        "sender": {"name": sender_name, "email": from_email},
        "to": [{"email": email} for email in recipients],
        "subject": subject,
        "htmlContent": html_content,
        "textContent": text_content,
    }
    logo = _logo_attachment_payload()
    if logo:
        payload["attachment"] = [logo]

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        _BREVO_API_URL,
        data=body,
        method="POST",
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": api_key,
        },
    )
    timeout = _smtp_timeout_seconds()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200) or 200
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        status = int(exc.code or 0)
        retryable = status in {408, 425, 429} or status >= 500
        raise BrevoAPIError(
            f"Brevo API HTTP {status}",
            status_code=status,
            retryable=retryable,
        ) from None
    except urllib.error.URLError as exc:
        raise BrevoAPIError(
            f"Brevo API network error: {type(exc.reason).__name__ if exc.reason else 'URLError'}",
            status_code=None,
            retryable=True,
        ) from exc

    if status >= 400:
        raise BrevoAPIError(
            f"Brevo API HTTP {status}",
            status_code=status,
            retryable=status >= 500,
        )

    message_id = None
    try:
        message_id = (json.loads(raw) or {}).get("messageId")
    except Exception:
        message_id = None
    logger.info(
        "Email sent via Brevo API recipient_count=%s message_id=%s",
        len(recipients),
        message_id or "unknown",
    )
    return True


def _send_via_smtp(
    *,
    subject: str,
    html_content: str,
    text_content: str,
    recipients: list[str],
    from_email: str,
    template_name: str,
) -> bool:
    connection = None
    try:
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
                "Email sent via SMTP template=%s recipient_count=%s",
                template_name,
                len(recipients),
            )
            return True
        logger.error(
            "Failed to send SMTP email template=%s recipient_count=%s result=%s",
            template_name,
            len(recipients),
            result,
        )
        return False
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                logger.debug("SMTP connection close failed template=%s", template_name)


def send_html_email(subject, template_name, context, recipient_list, from_email=None):
    """
    Send an HTML email using a Django template.

    Prefer Brevo transactional API when BREVO_API_KEY is an xkeysib key.
    Otherwise use Django SMTP (Brevo relay). EMAIL_TIMEOUT applies to both.
    """
    recipients = _normalize_recipient_list(recipient_list)
    recipient_count = len(recipients)
    if not recipients:
        logger.warning("send_html_email skipped template=%s recipient_count=0", template_name)
        return False

    transport = _email_transport()
    if transport == "disabled":
        logger.info(
            "send_html_email disabled template=%s recipient_count=%s",
            template_name,
            recipient_count,
        )
        return True

    try:
        if from_email is None:
            from_email = settings.DEFAULT_FROM_EMAIL

        template_path = f"emails/{template_name}.html"
        logger.debug("Rendering email template: %s", template_path)

        render_context = dict(context or {})
        logo_url, logo_cid = _resolve_logo_src()
        render_context.setdefault("email_logo_url", logo_url)
        render_context.setdefault("email_logo_cid", logo_cid or logo_url)
        html_content = _render_email_html(template_name, render_context)
        text_content = strip_tags(html_content)

        # Brevo re-parses htmlContent; leftover Django markers cause silent delivery errors.
        if "{{" in html_content or "{%" in html_content:
            raise RuntimeError(
                f"Rendered email still contains template markers template={template_name}"
            )

        if transport == "brevo_api":
            return _send_via_brevo_api(
                subject=subject,
                html_content=html_content,
                text_content=text_content,
                recipients=recipients,
                from_email=from_email,
            )

        return _send_via_smtp(
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            recipients=recipients,
            from_email=from_email,
            template_name=template_name,
        )

    except Exception as exc:
        logger.error(
            "Error sending email template=%s recipient_count=%s transport=%s err_type=%s",
            template_name,
            recipient_count,
            transport,
            type(exc).__name__,
        )
        raise
