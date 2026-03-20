from rest_framework import serializers
from .models import Project, Site
from .models import Project, Site, ProjectDashboardData

class SiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = '__all__'

class ProjectSerializer(serializers.ModelSerializer):
    sites = SiteSerializer(many=True, read_only=True)
    pmc_head_name = serializers.SerializerMethodField()
    team_lead_name = serializers.SerializerMethodField()
    documentation_file_url = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()



    class Meta:
        model = Project
        fields = '__all__'
        extra_kwargs = {
            'pmc_head': {'required': False, 'allow_null': True},
            'team_lead': {'required': False, 'allow_null': True},
            'created_by': {'read_only': True},
        }

    def get_pmc_head_name(self, obj):
        if obj.pmc_head:
            return f"{obj.pmc_head.first_name} {obj.pmc_head.last_name}".strip() or obj.pmc_head.username
        return None

    def get_team_lead_name(self, obj):
        if obj.team_lead:
            return f"{obj.team_lead.first_name} {obj.team_lead.last_name}".strip() or obj.team_lead.username
        return None

    def get_documentation_file_url(self, obj):
        if obj.documentation_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.documentation_file.url)
            return obj.documentation_file.url
        return None

    def get_created_by_name(self, obj):
        u = getattr(obj, 'created_by', None)
        if u:
            full = f"{u.first_name} {u.last_name}".strip()
            return full or u.username
        return None

    def to_internal_value(self, data):
        """Handle boolean fields sent as strings from FormData."""
        # Convert mutable copy if needed
        if hasattr(data, 'dict'):
            # It's a QueryDict (from FormData), convert to mutable dict
            mutable_data = data.copy()
        else:
            mutable_data = data.copy() if hasattr(data, 'copy') else dict(data)

        # Convert string booleans to actual booleans
        boolean_fields = ['has_documentation', 'has_iso_checklist', 'has_test_frequency_chart']
        for field in boolean_fields:
            if field in mutable_data:
                val = mutable_data[field]
                if isinstance(val, str):
                    mutable_data[field] = val.lower() in ('true', '1', 'yes')

        return super().to_internal_value(mutable_data)


class ProjectDashboardDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectDashboardData
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')