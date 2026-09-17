from django.contrib import admin
from .models import ManpowerRecord


@admin.register(ManpowerRecord)
class ManpowerRecordAdmin(admin.ModelAdmin):
    list_display = (
        'project_name',
        'month',
        'year',
        'monthly_planned_manpower',
        'actual_manpower',
        'difference',
        'created_at',
    )
    list_filter = ('year', 'month', 'project_name')
    search_fields = ('project_name', 'month', 'remarks')
    ordering = ('-created_at',)
    readonly_fields = ('difference', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
