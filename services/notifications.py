from django.utils import timezone
from backend.tasks import send_notification_email
from notifications.utils import send_websocket_notification, create_notification_message
from projects.models import Project
from accounts.models import UserProfile
import logging

logger = logging.getLogger(__name__)


def notify_project_created(project):
    """
    Send notification when a new project is created.
    Sends to coordinators for awareness.

    Args:
        project (Project): The newly created project instance
    """
    # Get all coordinators for the project
    coordinators = list(project.coordinators.all())

    if coordinators:
        recipient_emails = [coord.email for coord in coordinators if coord.email]

        if recipient_emails:
            context = {
                'project': {
                    'name': project.name,
                    'client_name': project.client_name,
                    'location': project.location,
                    'description': project.description,
                    'budget': float(project.budget),
                    'created_by': {
                        'username': project.created_by.username,
                        'get_full_name': project.created_by.get_full_name(),
                    },
                    'created_at': project.created_at.isoformat(),
                }
            }

            send_notification_email.delay(
                subject=f"New Project Created: {project.name}",
                template_name='project_created',
                context=context,
                recipient_list=recipient_emails
            )

            # Send WebSocket notifications to coordinators
            for coord in coordinators:
                if coord.email in recipient_emails:
                    ws_message = create_notification_message(
                        'project_created',
                        f'New Project: {project.name}',
                        f'A new project "{project.name}" has been created and requires your attention.',
                        {'project_id': project.id, 'project_name': project.name}
                    )
                    send_websocket_notification(coord.id, ws_message)

            logger.info(f"Project creation notification sent to coordinators: {recipient_emails}")
        else:
            logger.warning("No coordinators have email addresses")
    else:
        logger.info("No coordinators assigned - no project creation notification sent")


def notify_project_assigned(project, assigned_user):
    """
    Send notification when a user is assigned to a project.

    Args:
        project (Project): The project instance
        assigned_user (User): The user who was assigned
    """
    if not assigned_user.email:
        logger.warning(f"User {assigned_user.username} has no email address")
        return

    context = {
        'user': {
            'username': assigned_user.username,
            'get_full_name': assigned_user.get_full_name(),
            'email': assigned_user.email,
        },
        'project': {
            'name': project.name,
            'client_name': project.client_name,
            'location': project.location,
            'description': project.description,
        },
        'assignment_date': timezone.now().isoformat(),
    }

    send_notification_email.delay(
        subject=f"Project Assignment: {project.name}",
        template_name='project_assigned',
        context=context,
        recipient_list=[assigned_user.email]
    )

    # Send WebSocket notification to the assigned user
    ws_message = create_notification_message(
        'project_assigned',
        f'Project Assigned: {project.name}',
        f'You have been assigned to the project "{project.name}".',
        {'project_id': project.id, 'project_name': project.name}
    )
    send_websocket_notification(assigned_user.id, ws_message)


def _get_project_approvers(project, approver_role):
    """
    Get users who should approve based on the role and project.

    Args:
        project (Project): The project instance
        approver_role (str): The role that should approve

    Returns:
        list: List of User objects
    """
    approvers = []

    if approver_role == 'Team Leader' and project.team_lead:
        approvers.append(project.team_lead)
    elif approver_role == 'PMC Head' and project.pmc_head:
        approvers.append(project.pmc_head)
    elif approver_role == 'Coordinator':
        # Send to all coordinators
        approvers.extend(list(project.coordinators.all()))

    return [user for user in approvers if user.email]


def notify_dpr_submitted(dpr):
    """
    Send notification when a DPR is submitted for approval.

    Args:
        dpr (DailyProgressReport): The DPR instance
    """
    # Find the project by name (since DPR uses project_name as string)
    try:
        project = Project.objects.get(name=dpr.project_name)
    except Project.DoesNotExist:
        logger.error(f"Project '{dpr.project_name}' not found for DPR {dpr.id}")
        return

    # Get approvers based on current_approver_role
    approvers = _get_project_approvers(project, dpr.current_approver_role)

    if not approvers:
        logger.warning(f"No approvers found for role '{dpr.current_approver_role}' on project '{project.name}'")
        return

    recipient_emails = [user.email for user in approvers]

    context = {
        'dpr': {
            'project_name': dpr.project_name,
            'report_date': dpr.report_date.isoformat(),
            'job_no': dpr.job_no,
            'issued_by': dpr.issued_by,
            'designation': dpr.designation,
            'submitted_by': {
                'username': dpr.submitted_by.username,
                'get_full_name': dpr.submitted_by.get_full_name(),
            }
        },
        'project': {
            'name': project.name,
            'client_name': project.client_name,
            'location': project.location,
        },
        'approver': {
            'username': approvers[0].username,
            'get_full_name': approvers[0].get_full_name(),
        } if approvers else None,
    }

    send_notification_email.delay(
        subject=f"DPR Submitted for Approval: {dpr.project_name} - {dpr.report_date}",
        template_name='dpr_submitted',
        context=context,
        recipient_list=recipient_emails
    )

    # Send WebSocket notifications to approvers
    for approver in approvers:
        ws_message = create_notification_message(
            'dpr_submitted',
            f'DPR Submitted: {dpr.project_name}',
            f'A DPR has been submitted for your approval.',
            {'dpr_id': dpr.id, 'project_name': dpr.project_name, 'report_date': dpr.report_date.isoformat()}
        )
        send_websocket_notification(approver.id, ws_message)


def notify_dpr_approved(dpr):
    """
    Send notification when a DPR is approved.

    Args:
        dpr (DailyProgressReport): The DPR instance
    """
    if not dpr.submitted_by or not dpr.submitted_by.email:
        logger.warning(f"DPR {dpr.id} has no submitter or submitter has no email")
        return

    # Find the project
    try:
        project = Project.objects.get(name=dpr.project_name)
    except Project.DoesNotExist:
        logger.error(f"Project '{dpr.project_name}' not found for DPR {dpr.id}")
        return

    context = {
        'dpr': {
            'project_name': dpr.project_name,
            'report_date': dpr.report_date.isoformat(),
            'job_no': dpr.job_no,
            'status': 'Approved',
            'approved_by': {
                'username': dpr.approved_by.username,
                'get_full_name': dpr.approved_by.get_full_name(),
            },
            'approved_at': dpr.approved_at.isoformat() if dpr.approved_at else None,
        },
        'project': {
            'name': project.name,
        },
        'submitter': {
            'username': dpr.submitted_by.username,
            'get_full_name': dpr.submitted_by.get_full_name(),
        },
    }

    send_notification_email.delay(
        subject=f"DPR Approved: {dpr.project_name} - {dpr.report_date}",
        template_name='dpr_approved',
        context=context,
        recipient_list=[dpr.submitted_by.email]
    )

    # Send WebSocket notification to submitter
    ws_message = create_notification_message(
        'dpr_approved',
        f'DPR Approved: {dpr.project_name}',
        f'Your DPR has been approved.',
        {'dpr_id': dpr.id, 'project_name': dpr.project_name, 'approved_by': dpr.approved_by.username}
    )
    send_websocket_notification(dpr.submitted_by.id, ws_message)


def notify_dpr_rejected(dpr):
    """
    Send notification when a DPR is rejected.

    Args:
        dpr (DailyProgressReport): The DPR instance
    """
    if not dpr.submitted_by or not dpr.submitted_by.email:
        logger.warning(f"DPR {dpr.id} has no submitter or submitter has no email")
        return

    # Find the project
    try:
        project = Project.objects.get(name=dpr.project_name)
    except Project.DoesNotExist:
        logger.error(f"Project '{dpr.project_name}' not found for DPR {dpr.id}")
        return

    context = {
        'dpr': {
            'project_name': dpr.project_name,
            'report_date': dpr.report_date.isoformat(),
            'job_no': dpr.job_no,
            'status': 'Rejected',
            'rejected_by': {
                'username': dpr.rejected_by.username,
                'get_full_name': dpr.rejected_by.get_full_name(),
            },
            'rejection_reason': dpr.rejection_reason,
        },
        'project': {
            'name': project.name,
        },
        'submitter': {
            'username': dpr.submitted_by.username,
            'get_full_name': dpr.submitted_by.get_full_name(),
        },
    }

    send_notification_email.delay(
        subject=f"DPR Rejected: {dpr.project_name} - {dpr.report_date}",
        template_name='dpr_rejected',
        context=context,
        recipient_list=[dpr.submitted_by.email]
    )

    # Send WebSocket notification to submitter
    ws_message = create_notification_message(
        'dpr_rejected',
        f'DPR Rejected: {dpr.project_name}',
        f'Your DPR has been rejected. Please review the feedback.',
        {'dpr_id': dpr.id, 'project_name': dpr.project_name, 'rejected_by': dpr.rejected_by.username, 'reason': dpr.rejection_reason}
    )
    send_websocket_notification(dpr.submitted_by.id, ws_message)