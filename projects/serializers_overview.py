"""Lightweight serializer for PMC dashboard project cards."""

from rest_framework import serializers


class OverviewKpiSerializer(serializers.Serializer):
    percentage = serializers.IntegerField()
    status = serializers.CharField()


class OverviewTeamLeaderSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    full_name = serializers.CharField(allow_blank=True)


class OverviewCompletedBySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    full_name = serializers.CharField(allow_blank=True)


class ProjectOverviewSerializer(serializers.Serializer):
    """Card payload only — no nested dashboard charts or financial blobs."""

    project_id = serializers.IntegerField()
    project_name = serializers.CharField()
    project_code = serializers.CharField(allow_blank=True)
    client = serializers.CharField(allow_blank=True)
    project_type = serializers.CharField(allow_blank=True)
    project_icon = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    completed_at = serializers.CharField(allow_null=True, required=False)
    completed_by = OverviewCompletedBySerializer(allow_null=True, required=False)
    health_score = serializers.IntegerField()
    progress = OverviewKpiSerializer()
    time = OverviewKpiSerializer()
    cost = OverviewKpiSerializer()
    quality = OverviewKpiSerializer()
    safety = OverviewKpiSerializer()
    team_leader = OverviewTeamLeaderSerializer(allow_null=True)
    location = serializers.CharField(allow_blank=True)
    issues_count = serializers.IntegerField()
    dpr_count = serializers.IntegerField()
    last_updated = serializers.CharField(allow_null=True)
    compare_enabled = serializers.BooleanField()
