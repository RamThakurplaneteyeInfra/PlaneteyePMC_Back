from django.db import models
from django.contrib.auth.models import User
from django.conf import settings


class UserProfile(models.Model):
    """
    Extended user profile to store additional role information
    """
    SITE_ENGINEER_TYPES = [
        ('site_engineer', 'Site Engineer'),
        ('billing_site_engineer', 'Billing Site Engineer'),
        ('qaqc_site_engineer', 'QAQC Site Engineer'),
        ('hse_site_engineer', 'HSE Site Engineer'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    
    # Site Engineer subtype (only relevant if user is a Site Engineer)
    site_engineer_type = models.CharField(
        max_length=50,
        choices=SITE_ENGINEER_TYPES,
        null=True,
        blank=True,
        help_text="Type of Site Engineer (only for Site Engineers)"
    )
    
    phone_number = models.CharField(max_length=20, blank=True)
    designation = models.CharField(max_length=255, blank=True)
    department = models.CharField(max_length=255, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - Profile"

    def get_primary_role(self):
        """
        Get the primary role of the user based on their groups
        Returns the role name as a string
        """
        groups = self.user.groups.all()
        if not groups.exists():
            return None
        
        # Priority order: CEO > PMC Head > Team Leader > Coordinator > Site Engineers
        role_priority = [
            'CEO',
            'PMC Head',
            'Team Leader',
            'Coordinator',
            'Billing Site Engineer',
            'QAQC Site Engineer',
            'HSE Site Engineer',
            'Site Engineer',
        ]
        
        for role in role_priority:
            if groups.filter(name=role).exists():
                return role
        
        # Return first group if no priority match
        return groups.first().name

    def get_role_display_name(self):
        """
        Get a display-friendly role name
        """
        role = self.get_primary_role()
        if role:
            return role
        return "No Role Assigned"


class Notification(models.Model):
    """
    In-app alerts and notification log entries.
    """

    NOTIFICATION_TYPE_PROJECT_ASSIGNED = "project_assigned"
    NOTIFICATION_TYPE_DPR_SUBMITTED = "dpr_submitted"
    NOTIFICATION_TYPE_DPR_APPROVED = "dpr_approved"
    NOTIFICATION_TYPE_DPR_REJECTED = "dpr_rejected"
    NOTIFICATION_TYPE_BILLING_UPDATE = "BILLING_UPDATE"
    NOTIFICATION_TYPE_MEETING_DOCUMENT = "MEETING_DOCUMENT"
    NOTIFICATION_TYPE_CORRESPONDENCE_ATTACHMENT = "CORRESPONDENCE_ATTACHMENT"

    NOTIFICATION_TYPES = [
        (NOTIFICATION_TYPE_PROJECT_ASSIGNED, "Project Assigned"),
        (NOTIFICATION_TYPE_DPR_SUBMITTED, "DPR Submitted"),
        (NOTIFICATION_TYPE_DPR_APPROVED, "DPR Approved"),
        (NOTIFICATION_TYPE_DPR_REJECTED, "DPR Rejected"),
        (NOTIFICATION_TYPE_BILLING_UPDATE, "Billing Data Updated"),
        (NOTIFICATION_TYPE_MEETING_DOCUMENT, "Meeting Document Uploaded"),
        (NOTIFICATION_TYPE_CORRESPONDENCE_ATTACHMENT, "Correspondence Document Uploaded"),
    ]

    ACTION_CREATE = "CREATE"
    ACTION_UPDATE = "UPDATE"
    ACTION_DELETE = "DELETE"

    ACTION_TYPES = [
        (ACTION_CREATE, "Create"),
        (ACTION_UPDATE, "Update"),
        (ACTION_DELETE, "Delete"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        help_text="User who received the notification",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_notifications",
        help_text="User who triggered the notification",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
        help_text="Project related to the notification",
    )
    module_name = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Financial module that was updated",
    )
    action_type = models.CharField(
        max_length=10,
        choices=ACTION_TYPES,
        blank=True,
        default="",
        help_text="Create, update, or delete action",
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Short notification title",
    )
    message = models.TextField(help_text="Notification message content")
    notification_type = models.CharField(
        max_length=30,
        choices=NOTIFICATION_TYPES,
        help_text="Type of notification",
    )
    is_read = models.BooleanField(
        default=False,
        help_text="Whether the user has read the notification",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the notification was created",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self):
        return f"{self.notification_type} - {self.user.username} - {self.created_at}"
