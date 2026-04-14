# Frontend Email Notification Integration Guide

## Overview
The backend includes an email notification system that automatically sends emails for various events in the application. Emails are sent asynchronously using Celery to avoid blocking the main application.

## Email Notification Types

### Project Notifications
- **Project Created**: Sent to coordinators when a new project is created
- **Project Assigned**: Sent to users when they are assigned to a project

### DPR (Daily Progress Report) Notifications
- **DPR Submitted**: Sent to approvers when a DPR is submitted for review
- **DPR Approved**: Sent to submitter when their DPR is approved
- **DPR Rejected**: Sent to submitter when their DPR is rejected with reasons

## Backend Email Implementation

### Email Configuration
Emails are configured using SMTP with the following settings:
- **Host**: smtp.gmail.com (configurable via EMAIL_HOST)
- **Port**: 587 (configurable via EMAIL_PORT)
- **TLS**: Enabled (configurable via EMAIL_USE_TLS)
- **Authentication**: Gmail App Password (not regular password)

### Asynchronous Sending
Emails are sent asynchronously using Celery:
```python
from django.core.mail import send_mail
from backend.celery import app

@app.task
def send_notification_email(subject, message, recipient_list):
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipient_list,
        fail_silently=False,
    )
```

### Email Templates
Emails use plain text format with structured content:
```
Subject: [PMC] DPR Approved - Project: {project_name}

Dear {user_name},

Your Daily Progress Report for {project_name} has been approved.

Details:
- Project: {project_name}
- Date: {date}
- Approved by: {approver_name}

Please continue with your work.

Best regards,
PMC System
```

## Frontend Integration Points

### Automatic Email Triggers
Emails are automatically sent by the backend when:
- Projects are created/assigned via API endpoints
- DPRs are submitted/approved/rejected via API endpoints

### Test Email Endpoint
For testing purposes, a test endpoint is available:

**Endpoint**: `POST /notifications/send-test-email/`

**Request**:
```json
{
  "email": "test@example.com",
  "type": "test"
}
```

**Response**:
```json
{
  "status": "Email sent successfully"
}
```

### Frontend Considerations

#### User Experience
- **Inform Users**: Let users know that email notifications will be sent for important actions
- **Email Preferences**: Consider adding user preferences for email notifications (future enhancement)
- **Confirmation Messages**: Show success messages when actions trigger emails

#### Error Handling
- **Network Issues**: If email service is down, operations still complete but emails may be delayed
- **Invalid Emails**: Backend validates email addresses before sending
- **Rate Limiting**: Gmail has sending limits; system handles queuing

#### Testing
- **Development**: Emails can be sent to test accounts during development
- **Production**: Monitor email delivery in production logs
- **Spam Filters**: Test emails may go to spam; check Gmail settings

## Email Content Structure

### Common Email Fields
All notification emails include:
- **Subject**: Prefixed with "[PMC]" and action type
- **Recipient**: User's registered email address
- **Sender**: Configured DEFAULT_FROM_EMAIL
- **Timestamp**: Included in email body
- **Context**: Project name, dates, and relevant details

### Email Templates by Type

#### Project Created
```
Subject: [PMC] New Project Created - {project_name}

A new project has been created and assigned to you.

Project Details:
- Name: {project_name}
- Description: {description}
- Start Date: {start_date}
- End Date: {end_date}

Please log in to the system for more details.
```

#### DPR Approved
```
Subject: [PMC] DPR Approved - Project: {project_name}

Your Daily Progress Report has been approved.

Report Details:
- Project: {project_name}
- Date: {report_date}
- Approved by: {approver_name}
- Comments: {approval_comments}

Continue with your project work.
```

#### DPR Rejected
```
Subject: [PMC] DPR Rejected - Project: {project_name}

Your Daily Progress Report requires revisions.

Report Details:
- Project: {project_name}
- Date: {report_date}
- Rejected by: {approver_name}
- Reason: {rejection_reason}
- Required Changes: {change_details}

Please update and resubmit your report.
```

## Technical Details

### Dependencies
- **Django**: Core email functionality
- **Celery**: Asynchronous task processing
- **Redis**: Message broker for Celery
- **Gmail SMTP**: Email delivery service

### Configuration
Email settings are configured in Django settings:
```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'your-email@gmail.com'
EMAIL_HOST_PASSWORD = 'your-app-password'
DEFAULT_FROM_EMAIL = 'your-email@gmail.com'
```

### Monitoring
- **Celery Logs**: Monitor worker logs for email sending status
- **Django Logs**: Check for email sending errors
- **Gmail Logs**: Monitor sent emails in Gmail sent folder

## Security Considerations

### Credentials
- Use Gmail App Passwords, not regular passwords
- Store credentials securely in environment variables
- Rotate passwords periodically

### Content Security
- Avoid sending sensitive data in emails
- Use HTTPS links in email content
- Validate all email addresses before sending

### Rate Limiting
- Gmail limits: 500 emails/day for free accounts
- Implement queuing for bulk notifications
- Monitor sending rates to avoid blocks

## Testing the Email System

### Manual Testing
1. Use the test endpoint to send emails to verified addresses
2. Trigger actual workflows (create project, submit DPR) to test automatic emails
3. Check email delivery in recipient inboxes
4. Verify email content formatting

### Integration Testing
1. Test with different email providers (Gmail, Outlook, etc.)
2. Verify emails arrive in inbox, not spam
3. Test with invalid email addresses
4. Check error handling when SMTP is unavailable

## Troubleshooting

### Common Issues
- **Emails not sending**: Check Celery worker is running
- **Authentication failed**: Verify Gmail App Password
- **Emails in spam**: Check email content and sender reputation
- **Rate limits**: Monitor sending frequency

### Logs to Check
- **Celery worker logs**: Email sending status
- **Django application logs**: Email task queuing
- **SMTP logs**: Connection and authentication status

## Future Enhancements

### Planned Features
- **HTML Email Templates**: Rich formatting with branding
- **Email Preferences**: User-controlled notification settings
- **Email Analytics**: Delivery and open tracking
- **Bulk Notifications**: Efficient sending to multiple recipients
- **Email Templates**: Configurable templates per notification type

This email system provides reliable notification delivery for your application. The frontend team should be aware of the automatic email triggers and can use the test endpoint for development purposes.