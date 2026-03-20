from django.contrib import admin
from .models import Task, DailyProgressReport

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('name', 'site', 'assigned_to', 'status', 'progress_percentage')
    list_filter = ('status', 'site')
    search_fields = ('name', 'description')

@admin.register(DailyProgressReport)
class DailyProgressReportAdmin(admin.ModelAdmin):
    list_display = ('report_date', 'submitted_by', 'status', 'manpower_count')
    list_filter = ('status', 'report_date')
    search_fields = ('work_done', 'critical_issues', 'submitted_by__username')
    readonly_fields = ('created_at',)
    
    fieldsets = (
        ("Basic Information", {
            'fields': ('site', 'task', 'submitted_by', 'report_date', 'status')
        }),
        ("Report Content", {
            'fields': ('work_done', 'critical_issues', 'billing_status')
        }),
        ("Logs (JSON)", {
            'fields': ('labor_log', 'machinery_log', 'activity_progress', 'manpower_count'),
            'description': "These fields store the structured data from the frontend form."
        }),
        ("Review Information", {
            'fields': ('approved_by', 'reviewed_at', 'rejection_reason')
        }),
        ("System Info", {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
