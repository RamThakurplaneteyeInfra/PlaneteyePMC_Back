from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import UserProfile

User = get_user_model()


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for UserProfile"""
    class Meta:
        model = UserProfile
        fields = ('site_engineer_type', 'phone_number', 'designation', 'department')


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User with role information"""
    # This will get the names of the groups the user belongs to
    groups = serializers.StringRelatedField(many=True)
    
    # Primary role (computed from groups)
    primary_role = serializers.SerializerMethodField()
    
    # Role display name
    role_display = serializers.SerializerMethodField()
    
    # Site engineer type (if applicable)
    site_engineer_type = serializers.SerializerMethodField()
    
    # Profile information
    profile = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name', 
            'groups', 'primary_role', 'role_display', 'site_engineer_type', 'profile'
        )

    def get_primary_role(self, obj):
        """Get primary role based on groups"""
        try:
            profile = obj.profile
            return profile.get_primary_role()
        except UserProfile.DoesNotExist:
            # Fallback to first group if profile doesn't exist
            groups = obj.groups.all()
            if groups.exists():
                return groups.first().name
            return None

    def get_role_display(self, obj):
        """Get display-friendly role name"""
        try:
            profile = obj.profile
            return profile.get_role_display_name()
        except UserProfile.DoesNotExist:
            groups = obj.groups.all()
            if groups.exists():
                return groups.first().name
            return "No Role Assigned"

    def get_site_engineer_type(self, obj):
        """Get site engineer type if user is a site engineer"""
        try:
            profile = obj.profile
            if profile.site_engineer_type:
                return profile.get_site_engineer_type_display()
            return None
        except UserProfile.DoesNotExist:
            return None

    def get_profile(self, obj):
        """Get profile data, or None if no profile"""
        try:
            profile = obj.profile
            return UserProfileSerializer(profile).data
        except UserProfile.DoesNotExist:
            return None
