from django.shortcuts import render
from django.http import JsonResponse
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
from datetime import datetime
from functools import wraps
from django.core.mail import send_mail
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication
from services.notifications import notify_dpr_submitted, notify_dpr_approved, notify_dpr_rejected, notify_project_created, notify_project_assigned, notify_site_engineer_assigned
from dpr.models import DailyProgressReport
from projects.models import Project
from django.contrib.auth.models import User
from accounts.rbac import is_admin_user


class IsStaffOrAdminRole(BasePermission):
    """Staff/superuser or PMC admin roles (CEO / PMC Head / PMC Manager)."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return bool(
            user.is_staff
            or user.is_superuser
            or is_admin_user(user)
        )


def _authenticate_jwt_if_needed(request):
    """Attach JWT user on plain Django views (Bearer token)."""
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return user
    try:
        result = JWTAuthentication().authenticate(request)
        if result:
            request.user = result[0]
            return result[0]
    except Exception:
        pass
    return None


def admin_required(view_func):
    """
    Protect notification test/debug helpers.
    Accepts session or JWT; requires staff/superuser or PMC admin role.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = _authenticate_jwt_if_needed(request)
        if not user or not user.is_authenticated:
            return JsonResponse(
                {"detail": "Authentication credentials were not provided."},
                status=401,
            )
        if not (
            user.is_staff
            or user.is_superuser
            or is_admin_user(user)
        ):
            return JsonResponse(
                {"detail": "You do not have permission to perform this action."},
                status=403,
            )
        return view_func(request, *args, **kwargs)

    return _wrapped


@admin_required
def notifications_test(request):
    """
    Test page for real-time notifications via WebSocket
    """
    return render(request, 'notifications_test.html')


@admin_required
def send_test_notification(request):
    """
    Send a test notification to the test group
    """
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        'test_notifications',
        {
            'type': 'notification_message',
            'message': json.dumps({
                'type': 'test',
                'title': 'Test Notification',
                'message': 'This is a test WebSocket notification!',
                'timestamp': datetime.now().isoformat() + 'Z',
                'data': {'test': True}
            })
        }
    )
    return JsonResponse({'status': 'Notification sent'})


@admin_required
def send_test_email(request):
    """
    Send a test email notification
    """
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        email = data.get('email')
        email_type = data.get('type', 'test')

        subject = f"[PMC] Test Email - {email_type.title()}"
        message = f"This is a test email notification.\n\nType: {email_type}\nTimestamp: {datetime.now().isoformat()}"

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
            return JsonResponse({'status': 'Email sent successfully'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsStaffOrAdminRole])
def test_sync_email(request):
    """
    Test email sending synchronously (without Celery)
    """
    try:
        from backend.tasks import send_html_email

        context = {
            'test_message': 'This is a synchronous test email',
            'timestamp': datetime.now().isoformat(),
            'base_url': settings.BASE_URL
        }

        success = send_html_email(
            subject="[PMC] Sync Test Email",
            template_name='project_created',
            context=context,
            recipient_list=['sandeshahire840@gmail.com'],  # Test recipient
            from_email=settings.DEFAULT_FROM_EMAIL
        )

        if success:
            return JsonResponse({'status': 'Sync email sent successfully'})
        else:
            return JsonResponse({'error': 'Failed to send sync email'}, status=500)

    except Exception as e:
        return JsonResponse({'error': f'Sync email failed: {str(e)}'}, status=500)


@api_view(['POST'])
def notify_project_created_endpoint(request):
    """
    Send email notification when a project is created.

    Expected request body:
    {
        "project_id": 456
    }
    """
    try:
        project_id = request.data.get('project_id')

        if not project_id:
            return Response(
                {'error': 'project_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            return Response(
                {'error': 'Project not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Temporarily make notification synchronous for testing
        from backend.tasks import send_html_email
        from django.conf import settings

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
                    },
                    'base_url': settings.BASE_URL
                }

                success = send_html_email(
                    subject=f"New Project Created: {project.name}",
                    template_name='project_created',
                    context=context,
                    recipient_list=recipient_emails,
                    from_email=settings.DEFAULT_FROM_EMAIL
                )

                if success:
                    return Response(
                        {'status': 'Project creation notification sent successfully'},
                        status=status.HTTP_200_OK
                    )
                else:
                    return Response(
                        {'error': 'Failed to send project creation notification'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

        return Response(
            {'status': 'Project creation notification sent successfully (no coordinators with email)'},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return Response(
            {'error': f'Failed to send notification: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def notify_dpr_submitted_endpoint(request):
    """
    Send email notification when a DPR is submitted.

    Expected request body:
    {
        "dpr_id": 123
    }
    """
    try:
        dpr_id = request.data.get('dpr_id')

        if not dpr_id:
            return Response(
                {'error': 'dpr_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            dpr = DailyProgressReport.objects.get(id=dpr_id)
        except DailyProgressReport.DoesNotExist:
            return Response(
                {'error': 'DPR not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        notify_dpr_submitted(dpr)

        return Response(
            {'status': 'DPR submission notification sent successfully'},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return Response(
            {'error': f'Failed to send notification: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def notify_dpr_approved_endpoint(request):
    """
    Send email notification when a DPR is approved.

    Expected request body:
    {
        "dpr_id": 123
    }
    """
    try:
        dpr_id = request.data.get('dpr_id')

        if not dpr_id:
            return Response(
                {'error': 'dpr_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            dpr = DailyProgressReport.objects.get(id=dpr_id)
        except DailyProgressReport.DoesNotExist:
            return Response(
                {'error': 'DPR not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        notify_dpr_approved(dpr)

        return Response(
            {'status': 'DPR approval notification sent successfully'},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return Response(
            {'error': f'Failed to send notification: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def notify_dpr_rejected_endpoint(request):
    """
    Send email notification when a DPR is rejected.

    Expected request body:
    {
        "dpr_id": 123
    }
    """
    try:
        dpr_id = request.data.get('dpr_id')

        if not dpr_id:
            return Response(
                {'error': 'dpr_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            dpr = DailyProgressReport.objects.get(id=dpr_id)
        except DailyProgressReport.DoesNotExist:
            return Response(
                {'error': 'DPR not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        notify_dpr_rejected(dpr)

        return Response(
            {'status': 'DPR rejection notification sent successfully'},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return Response(
            {'error': f'Failed to send notification: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def notify_team_lead_assigned_endpoint(request):
    """
    Send email notification when a Team Leader is assigned to a project.

    Expected request body:
    {
        "project_id": 456,
        "user_id": 123
    }
    """
    try:
        project_id = request.data.get('project_id')
        user_id = request.data.get('user_id')

        if not project_id:
            return Response(
                {'error': 'project_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            return Response(
                {'error': 'Project not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            assigned_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if user is actually a Team Leader
        if not assigned_user.groups.filter(name='Team Leader').exists():
            return Response(
                {'error': 'Assigned user is not a Team Leader'},
                status=status.HTTP_400_BAD_REQUEST
            )

        notify_project_assigned(project, assigned_user)

        return Response(
            {'status': 'Team Leader assignment notification sent successfully'},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return Response(
            {'error': f'Failed to send notification: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def notify_site_engineer_assigned_endpoint(request):
    """
    Send email notification when a Site Engineer is assigned to a project.

    Expected request body:
    {
        "project_id": 456,
        "user_id": 123
    }
    """
    try:
        project_id = request.data.get('project_id')
        user_id = request.data.get('user_id')

        if not project_id:
            return Response(
                {'error': 'project_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            return Response(
                {'error': 'Project not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            assigned_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if user is a Site Engineer type
        site_engineer_groups = ['Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer']
        if not any(assigned_user.groups.filter(name=group).exists() for group in site_engineer_groups):
            return Response(
                {'error': 'Assigned user is not a Site Engineer type'},
                status=status.HTTP_400_BAD_REQUEST
            )

        notify_site_engineer_assigned(project, assigned_user)

        return Response(
            {'status': 'Site Engineer assignment notification sent successfully'},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return Response(
            {'error': f'Failed to send notification: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def chrome_notification_endpoint(request):
    """
    Unified Chrome notification endpoint for all notification types.

    Expected request body:
    {
        "type": "project_created" | "project_assigned" | "site_engineer_assigned" | "dpr_submitted" | "dpr_approved" | "dpr_rejected",
        "project_id": 456,  // Required for project-related notifications
        "user_id": 123,     // Required for assignment notifications
        "dpr_id": 789       // Required for DPR notifications
    }

    Notification Logic:
    - project_created: PMC Head creates project → Notify PMC Managers
    - project_assigned: PMC Manager assigns to Team Leader → Notify that Team Leader only
    - site_engineer_assigned: Team Leader assigns to Site Engineers → Notify specific site engineer types
    - dpr_submitted: Site Engineer submits DPR → Notify current approver role
    - dpr_approved: DPR approved → Notify relevant users based on approver role
    - dpr_rejected: DPR rejected → Notify relevant users based on approver role
    """
    try:
        notification_type = request.data.get('type')
        project_id = request.data.get('project_id')
        user_id = request.data.get('user_id')
        dpr_id = request.data.get('dpr_id')

        if not notification_type:
            return Response(
                {'error': 'type is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Handle project creation notification
        if notification_type == 'project_created':
            if not project_id:
                return Response(
                    {'error': 'project_id is required for project_created notifications'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                project = Project.objects.get(id=project_id)
            except Project.DoesNotExist:
                return Response(
                    {'error': 'Project not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            notify_project_created(project)
            return Response(
                {'status': 'Project creation Chrome notification sent successfully'},
                status=status.HTTP_200_OK
            )

        # Handle project assignment notifications
        elif notification_type == 'project_assigned':
            if not project_id or not user_id:
                return Response(
                    {'error': 'project_id and user_id are required for project_assigned notifications'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                project = Project.objects.get(id=project_id)
            except Project.DoesNotExist:
                return Response(
                    {'error': 'Project not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            try:
                assigned_user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check user role and call appropriate notification function
            if assigned_user.groups.filter(name='Team Leader').exists():
                notify_project_assigned(project, assigned_user)
                return Response(
                    {'status': 'Team Leader assignment Chrome notification sent successfully'},
                    status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {'error': 'Assigned user is not a Team Leader'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Handle site engineer assignment notifications
        elif notification_type == 'site_engineer_assigned':
            if not project_id or not user_id:
                return Response(
                    {'error': 'project_id and user_id are required for site_engineer_assigned notifications'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                project = Project.objects.get(id=project_id)
            except Project.DoesNotExist:
                return Response(
                    {'error': 'Project not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            try:
                assigned_user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check if user is a site engineer type
            site_engineer_groups = ['Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer']
            if any(assigned_user.groups.filter(name=group).exists() for group in site_engineer_groups):
                notify_site_engineer_assigned(project, assigned_user)
                return Response(
                    {'status': 'Site Engineer assignment Chrome notification sent successfully'},
                    status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {'error': 'Assigned user is not a Site Engineer type'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Handle DPR submission notification
        elif notification_type == 'dpr_submitted':
            if not dpr_id:
                return Response(
                    {'error': 'dpr_id is required for dpr_submitted notifications'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                dpr = DailyProgressReport.objects.get(id=dpr_id)
            except DailyProgressReport.DoesNotExist:
                return Response(
                    {'error': 'DPR not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            notify_dpr_submitted(dpr)
            return Response(
                {'status': 'DPR submission Chrome notification sent successfully'},
                status=status.HTTP_200_OK
            )

        # Handle DPR approval notification
        elif notification_type == 'dpr_approved':
            if not dpr_id:
                return Response(
                    {'error': 'dpr_id is required for dpr_approved notifications'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                dpr = DailyProgressReport.objects.get(id=dpr_id)
            except DailyProgressReport.DoesNotExist:
                return Response(
                    {'error': 'DPR not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Determine who approved it based on the current approver role
            # This assumes the DPR status has been updated before calling this endpoint
            approved_by_role = dpr.current_approver_role or 'Unknown'

            # Import the role-based approval notification
            from services.notifications import notify_dpr_approved_by_role
            notify_dpr_approved_by_role(dpr, approved_by_role)

            return Response(
                {'status': f'DPR approval Chrome notification sent successfully (approved by {approved_by_role})'},
                status=status.HTTP_200_OK
            )

        # Handle DPR rejection notification
        elif notification_type == 'dpr_rejected':
            if not dpr_id:
                return Response(
                    {'error': 'dpr_id is required for dpr_rejected notifications'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                dpr = DailyProgressReport.objects.get(id=dpr_id)
            except DailyProgressReport.DoesNotExist:
                return Response(
                    {'error': 'DPR not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Determine who rejected it based on the current approver role
            rejected_by_role = dpr.current_approver_role or 'Unknown'

            # Import the role-based rejection notification
            from services.notifications import notify_dpr_rejected_by_role
            notify_dpr_rejected_by_role(dpr, rejected_by_role)

            return Response(
                {'status': f'DPR rejection Chrome notification sent successfully (rejected by {rejected_by_role})'},
                status=status.HTTP_200_OK
            )

        else:
            return Response(
                {'error': f'Unknown notification type: {notification_type}'},
                status=status.HTTP_400_BAD_REQUEST
            )

    except Exception as e:
        return Response(
            {'error': f'Failed to send Chrome notification: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )