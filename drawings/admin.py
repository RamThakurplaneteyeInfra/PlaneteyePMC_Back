"""
Django admin registration for the Drawings app.
"""

from django.contrib import admin

from .models.drawing import Drawing


@admin.register(Drawing)
class DrawingAdmin(admin.ModelAdmin):
    """Admin view for Drawing records."""

    list_display = [
        "projectName",
        "totalSubmitted",
        "totalApproved",
        "variance",
        "approvalPercentage",
        "created_at",
        "updated_at",
    ]
    list_filter = ["created_at"]
    search_fields = ["projectName"]
    readonly_fields = ["variance", "approvalPercentage", "created_at", "updated_at"]
    ordering = ["projectName"]
