from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def send_html_email(subject, template_name, context, recipient_list, from_email=None):
    """
    Send an HTML email using a Django template.
    """
    try:
        if from_email is None:
            from_email = settings.DEFAULT_FROM_EMAIL

        template_path = f'emails/{template_name}.html'
        logger.debug(f"Rendering email template: {template_path}")

        html_content = render_to_string(template_path, context)

        result = send_mail(
            subject=subject,
            message='',
            html_message=html_content,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=False,
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