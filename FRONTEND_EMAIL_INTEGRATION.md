# Frontend Email Notification Integration Guide

## Overview
The backend includes an email notification system that automatically sends emails for various events in the application. Emails are sent asynchronously using Celery to avoid blocking the main application.

### DPR Approval Workflow
The DPR (Daily Progress Report) follows a specific approval workflow with targeted email notifications:

1. **Site Engineer** submits DPR → Email sent to **Team Lead**
2. **Team Lead** approves → Email sent to **Site Engineer** + DPR sent to **Coordinator**
3. **Coordinator** approves → Email sent to **Team Lead** + **Site Engineer** + DPR sent to **PMC Head**
4. **PMC Head** approves → Email sent to **Coordinator** + **Team Lead** + **Site Engineer**

Rejections work similarly but send emails to all relevant parties in the reverse direction with rejection reasons.

## Email Notification Types

### Project Notifications
- **Project Created**: Sent to coordinators when a new project is created
- **Project Assigned**: Sent to users when they are assigned to a project
- **Team Lead Assigned**: Sent to team lead when assigned to a project
- **Site Engineer Assigned**: Sent to all site engineers when any site engineer is assigned to a project

### DPR (Daily Progress Report) Notifications
- **DPR Submitted**: Sent to the next approver in the workflow (Team Lead → Coordinator → PMC Head)
- **DPR Approved**: Sent to appropriate recipients based on approval stage:
  - Team Lead approval → Site Engineer (submitter)
  - Coordinator approval → Team Lead + Site Engineer
  - PMC Head approval → Coordinator + Team Lead + Site Engineer
- **DPR Rejected**: Sent to appropriate recipients based on rejection stage:
  - Team Lead rejection → Site Engineer (submitter)
  - Coordinator rejection → Team Lead + Site Engineer
  - PMC Head rejection → Coordinator + Team Lead + Site Engineer

### Test Notifications
- **Test Email**: Manual test emails for development and debugging
- **Synchronous Test Email**: Immediate email sending without Celery queue

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

### Notification API Endpoints
For triggering email notifications manually, use these specific endpoints. All endpoints are located under `/notifications/` and accept JSON POST requests.

#### 1. Test Email Endpoint
**Endpoint**: `POST /notifications/send-test-email/`

**Request Body**:
```json
{
  "email": "test@example.com",
  "type": "test"
}
```

**Response** (Success):
```json
{
  "status": "Email sent successfully"
}
```

**Response** (Error):
```json
{
  "error": "Method not allowed"
}
```

#### 2. Synchronous Test Email Endpoint
**Endpoint**: `POST /notifications/test-sync-email/`

**Request Body**: None required

**Response** (Success):
```json
{
  "status": "Sync email sent successfully"
}
```

**Response** (Error):
```json
{
  "error": "Failed to send sync email"
}
```

#### 3. Project Created Notification
**Endpoint**: `POST /notifications/project-created/`

**Request Body**:
```json
{
  "project_id": 456
}
```

**Response** (Success):
```json
{
  "status": "Project creation notification sent successfully"
}
```

**Response** (Error):
```json
{
  "error": "project_id is required"
}
```
```json
{
  "error": "Project not found"
}
```

#### 4. Team Lead Assigned Notification
**Endpoint**: `POST /notifications/team-lead-assigned/`

**Request Body**:
```json
{
  "project_id": 456,
  "user_id": 123
}
```

**Response** (Success):
```json
{
  "status": "Team Leader assignment notification sent successfully"
}
```

**Response** (Error):
```json
{
  "error": "project_id is required"
}
```
```json
{
  "error": "user_id is required"
}
```
```json
{
  "error": "Assigned user is not a Team Leader"
}
```

#### 5. Site Engineer Assigned Notification
**Endpoint**: `POST /notifications/site-engineer-assigned/`

**Request Body**:
```json
{
  "project_id": 456,
  "user_id": 123
}
```

**Response** (Success):
```json
{
  "status": "Site Engineer assignment notification sent successfully"
}
```

**Response** (Error):
```json
{
  "error": "project_id is required"
}
```
```json
{
  "error": "user_id is required"
}
```
```json
{
  "error": "Assigned user is not a Site Engineer type"
}
```

#### 6. DPR Submitted Notification
**Endpoint**: `POST /notifications/dpr-submitted/`

**Request Body**:
```json
{
  "dpr_id": 123
}
```

**Response** (Success):
```json
{
  "status": "DPR submission notification sent successfully"
}
```

**Response** (Error):
```json
{
  "error": "dpr_id is required"
}
```
```json
{
  "error": "DPR not found"
}
```

#### 7. DPR Approved Notification
**Endpoint**: `POST /notifications/dpr-approved/`

**Request Body**:
```json
{
  "dpr_id": 123
}
```

**Response** (Success):
```json
{
  "status": "DPR approval notification sent successfully"
}
```

**Response** (Error):
```json
{
  "error": "dpr_id is required"
}
```
```json
{
  "error": "DPR not found"
}
```

#### 8. DPR Rejected Notification
**Endpoint**: `POST /notifications/dpr-rejected/`

**Request Body**:
```json
{
  "dpr_id": 123
}
```

**Response** (Success):
```json
{
  "status": "DPR rejection notification sent successfully"
}
```

**Response** (Error):
```json
{
  "error": "dpr_id is required"
}
```
```json
{
  "error": "DPR not found"
}
```

### Frontend Integration
Call the appropriate endpoint from the frontend after successful actions:

```javascript
// Test email sending
fetch('/notifications/send-test-email/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: 'test@example.com', type: 'test' })
});

// Synchronous test email (without Celery)
fetch('/notifications/test-sync-email/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' }
});

// After project creation
fetch('/notifications/project-created/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ project_id: projectId })
});

// After team lead assignment
fetch('/notifications/team-lead-assigned/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ project_id: projectId, user_id: userId })
});

// After site engineer assignment
fetch('/notifications/site-engineer-assigned/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ project_id: projectId, user_id: userId })
});

// After DPR submission
fetch('/notifications/dpr-submitted/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ dpr_id: dprId })
});

// After DPR approval
fetch('/notifications/dpr-approved/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ dpr_id: dprId })
});

// After DPR rejection
fetch('/notifications/dpr-rejected/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ dpr_id: dprId })
});
```

These endpoints ensure emails are sent to the respective authorities when specific actions occur.

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

#### Team Lead Assigned
```
Subject: [PMC] Project Assignment: {project_name}

You have been assigned as the Team Leader for the following project:

Project Details:
- Name: {project_name}
- Client: {project_client}
- Location: {project_location}
- Assigned Date: {assignment_date}

Please review the project details and coordinate with your team.
```

#### Site Engineer Assigned
```
Subject: [PMC] Site Engineer Assigned: {project_name}

A new site engineer has been assigned to the following project:

Project Details:
- Name: {project_name}
- Client: {project_client}
- Location: {project_location}
- Assigned Engineer: {assigned_user_name}
- Assignment Date: {assignment_date}

All Site Engineers on this Project:
{list_of_all_site_engineers}

Please coordinate with the assigned engineer and ensure smooth project execution.
```

#### Test Email
```
Subject: [PMC] Test Email - {email_type}

This is a test email notification.

Details:
- Type: {email_type}
- Timestamp: {timestamp}

This email confirms that the notification system is working correctly.
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

### Test Users
The following test users have been created for email notification testing:

**Team Lead:**
- Username: `test_team_lead`
- Password: `Project@123`
- Email: `ahiresandesh4@gmail.com`
- Role: Team Leader

**Site Engineer:**
- Username: `test_site_engineer`
- Password: `Project@123`
- Email: `sanchitahire191@gmail.com`
- Role: Site Engineer

### System Users with Email
**Production Users:**
- Username: `pmc_tl`
- Password: Not set (use admin panel)
- Email: `rudrajoshi072004@gmail.com`
- Role: Team Leader

- Username: `pmc_coordinator`
- Email: `sandeshahire1630@gmail.com`
- Role: Coordinator

**Site Engineer Users:**
- Username: `pmc_bse`
- Email: `sandeshahire146@gmail.com`
- Role: Billing Site Engineer

- Username: `pmc_qaqc`
- Email: `sandeshtravels2004@gmail.com`
- Role: QAQC Site Engineer

- Username: `pmc_se`
- Email: `sanchitahire191@gmail.com`
- Role: Site Engineer

### Manual Testing
1. Use the test endpoints (`/notifications/send-test-email/` or `/notifications/test-sync-email/`) to send emails to verified addresses
2. Trigger actual workflows (create project, submit DPR) to test automatic emails
3. Check email delivery in recipient inboxes
4. Verify email content formatting

### Postman Collection
Import `notifications/postman_collection.json` into Postman for comprehensive testing of all notification endpoints. The collection includes:
- Pre-configured requests for all notification endpoints
- Sample data for testing
- Proper headers and request formats

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