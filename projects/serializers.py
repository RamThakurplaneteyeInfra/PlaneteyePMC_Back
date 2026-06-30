from rest_framework import serializers
from .bottleneck_sync import (
    bottlenecks_to_left_text,
    sync_bottlenecks_from_dashboard,
)
from .models import Project, Site, ProjectDashboardData, ProjectLog, ProjectLogEntry

class SiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = '__all__'

class ProjectSerializer(serializers.ModelSerializer):
    """
    Serializer for Project model with related data and dashboard metrics.

    Performance Notes:
    - Use select_related('dashboard_data') in views for optimal dashboard field access
    - Use prefetch_related('sites', 'coordinators', 'site_engineers') for many-to-many fields
    """

    sites = SiteSerializer(many=True, read_only=True)
    pmc_head_name = serializers.SerializerMethodField()
    team_lead_name = serializers.SerializerMethodField()
    coordinator_names = serializers.SerializerMethodField()
    site_engineer_names = serializers.SerializerMethodField()
    site_engineer_name = serializers.SerializerMethodField()
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

    # Project date fields — read from dashboard_data when available,
    # fall back to Project model fields (project_start / contract_finish / forecast_finish).
    # These are the canonical names the frontend uses everywhere.
    project_start_date = serializers.SerializerMethodField()
    contract_finish_date = serializers.SerializerMethodField()
    forecast_finish_date = serializers.SerializerMethodField()



    class Meta:
        model = Project
        fields = '__all__'
        extra_kwargs = {
            'pmc_head': {'required': False, 'allow_null': True},
            'team_lead': {'required': False, 'allow_null': True},
            'created_by': {'read_only': True},
        }

    def _get_user_full_name_or_username(self, user):
        """
        Helper method to get user's full name or fallback to username.
        """
        if not user:
            return None
        full_name = f"{user.first_name} {user.last_name}".strip()
        return full_name or user.username

    def _get_users_names_list(self, users_queryset):
        """
        Helper method to get list of user names from queryset.
        """
        return [self._get_user_full_name_or_username(user) for user in users_queryset]

    def _get_dashboard_field_safe(self, obj, field_name, default=None):
        """
        Helper method to safely access dashboard data fields.
        Returns default if dashboard_data doesn't exist or field access fails.
        """
        try:
            if hasattr(obj, 'dashboard_data') and obj.dashboard_data:
                return getattr(obj.dashboard_data, field_name, default)
        except AttributeError:
            pass
        return default

    def get_pmc_head_name(self, obj):
        return self._get_user_full_name_or_username(obj.pmc_head)

    def get_team_lead_name(self, obj):
        return self._get_user_full_name_or_username(obj.team_lead)

    def get_coordinator_names(self, obj):
        return self._get_users_names_list(obj.coordinators.all())

    def get_site_engineer_names(self, obj):
        return self._get_users_names_list(obj.site_engineers.all())

    def get_site_engineer_name(self, obj):
        return self._get_user_full_name_or_username(obj.site_engineer)

    def get_billing_engineer_name(self, obj):
        return self._get_user_full_name_or_username(obj.billing_site_engineer)

    def get_qaqc_engineer_name(self, obj):
        return self._get_user_full_name_or_username(obj.qaqc_site_engineer)

    def get_documentation_file_url(self, obj):
        if obj.documentation_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.documentation_file.url)
            return obj.documentation_file.url
        return None

    def get_created_by_name(self, obj):
        return self._get_user_full_name_or_username(getattr(obj, 'created_by', None))

    def get_planned_value(self, obj):
        return self._get_dashboard_field_safe(obj, 'planned_value')

    def get_earned_value(self, obj):
        return self._get_dashboard_field_safe(obj, 'earned_value')

    def get_actual_cost(self, obj):
        return self._get_dashboard_field_safe(obj, 'ac')

    def get_gross_billed(self, obj):
        return self._get_dashboard_field_safe(obj, 'gross_billed')

    def get_net_billed(self, obj):
        return self._get_dashboard_field_safe(obj, 'net_billed')

    def get_net_collected(self, obj):
        return self._get_dashboard_field_safe(obj, 'net_collected')

    def get_net_due(self, obj):
        return self._get_dashboard_field_safe(obj, 'net_due')

    def get_total_manhours(self, obj):
        return self._get_dashboard_field_safe(obj, 'total_manhours')

    def get_fatalities(self, obj):
        return self._get_dashboard_field_safe(obj, 'fatalities')

    def get_significant(self, obj):
        return self._get_dashboard_field_safe(obj, 'significant')

    def get_major(self, obj):
        return self._get_dashboard_field_safe(obj, 'major')

    def get_minor(self, obj):
        return self._get_dashboard_field_safe(obj, 'minor')

    def get_near_miss(self, obj):
        return self._get_dashboard_field_safe(obj, 'near_miss')

    def get_project_start_date(self, obj):
        """
        Return project_start_date from dashboard_data when available,
        falling back to the Project model's project_start field.
        This ensures the frontend always gets the latest saved value.
        """
        dd_value = self._get_dashboard_field_safe(obj, 'project_start_date')
        if dd_value is not None:
            return str(dd_value)
        return str(obj.project_start) if obj.project_start else None

    def get_contract_finish_date(self, obj):
        """
        Return contract_finish_date from dashboard_data when available,
        falling back to the Project model's contract_finish field.
        """
        dd_value = self._get_dashboard_field_safe(obj, 'contract_finish_date')
        if dd_value is not None:
            return str(dd_value)
        return str(obj.contract_finish) if obj.contract_finish else None

    def get_forecast_finish_date(self, obj):
        """
        Return forecast_finish_date from dashboard_data when available,
        falling back to the Project model's forecast_finish field.
        """
        dd_value = self._get_dashboard_field_safe(obj, 'forecast_finish_date')
        if dd_value is not None:
            return str(dd_value)
        return str(obj.forecast_finish) if obj.forecast_finish else None

    def to_internal_value(self, data):
        """
        Handle boolean fields sent as strings from FormData.
        Optimized for cleaner boolean parsing.
        """
        # Create a mutable copy of data
        if hasattr(data, 'dict'):
            # QueryDict from FormData
            mutable_data = data.copy()
        else:
            mutable_data = data.copy() if hasattr(data, 'copy') else dict(data)

        # Convert string booleans to actual booleans
        boolean_fields = ['has_documentation', 'has_iso_checklist', 'has_test_frequency_chart']
        truthy_values = {'true', '1', 'yes'}

        for field in boolean_fields:
            if field in mutable_data:
                val = mutable_data[field]
                if isinstance(val, str):
                    mutable_data[field] = val.lower() in truthy_values

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
    
    def _validate_positive_decimal(self, value, field_name, allow_zero=True):
        """
        Helper method to validate positive decimal values.
        """
        if value < 0 or (not allow_zero and value == 0):
            operator = '>=' if allow_zero else '>'
            raise serializers.ValidationError(f"{field_name} must be {operator} 0")
        return value

    def validate_original_contract_value(self, value):
        return self._validate_positive_decimal(value, "Original contract value")

    def validate_approved_vo(self, value):
        return self._validate_positive_decimal(value, "Approved VO")

    def validate_bac(self, value):
        return self._validate_positive_decimal(value, "Budget at Completion (BAC)", allow_zero=False)

    def validate_working_hours_per_day(self, value):
        return self._validate_positive_decimal(value, "Working hours per day", allow_zero=False)

    def validate_working_days_per_month(self, value):
        return self._validate_positive_decimal(value, "Working days per month", allow_zero=False)
    
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


# ======================================================
# Project Logs Serializers
# ======================================================

class ProjectLogEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectLogEntry
        fields = ['id', 'entry_type', 'left_text', 'right_text', 'row_order']


class ProjectLogSerializer(serializers.ModelSerializer):
    """
    Serializer for Project Logs with nested entries.
    Supports both Issues/Concerns and Risks/Actions.
    """
    entries = ProjectLogEntrySerializer(many=True, required=False)

    class Meta:
        model = ProjectLog
        fields = ['id', 'project', 'entries', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at', 'project']

    def validate(self, data):
        entries_data = self.initial_data.get('entries', [])
        
        seen_orders = {
            ProjectLogEntry.EntryType.ISSUE_CONCERN: set(),
            ProjectLogEntry.EntryType.RISK_ACTION: set(),
            ProjectLogEntry.EntryType.BOTTLENECK_DASHBOARD: set(),
        }

        for entry in entries_data:
            entry_type = entry.get('entry_type')
            row_order = entry.get('row_order', 0)

            if entry_type in seen_orders:
                if row_order in seen_orders[entry_type]:
                    raise serializers.ValidationError(
                        f"Duplicate row_order {row_order} for entry_type {entry_type}"
                    )
                seen_orders[entry_type].add(row_order)

        return data

    def create(self, validated_data):
        # This is usually handled via the ViewSet
        project_log = ProjectLog.objects.create(**validated_data)
        return project_log

    def update(self, instance, validated_data):
        entries_data = self.initial_data.get('entries', [])
        request = self.context.get('request')
        user = request.user if request and request.user.is_authenticated else None
        project_id = instance.project_id

        instance.entries.all().delete()

        for entry_data in entries_data:
            entry_type = entry_data.get('entry_type')
            left_text = entry_data.get('left_text', '')
            right_text = entry_data.get('right_text', '')

            if entry_type == ProjectLogEntry.EntryType.BOTTLENECK_DASHBOARD:
                left_text = sync_bottlenecks_from_dashboard(
                    project_id, left_text, user=user
                )

            ProjectLogEntry.objects.create(
                project_log=instance,
                entry_type=entry_type,
                left_text=left_text,
                right_text=right_text,
                row_order=entry_data.get('row_order', 0),
            )

        instance.save()
        return instance

    def to_representation(self, instance):
        """Ensure entries are properly ordered; refresh bottleneck JSON from DB."""
        representation = super().to_representation(instance)
        entries = representation.get('entries', [])

        for entry in entries:
            if entry.get('entry_type') == ProjectLogEntry.EntryType.BOTTLENECK_DASHBOARD:
                entry['left_text'] = bottlenecks_to_left_text(instance.project_id)

        sorted_entries = sorted(
            entries,
            key=lambda x: (x.get('entry_type', ''), x.get('row_order', 0)),
        )
        representation['entries'] = sorted_entries
        return representation
