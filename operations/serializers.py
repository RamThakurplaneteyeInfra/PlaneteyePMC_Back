from rest_framework import serializers
from .models import Task, DailyProgressReport

class TaskSerializer(serializers.ModelSerializer):
    site_name = serializers.ReadOnlyField(source='site.name')
    assigned_to_name = serializers.ReadOnlyField(source='assigned_to.username')

    class Meta:
        model = Task
        fields = '__all__'

class DailyProgressReportSerializer(serializers.ModelSerializer):
    task_name = serializers.ReadOnlyField(source='task.name')
    site_name = serializers.ReadOnlyField(source='site.name')
    project_name = serializers.ReadOnlyField(source='project.name')
    submitted_by_name = serializers.ReadOnlyField(source='submitted_by.username')
    approved_by_name = serializers.ReadOnlyField(source='approved_by.username')

    class Meta:
        model = DailyProgressReport
        # drf-yasg: avoid OpenAPI schema name collisions with DPR app serializer
        ref_name = "OperationsDailyProgressReport"
        fields = '__all__'
        read_only_fields = ('submitted_by', 'approved_by', 'reviewed_at', 'status', 'rejection_reason')
        extra_kwargs = {
            'project': {'required': False, 'allow_null': True},
            'site': {'required': False, 'allow_null': True},
            'task': {'required': False, 'allow_null': True},
        }
