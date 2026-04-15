from django.urls import path
from . import views

urlpatterns = [
    path('test/', views.notifications_test, name='notifications_test'),
    path('send-test/', views.send_test_notification, name='send_test_notification'),
    path('send-test-email/', views.send_test_email, name='send_test_email'),
    path('test-sync-email/', views.test_sync_email, name='test_sync_email'),

    # Specific notification endpoints
    path('project-created/', views.notify_project_created_endpoint, name='notify_project_created'),
    path('team-lead-assigned/', views.notify_team_lead_assigned_endpoint, name='notify_team_lead_assigned'),
    path('site-engineer-assigned/', views.notify_site_engineer_assigned_endpoint, name='notify_site_engineer_assigned'),
    path('dpr-submitted/', views.notify_dpr_submitted_endpoint, name='notify_dpr_submitted'),
    path('dpr-approved/', views.notify_dpr_approved_endpoint, name='notify_dpr_approved'),
    path('dpr-rejected/', views.notify_dpr_rejected_endpoint, name='notify_dpr_rejected'),
]