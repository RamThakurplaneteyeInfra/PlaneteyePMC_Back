from rest_framework import serializers


class WPRActivitySerializer(serializers.Serializer):
    """
    Serializer for individual activity in WPR
    """
    scope_name = serializers.CharField()
    scope_description = serializers.CharField()
    category_name = serializers.CharField()
    subcategory_name = serializers.CharField()
    unit = serializers.CharField()
    planned_quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    executed_quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    remaining_quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    progress_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    section = serializers.CharField()
    location = serializers.CharField()
    status = serializers.CharField()
    next_day_planned_work = serializers.CharField()
    remarks = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    completion_date = serializers.DateField(allow_null=True)
    days_taken = serializers.IntegerField()


class WPRSummarySerializer(serializers.Serializer):
    """
    Serializer for weekly summary statistics
    """
    total_activities = serializers.IntegerField()
    completed = serializers.IntegerField()
    in_progress = serializers.IntegerField()
    pending = serializers.IntegerField()
    completion_rate = serializers.FloatField()
    overall_progress = serializers.FloatField()
    total_work_done = serializers.FloatField()
    performance = serializers.CharField()
    status = serializers.CharField()


class WPRPendingWorkSerializer(serializers.Serializer):
    """
    Serializer for pending work items
    """
    scope = serializers.CharField()
    scope_id = serializers.IntegerField()
    progress = serializers.DecimalField(max_digits=5, decimal_places=2)
    planned_quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    executed_quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    remaining_quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    last_updated = serializers.CharField()  # ISO format string
    next_plan = serializers.CharField()


class WPRIssuesSerializer(serializers.Serializer):
    """
    Serializer for issues structure
    """
    total = serializers.IntegerField()
    unresolved = serializers.ListField(child=serializers.CharField())


class WPRWeekSerializer(serializers.Serializer):
    """
    Serializer for a single week's data in WPR
    """
    week = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    activities = WPRActivitySerializer(many=True)
    summary = WPRSummarySerializer()
    deliverables = serializers.ListField(child=serializers.CharField())
    pending_work = WPRPendingWorkSerializer(many=True)
    issues = WPRIssuesSerializer()
    remarks = serializers.ListField(child=serializers.CharField())
    quality_status = serializers.CharField()
    incidents = serializers.ListField(child=serializers.CharField())
    billing_status = serializers.CharField(allow_null=True)
    drawing_status = serializers.CharField(allow_null=True)
    trend = serializers.CharField()
    status = serializers.CharField()


class WPRProjectSummarySerializer(serializers.Serializer):
    """
    Serializer for project-level summary
    """
    total_weeks = serializers.IntegerField()
    overall_completion = serializers.FloatField()
    status = serializers.CharField()


class WPRSerializer(serializers.Serializer):
    """
    Main serializer for Weekly Progress Report response
    """
    project_name = serializers.CharField()
    period = serializers.DictField()
    weeks = WPRWeekSerializer(many=True)
    project_summary = WPRProjectSummarySerializer()
