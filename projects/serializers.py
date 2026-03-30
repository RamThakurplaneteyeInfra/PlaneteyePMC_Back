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
    coordinator_names = serializers.SerializerMethodField()
    site_engineer_names = serializers.SerializerMethodField()
    billing_engineer_name = serializers.SerializerMethodField()
    qaqc_engineer_name = serializers.SerializerMethodField()
    documentation_file_url = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    # Dashboard data fields
    planned_value = serializers.SerializerMethodField()
    earned_value = serializers.SerializerMethodField()
    actual_cost = serializers.SerializerMethodField()
    gross_billed = serializers.SerializerMethodField()
    net_billed = serializers.SerializerMethodField()
    net_collected = serializers.SerializerMethodField()
    net_due = serializers.SerializerMethodField()
    total_manhours = serializers.SerializerMethodField()
    fatalities = serializers.SerializerMethodField()
    significant = serializers.SerializerMethodField()
    major = serializers.SerializerMethodField()
    minor = serializers.SerializerMethodField()
    near_miss = serializers.SerializerMethodField()



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

    def get_coordinator_names(self, obj):
        coordinators = obj.coordinators.all()
        return [f"{c.first_name} {c.last_name}".strip() or c.username for c in coordinators]

    def get_site_engineer_names(self, obj):
        site_engineers = obj.site_engineers.all()
        return [f"{se.first_name} {se.last_name}".strip() or se.username for se in site_engineers]

    def get_billing_engineer_name(self, obj):
        if obj.billing_site_engineer:
            return f"{obj.billing_site_engineer.first_name} {obj.billing_site_engineer.last_name}".strip() or obj.billing_site_engineer.username
        return None

    def get_qaqc_engineer_name(self, obj):
        if obj.qaqc_site_engineer:
            return f"{obj.qaqc_site_engineer.first_name} {obj.qaqc_site_engineer.last_name}".strip() or obj.qaqc_site_engineer.username
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

    def get_planned_value(self, obj):
        try:
            return obj.dashboard_data.planned_value if obj.dashboard_data else None
        except:
            return None

    def get_earned_value(self, obj):
        try:
            return obj.dashboard_data.earned_value if obj.dashboard_data else None
        except:
            return None

    def get_actual_cost(self, obj):
        try:
            return obj.dashboard_data.ac if obj.dashboard_data else None
        except:
            return None

    def get_gross_billed(self, obj):
        try:
            return obj.dashboard_data.gross_billed if obj.dashboard_data else None
        except:
            return None

    def get_net_billed(self, obj):
        try:
            return obj.dashboard_data.net_billed if obj.dashboard_data else None
        except:
            return None

    def get_net_collected(self, obj):
        try:
            return obj.dashboard_data.net_collected if obj.dashboard_data else None
        except:
            return None

    def get_net_due(self, obj):
        try:
            return obj.dashboard_data.net_due if obj.dashboard_data else None
        except:
            return None

    def get_total_manhours(self, obj):
        try:
            return obj.dashboard_data.total_manhours if obj.dashboard_data else None
        except:
            return None

    def get_fatalities(self, obj):
        try:
            return obj.dashboard_data.fatalities if obj.dashboard_data else None
        except:
            return None

    def get_significant(self, obj):
        try:
            return obj.dashboard_data.significant if obj.dashboard_data else None
        except:
            return None

    def get_major(self, obj):
        try:
            return obj.dashboard_data.major if obj.dashboard_data else None
        except:
            return None

    def get_minor(self, obj):
        try:
            return obj.dashboard_data.minor if obj.dashboard_data else None
        except:
            return None

    def get_near_miss(self, obj):
        try:
            return obj.dashboard_data.near_miss if obj.dashboard_data else None
        except:
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


class ProjectInitSerializer(serializers.ModelSerializer):
    """
    Serializer for Project Initialization API.
    
    PMC Head uses this to initialize a project with:
    - Basic Info (name, location)
    - Project Dates (start, contract finish, forecast finish)
    - Contract Values (original, approved VO, pending VO)
    - Budget (BAC)
    - Work Configuration (hours/day, days/month)
    - Team Assignment
    
    Auto-calculated fields (NOT accepted in input):
    - revised_contract_value = original_contract_value + approved_vo
    - delay_days = (forecast_finish - contract_finish).days
    """
    
    # Read-only fields that are auto-calculated
    revised_contract_value = serializers.DecimalField(
        max_digits=15, decimal_places=2,
        read_only=True
    )
    delay_days = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = Project
        # Fields that CAN be accepted in input
        fields = [
            # Basic Info
            'name',
            'location',
            
            # Project Dates
            'project_start',
            'contract_finish',
            'forecast_finish',
            
            # Contract Values
            'original_contract_value',
            'approved_vo',
            'pending_vo',
            
            # Budget
            'bac',
            
            # Work Configuration
            'working_hours_per_day',
            'working_days_per_month',
            
            # Team Assignment
            'assigned_users',
            
            # Auto-calculated (read-only in response)
            'revised_contract_value',
            'delay_days',
            'created_at',
        ]
        extra_kwargs = {
            # All fields are required for initialization
            'name': {'required': True},
            'location': {'required': True},
            'project_start': {'required': True},
            'contract_finish': {'required': True},
            'forecast_finish': {'required': False, 'allow_null': True},
            'original_contract_value': {'required': True, 'min_value': 0},
            'approved_vo': {'required': True, 'min_value': 0},
            'pending_vo': {'required': True, 'min_value': 0},
            'bac': {'required': True, 'min_value': 0},
            'working_hours_per_day': {'required': True, 'min_value': 0},
            'working_days_per_month': {'required': True, 'min_value': 1},
            'assigned_users': {'required': False, 'many': True},
        }
    
    def validate_original_contract_value(self, value):
        """Validate original_contract_value >= 0"""
        if value < 0:
            raise serializers.ValidationError("Original contract value must be >= 0")
        return value
    
    def validate_approved_vo(self, value):
        """Validate approved_vo >= 0"""
        if value < 0:
            raise serializers.ValidationError("Approved VO must be >= 0")
        return value
    
    def validate_bac(self, value):
        """Validate bac > 0"""
        if value <= 0:
            raise serializers.ValidationError("Budget at Completion (BAC) must be > 0")
        return value
    
    def validate_working_hours_per_day(self, value):
        """Validate working_hours_per_day > 0"""
        if value <= 0:
            raise serializers.ValidationError("Working hours per day must be > 0")
        return value
    
    def validate_working_days_per_month(self, value):
        """Validate working_days_per_month > 0"""
        if value <= 0:
            raise serializers.ValidationError("Working days per month must be > 0")
        return value
    
    def create(self, validated_data):
        """
        Create a new project with auto-calculated fields.
        
        The save() method in the model handles:
        - revised_contract_value = original_contract_value + approved_vo
        - delay_days = (forecast_finish - contract_finish).days
        """
        # Remove assigned_users from validated_data as it's handled differently
        assigned_users = validated_data.pop('assigned_users', [])
        
        # Create the project
        project = Project(**validated_data)
        # This will trigger the save() method which calculates revised_contract_value and delay_days
        project.save()
        
        # Assign users if provided
        if assigned_users:
            project.assigned_users.set(assigned_users)
        
        return project
    
    def to_representation(self, instance):
        """Return the project with auto-calculated fields."""
        # Trigger recalculation in case instance was modified
        instance.save()
        return super().to_representation(instance)