from django.utils import timezone
from notifications.utils import send_websocket_notification, create_notification_message
from projects.models import Project
from accounts.models import UserProfile
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def notify_project_created(project):
    """
    Notify coordinators when a new project is created.

    WebSocket stays in-request; SMTP is queued after commit on the shared
    email ThreadPoolExecutor so project POST is not blocked by SMTP.
    """
    coordinators = list(project.coordinators.all())
    if not coordinators:
        logger.info("No coordinators assigned - no project creation notification sent")
        return

    recipient_ids = []
    for coord in coordinators:
        if not coord.email:
            continue
        ws_message = create_notification_message(
            "project_created",
            f"New Project: {project.name}",
            f'A new project "{project.name}" has been created and requires your attention.',
            {"project_id": project.id, "project_name": project.name},
        )
        send_websocket_notification(coord.id, ws_message)
        recipient_ids.append(coord.id)

    if not recipient_ids:
        logger.warning("No coordinators have email addresses")
        return

    from dpr.tasks import queue_after_commit

    queue_after_commit(
        send_project_created_email,
        project_id=project.id,
        recipient_ids=recipient_ids,
    )


def send_project_created_email(*, project_id: int, recipient_ids: list[int]) -> dict:
    """Background SMTP worker for project-created emails."""
    from django.contrib.auth import get_user_model

    from dpr.tasks import _dedup_key, run_background_smtp_job
    from projects.models import Project

    User = get_user_model()

    def _send():
        from services.email_utils import send_html_email

        project = Project.objects.filter(pk=project_id).select_related("created_by").first()
        if not project:
            return
        recipients = list(
            User.objects.filter(id__in=recipient_ids or [], is_active=True).exclude(email="")
        )
        emails = [u.email for u in recipients if u.email]
        if not emails:
            return
        created_by = project.created_by
        context = {
            "project": {
                "name": project.name,
                "client_name": project.client_name,
                "location": project.location,
                "description": project.description,
                "budget": float(project.budget or 0),
                "created_by": {
                    "username": created_by.username if created_by else "",
                    "get_full_name": created_by.get_full_name() if created_by else "",
                },
                "created_at": project.created_at.isoformat() if project.created_at else "",
            }
        }
        ok = send_html_email(
            subject=f"New Project Created: {project.name}",
            template_name="project_created",
            context=context,
            recipient_list=emails,
        )
        if not ok:
            raise RuntimeError("SMTP send_html_email returned failure template=project_created")
        logger.info(
            "Project creation email sent project_id=%s recipient_count=%s",
            project_id,
            len(emails),
        )

    return run_background_smtp_job(
        kind="project_created",
        dedup_key=_dedup_key("project_created", project_id, list(recipient_ids or [])),
        send_fn=_send,
    )


def notify_project_assigned(project, assigned_user):
    """
    Send notification when a user is assigned to a project.

    WebSocket stays synchronous; SMTP is queued after commit on the shared
    email ThreadPoolExecutor so assignment API latency is not blocked by SMTP.
    """
    # Send WebSocket notification immediately (in-request, non-SMTP).
    ws_message = create_notification_message(
        'project_assigned',
        f'Project Assigned: {project.name}',
        f'You have been assigned to the project "{project.name}".',
        {'project_id': project.id, 'project_name': project.name}
    )
    send_websocket_notification(assigned_user.id, ws_message)

    if not assigned_user.email:
        logger.warning(f"User {assigned_user.username} has no email address")
        return

    from dpr.tasks import queue_after_commit

    queue_after_commit(
        send_project_assigned_email,
        project_id=project.id,
        user_id=assigned_user.id,
    )


def send_project_assigned_email(*, project_id: int, user_id: int) -> dict:
    """Background SMTP worker for project assignment emails."""
    from django.contrib.auth import get_user_model

    from dpr.tasks import _dedup_key, run_background_smtp_job
    from projects.models import Project

    User = get_user_model()

    def _send():
        from services.email_utils import send_html_email

        try:
            project = Project.objects.only(
                "id", "name", "client_name", "location", "description"
            ).get(pk=project_id)
            assigned_user = User.objects.only(
                "id", "username", "email", "first_name", "last_name"
            ).get(pk=user_id)
        except Exception:
            logger.exception(
                "send_project_assigned_email load failed project_id=%s user_id=%s",
                project_id,
                user_id,
            )
            return

        if not assigned_user.email:
            return

        context = {
            "user": {
                "username": assigned_user.username,
                "get_full_name": assigned_user.get_full_name(),
                "email": assigned_user.email,
            },
            "project": {
                "name": project.name,
                "client_name": project.client_name,
                "location": project.location,
                "description": project.description,
            },
            "assignment_date": timezone.now().isoformat(),
        }
        ok = send_html_email(
            subject=f"Project Assignment: {project.name}",
            template_name="project_assigned",
            context=context,
            recipient_list=[assigned_user.email],
        )
        if not ok:
            raise RuntimeError("SMTP send_html_email returned failure template=project_assigned")

    return run_background_smtp_job(
        kind="project_assigned",
        dedup_key=_dedup_key("project_assigned", project_id, [user_id]),
        send_fn=_send,
    )


def notify_site_engineer_assigned(project, assigned_user):
    """
    Notify all site engineers when any site engineer is assigned.

    WebSocket stays in-request; SMTP is queued after commit on the shared
    email ThreadPoolExecutor.
    """
    site_engineers = []

    if project.billing_site_engineer and project.billing_site_engineer.email:
        site_engineers.append(project.billing_site_engineer)
    if project.qaqc_site_engineer and project.qaqc_site_engineer.email:
        site_engineers.append(project.qaqc_site_engineer)

    specific_ids = {se.id for se in site_engineers}
    for se in project.site_engineers.all():
        if se.email and se.id not in specific_ids:
            site_engineers.append(se)

    if not site_engineers:
        logger.warning(
            "No site engineers with email addresses found for project '%s'",
            project.name,
        )
        return

    for se in site_engineers:
        ws_message = create_notification_message(
            "site_engineer_assigned",
            f"Site Engineer Assigned: {project.name}",
            (
                f'{assigned_user.get_full_name()} has been assigned as a site '
                f'engineer to project "{project.name}".'
            ),
            {
                "project_id": project.id,
                "project_name": project.name,
                "assigned_user": assigned_user.username,
            },
        )
        send_websocket_notification(se.id, ws_message)

    recipient_ids = [se.id for se in site_engineers]
    from dpr.tasks import queue_after_commit

    queue_after_commit(
        send_site_engineer_assigned_email,
        project_id=project.id,
        assigned_user_id=assigned_user.id,
        recipient_ids=recipient_ids,
    )
    logger.info(
        "Site engineer assignment WS sent; email queued project=%s recipients=%s",
        project.name,
        recipient_ids,
    )


def send_site_engineer_assigned_email(
    *, project_id: int, assigned_user_id: int, recipient_ids: list[int]
) -> dict:
    """Background SMTP worker for site-engineer assignment emails."""
    from django.contrib.auth import get_user_model

    from dpr.tasks import _dedup_key, run_background_smtp_job
    from projects.models import Project

    User = get_user_model()

    def _send():
        from services.email_utils import send_html_email

        project = Project.objects.filter(pk=project_id).first()
        assigned_user = User.objects.filter(pk=assigned_user_id).first()
        if not project or not assigned_user:
            return
        recipients = list(
            User.objects.filter(id__in=recipient_ids or [], is_active=True).exclude(email="")
        )
        emails = [u.email for u in recipients if u.email]
        if not emails:
            return
        context = {
            "assigned_user": {
                "username": assigned_user.username,
                "get_full_name": assigned_user.get_full_name(),
            },
            "project": {
                "name": project.name,
                "client_name": project.client_name,
                "location": project.location,
                "description": project.description,
            },
            "assignment_date": timezone.now().isoformat(),
            "all_site_engineers": [
                {
                    "username": se.username,
                    "get_full_name": se.get_full_name(),
                }
                for se in recipients
            ],
        }
        ok = send_html_email(
            subject=f"Site Engineer Assigned: {project.name}",
            template_name="site_engineer_assigned",
            context=context,
            recipient_list=emails,
        )
        if not ok:
            raise RuntimeError(
                "SMTP send_html_email returned failure template=site_engineer_assigned"
            )

    return run_background_smtp_job(
        kind="site_engineer_assigned",
        dedup_key=_dedup_key(
            "site_engineer_assigned", project_id, list(recipient_ids or []), str(assigned_user_id)
        ),
        send_fn=_send,
    )

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
    elif approver_role in ('PMC Manager', 'Coordinator'):
        approvers.extend(list(project.coordinators.all()))

    # Filter to only those with email, log warning if role user has no email
    filtered = []
    for user in approvers:
        if user.email:
            filtered.append(user)
        else:
            logger.warning(
                f"User '{user.username}' is assigned as {approver_role} but has no email configured."
            )

    return filtered


def _get_dpr_notification_recipients(project, approver_role):
    """
    Get email recipients for DPR submission notifications.

    Prefers the specific approver role (Team Leader / Coordinator / PMC Head).
    Falls back to ANY assigned project leadership (team_lead + pmc_head + coordinators)
    so that emails are always sent to at least one role when a DPR is submitted,
    even if the exact workflow slot is not yet assigned on the project.
    """
    # Try exact role first
    specific = _get_project_approvers(project, approver_role)
    if specific:
        return specific

    # Fallback: any leadership on the project
    fallback = []
    if project.team_lead:
        fallback.append(project.team_lead)
    if project.pmc_head:
        fallback.append(project.pmc_head)
    fallback.extend(list(project.coordinators.all()))

    # Dedup + require email
    seen = set()
    recipients = []
    for user in fallback:
        if user.id not in seen and user.email:
            seen.add(user.id)
            recipients.append(user)

    if recipients:
        logger.info(
            f"No exact approver for role '{approver_role}' on '{project.name}'. "
            f"Falling back to {len(recipients)} leadership user(s)."
        )

    return recipients


def notify_dpr_submitted(dpr, *, is_resubmit: bool = False):
    """
    Notify next approver(s) when a DPR is submitted (or resubmitted).

    - WebSocket notifications: synchronous (immediate in-app)
    - SMTP email: ThreadPoolExecutor after DB transaction commit (no Celery worker)
    """
    from dpr.tasks import (
        queue_after_commit,
        send_dpr_resubmission_email,
        send_dpr_submission_email,
    )

    project_name_clean = (dpr.project_name or '').strip()
    project = Project.objects.filter(name__iexact=project_name_clean).first()
    if not project and project_name_clean:
        project = Project.objects.filter(name__icontains=project_name_clean).first()

    if not project:
        logger.error(f"Project '{dpr.project_name}' not found for DPR {dpr.id}")
        return

    approvers = _get_dpr_notification_recipients(project, dpr.current_approver_role)

    if not approvers:
        tl = project.team_lead
        pmc = project.pmc_head
        coords = list(project.coordinators.all())
        logger.warning(
            f"No recipients found for DPR submission notification. "
            f"Project: {project.name} | Role: {dpr.current_approver_role} | "
            f"team_lead={tl.username if tl else None} (email={tl.email if tl else None}) | "
            f"pmc_head={pmc.username if pmc else None} (email={pmc.email if pmc else None}) | "
            f"coordinators={[c.username for c in coords]}"
        )
        return

    recipient_emails = [user.email for user in approvers]
    recipient_ids = [user.id for user in approvers]
    dpr_id = dpr.id
    submitted_by_id = dpr.submitted_by_id

    logger.info(
        "DPR submitted successfully dpr_id=%s project=%s role=%s resubmit=%s recipients=%s",
        dpr_id,
        dpr.project_name,
        dpr.current_approver_role,
        is_resubmit,
        recipient_emails,
    )

    for approver in approvers:
        ws_message = create_notification_message(
            'dpr_submitted',
            f'DPR Submitted: {dpr.project_name}',
            f'A DPR has been submitted for your approval.',
            {'dpr_id': dpr.id, 'project_name': dpr.project_name, 'report_date': dpr.report_date.isoformat()}
        )
        send_websocket_notification(approver.id, ws_message)

    if dpr.submitted_by and dpr.submitted_by.email:
        submitter_ws_message = create_notification_message(
            'dpr_submitted',
            f'DPR Submitted: {dpr.project_name}',
            f'Your DPR has been submitted for approval.',
            {'dpr_id': dpr.id, 'project_name': dpr.project_name, 'status': 'submitted'}
        )
        send_websocket_notification(dpr.submitted_by.id, submitter_ws_message)

    task = send_dpr_resubmission_email if is_resubmit else send_dpr_submission_email
    logger.info(
        "Queued %s Email dpr_id=%s recipients=%s",
        "Resubmission" if is_resubmit else "Submission",
        dpr_id,
        recipient_ids,
    )
    queue_after_commit(
        task,
        dpr_id=dpr_id,
        submitted_by_id=submitted_by_id,
        recipient_ids=recipient_ids,
    )


def notify_dpr_approved_by_role(dpr, approved_by_role):
    """Approval notification. WebSocket sync; SMTP via thread pool after commit."""
    from dpr.tasks import approval_task_for_role, queue_after_commit

    project = Project.objects.filter(name=dpr.project_name).first()
    if not project:
        logger.error(f"Project '{dpr.project_name}' not found for DPR {dpr.id}")
        return

    recipients = []

    if approved_by_role == 'Team Leader':
        if dpr.submitted_by and dpr.submitted_by.email:
            recipients.append(dpr.submitted_by)
    elif approved_by_role in ('PMC Manager', 'Coordinator'):
        recipients.extend(_get_project_approvers(project, 'Team Leader'))
        if dpr.submitted_by and dpr.submitted_by.email:
            recipients.append(dpr.submitted_by)
    elif approved_by_role == 'PMC Head':
        recipients.extend(_get_project_approvers(project, 'PMC Manager'))
        recipients.extend(_get_project_approvers(project, 'Team Leader'))
        if dpr.submitted_by and dpr.submitted_by.email:
            recipients.append(dpr.submitted_by)

    recipients = list(set(recipients))
    recipient_emails = [user.email for user in recipients if user.email]
    recipient_ids = [user.id for user in recipients if user.email]

    if not recipient_emails:
        logger.warning(
            f"No recipients found for DPR approval notification (approved by {approved_by_role})"
        )
        return

    for recipient in recipients:
        if recipient.email in recipient_emails:
            ws_message = create_notification_message(
                'dpr_approved',
                f'DPR Approved: {dpr.project_name}',
                f'DPR has been approved by {approved_by_role}.',
                {'dpr_id': dpr.id, 'project_name': dpr.project_name, 'approved_by': approved_by_role}
            )
            send_websocket_notification(recipient.id, ws_message)

    task = approval_task_for_role(approved_by_role)
    logger.info(
        "Queued %s Approval Email dpr_id=%s recipients=%s",
        approved_by_role,
        dpr.id,
        recipient_ids,
    )
    queue_after_commit(task, dpr_id=dpr.id, recipient_ids=recipient_ids)


def notify_dpr_rejected_by_role(dpr, rejected_by_role):
    """Rejection notification. WebSocket sync; SMTP via thread pool after commit."""
    from dpr.tasks import queue_after_commit, send_dpr_rejection_email

    project = Project.objects.filter(name=dpr.project_name).first()
    if not project:
        logger.error(f"Project '{dpr.project_name}' not found for DPR {dpr.id}")
        return

    recipients = []

    if rejected_by_role == 'Team Leader':
        if dpr.submitted_by and dpr.submitted_by.email:
            recipients.append(dpr.submitted_by)
    elif rejected_by_role in ('PMC Manager', 'Coordinator'):
        recipients.extend(_get_project_approvers(project, 'Team Leader'))
        if dpr.submitted_by and dpr.submitted_by.email:
            recipients.append(dpr.submitted_by)
    elif rejected_by_role == 'PMC Head':
        recipients.extend(_get_project_approvers(project, 'PMC Manager'))
        recipients.extend(_get_project_approvers(project, 'Team Leader'))
        if dpr.submitted_by and dpr.submitted_by.email:
            recipients.append(dpr.submitted_by)

    recipients = list(set(recipients))
    recipient_emails = [user.email for user in recipients if user.email]
    recipient_ids = [user.id for user in recipients if user.email]

    if not recipient_emails:
        logger.warning(
            f"No recipients found for DPR rejection notification (rejected by {rejected_by_role})"
        )
        return

    for recipient in recipients:
        if recipient.email in recipient_emails:
            ws_message = create_notification_message(
                'dpr_rejected',
                f'DPR Rejected: {dpr.project_name}',
                f'DPR has been rejected by {rejected_by_role}. Please review the feedback.',
                {
                    'dpr_id': dpr.id,
                    'project_name': dpr.project_name,
                    'rejected_by': rejected_by_role,
                    'reason': dpr.rejection_reason,
                },
            )
            send_websocket_notification(recipient.id, ws_message)

    logger.info(
        "Queued Rejection Email dpr_id=%s role=%s recipients=%s",
        dpr.id,
        rejected_by_role,
        recipient_ids,
    )
    queue_after_commit(
        send_dpr_rejection_email,
        dpr_id=dpr.id,
        recipient_ids=recipient_ids,
        role=rejected_by_role,
    )


def notify_dpr_approved(dpr):
    """Legacy approve (submitter only). WebSocket sync; SMTP via thread pool after commit."""
    from dpr.tasks import queue_after_commit, send_dpr_approved_email

    if not dpr.submitted_by or not dpr.submitted_by.email:
        logger.warning(f"DPR {dpr.id} has no submitter or submitter has no email")
        return

    project = Project.objects.filter(name=dpr.project_name).first()
    if not project:
        logger.error(f"Project '{dpr.project_name}' not found for DPR {dpr.id}")
        return

    ws_message = create_notification_message(
        'dpr_approved',
        f'DPR Approved: {dpr.project_name}',
        f'Your DPR has been approved.',
        {
            'dpr_id': dpr.id,
            'project_name': dpr.project_name,
            'approved_by': dpr.approved_by.username if dpr.approved_by else None,
        },
    )
    send_websocket_notification(dpr.submitted_by.id, ws_message)

    logger.info(
        "Queued legacy Approval Email dpr_id=%s recipient=%s",
        dpr.id,
        dpr.submitted_by_id,
    )
    queue_after_commit(
        send_dpr_approved_email,
        dpr_id=dpr.id,
        recipient_ids=[dpr.submitted_by_id],
    )


def notify_dpr_rejected(dpr):
    """Legacy reject (submitter only). WebSocket sync; SMTP via thread pool after commit."""
    from dpr.tasks import queue_after_commit, send_dpr_rejected_email

    if not dpr.submitted_by or not dpr.submitted_by.email:
        logger.warning(f"DPR {dpr.id} has no submitter or submitter has no email")
        return

    project = Project.objects.filter(name=dpr.project_name).first()
    if not project:
        logger.error(f"Project '{dpr.project_name}' not found for DPR {dpr.id}")
        return

    ws_message = create_notification_message(
        'dpr_rejected',
        f'DPR Rejected: {dpr.project_name}',
        f'Your DPR has been rejected. Please review the feedback.',
        {
            'dpr_id': dpr.id,
            'project_name': dpr.project_name,
            'rejected_by': dpr.rejected_by.username if dpr.rejected_by else None,
            'reason': dpr.rejection_reason,
        },
    )
    send_websocket_notification(dpr.submitted_by.id, ws_message)

    logger.info(
        "Queued legacy Rejection Email dpr_id=%s recipient=%s",
        dpr.id,
        dpr.submitted_by_id,
    )
    queue_after_commit(
        send_dpr_rejected_email,
        dpr_id=dpr.id,
        recipient_ids=[dpr.submitted_by_id],
    )
