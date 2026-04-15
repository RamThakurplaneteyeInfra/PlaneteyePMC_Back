from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from .celery import app
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
        logger.info(f"Loading template: {template_path}")

        # Render the HTML content
        html_content = render_to_string(template_path, context)

        # Log first 200 chars of content for debugging
        logger.info(f"Email content preview: {html_content[:200]}...")

        # Send the email
        result = send_mail(
            subject=subject,
            message='',  # Plain text message (empty for HTML-only)
            html_message=html_content,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=False,
        )

        if result == 1:  # send_mail returns number of successfully sent emails
            logger.info(f"Email sent successfully to {recipient_list}")
            return True
        else:
            logger.error(f"Failed to send email to {recipient_list}")
            return False

    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")
        return False


@app.task
def send_notification_email(subject, template_name, context, recipient_list, from_email=None):
    """
    Celery task to send notification emails asynchronously.

    Args:
        subject (str): Email subject
        template_name (str): Template name (without .html extension)
        context (dict): Context variables for the template
        recipient_list (list): List of recipient email addresses
        from_email (str, optional): From email address

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"Sending email to {recipient_list} with template {template_name}")

        # Add base_url to context for absolute URLs in emails
        context = context.copy()
        context['base_url'] = settings.BASE_URL

        success = send_html_email(
            subject=subject,
            template_name=template_name,
            context=context,
            recipient_list=recipient_list,
            from_email=from_email
        )

        if success:
            logger.info(f"Email sent successfully to {recipient_list}")
            return True
        else:
            logger.error(f"Failed to send email to {recipient_list}")
            raise Exception("Email sending failed")

    except Exception as e:
        logger.error(f"Error in send_notification_email task: {str(e)}")
        raise  # Let Celery handle the retry