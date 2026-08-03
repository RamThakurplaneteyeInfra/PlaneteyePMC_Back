from rest_framework import serializers
from django.utils import timezone
from .models import ScopeCategory, ScopeSubCategory, MonthlyScopeWork, ScopeAssignment
from projects.models import Project


class ScopeSubCategorySerializer(serializers.ModelSerializer):
    """Serializer for Scope Subcategory"""

    class Meta:
        model = ScopeSubCategory
        fields = ['id', 'name', 'display_order', 'is_active', 'default_quantity']


class ScopeCategorySerializer(serializers.ModelSerializer):
    """Serializer for Scope Category with subcategories"""

    subcategories = ScopeSubCategorySerializer(many=True, read_only=True)

    class Meta:
        model = ScopeCategory
        fields = ['id', 'name', 'display_order', 'is_active', 'subcategories']


class MonthlyScopeWorkSerializer(serializers.ModelSerializer):
    """Serializer for Monthly Scope of Work"""

    # Nested serializers for relationships
    project_name = serializers.CharField(source='project.name', read_only=True)
    category_name = serializers.SerializerMethodField()
    subcategory_name = serializers.SerializerMethodField()

    # Custom fields for "Other" options
    custom_category_name = serializers.CharField(required=False, allow_blank=True)
    custom_subcategory_name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = MonthlyScopeWork
        fields = [
            'id', 'project', 'project_name', 'month', 'category', 'category_name',
            'subcategory', 'subcategory_name', 'description', 'unit', 'planned_quantity',
            'cumulative_quantity', 'remaining_quantity', 'progress_percentage',
            'section', 'location', 'start_date', 'end_date', 'custom_category_name',
            'custom_subcategory_name', 'status', 'created_by', 'updated_by',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']
        extra_kwargs = {
            'project': {'required': False},
            'month': {'required': False},
            # Required on create; model stays nullable for legacy rows
            'category': {'required': True, 'allow_null': False},
            'subcategory': {'required': True, 'allow_null': False},
            'unit': {'required': False},
            'planned_quantity': {'required': False},
            'start_date': {'required': False},
            'end_date': {'required': False},
        }

    def get_category_name(self, obj):
        try:
            return obj.get_category_display_name()
        except Exception:
            # category may be null for legacy rows
            return ""

    def get_subcategory_name(self, obj):
        try:
            return obj.get_subcategory_display_name()
        except Exception:
            # subcategory may be null for legacy rows
            return ""

    def validate(self, data):
        """
        Custom validation for MonthlyScopeWork
        """
        # Validate planned quantity if provided
        if 'planned_quantity' in data and data.get('planned_quantity') is not None and data.get('planned_quantity', 0) <= 0:
            raise serializers.ValidationError({
                'planned_quantity': 'Planned quantity must be greater than 0'
            })

        category = data.get('category', getattr(self.instance, 'category', None))
        subcategory = data.get('subcategory', getattr(self.instance, 'subcategory', None))

        # Create (and full update): category + subcategory are mandatory
        if not self.partial:
            errors = {}
            if not category:
                errors['category'] = 'Category is required.'
            if not subcategory:
                errors['subcategory'] = 'Subcategory is required.'
            if errors:
                raise serializers.ValidationError(errors)

        # Check if subcategory belongs to the selected category
        if subcategory and category and subcategory.category_id != category.id:
            raise serializers.ValidationError({
                'subcategory': 'Selected subcategory does not belong to the selected category'
            })

        # Validate custom names for "Other" options if category/subcategory is "Other"
        if category and category.name == "Other":
            custom_category_name = data.get(
                'custom_category_name',
                getattr(self.instance, 'custom_category_name', '') if self.instance else '',
            )
            if not str(custom_category_name or '').strip():
                raise serializers.ValidationError({
                    'custom_category_name': 'Custom category name is required when "Other" is selected'
                })

        if subcategory and subcategory.name == "Other":
            custom_subcategory_name = data.get(
                'custom_subcategory_name',
                getattr(self.instance, 'custom_subcategory_name', '') if self.instance else '',
            )
            if not str(custom_subcategory_name or '').strip():
                raise serializers.ValidationError({
                    'custom_subcategory_name': 'Custom subcategory name is required when "Other" is selected'
                })

        return data

    def create(self, validated_data):
        # Set created_by from request user
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['created_by'] = request.user

        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Set updated_by from request user
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['updated_by'] = request.user

        return super().update(instance, validated_data)


class ScopeAssignmentSerializer(serializers.ModelSerializer):
    """Serializer for Scope Assignment"""

    scope_details = MonthlyScopeWorkSerializer(source='scope', read_only=True)
    site_engineer_name = serializers.CharField(source='site_engineer.get_full_name', read_only=True)
    assigned_by_name = serializers.CharField(source='assigned_by.get_full_name', read_only=True)

    class Meta:
        model = ScopeAssignment
        fields = [
            'id', 'scope', 'scope_details', 'site_engineer', 'site_engineer_name',
            'assigned_by', 'assigned_by_name', 'assigned_at'
        ]
        read_only_fields = ['assigned_by', 'assigned_at']

    def create(self, validated_data):
        # Set assigned_by from request user
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['assigned_by'] = request.user

        return super().create(validated_data)