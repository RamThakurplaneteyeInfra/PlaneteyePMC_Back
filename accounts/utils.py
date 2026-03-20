"""
Utility functions for user roles
"""
from django.contrib.auth.models import User


def get_user_role(user):
    """
    Get the primary role of a user
    Returns role name as string or None
    """
    if not user or not user.is_authenticated:
        return None
    
    groups = user.groups.all()
    if not groups.exists():
        return None
    
    # Priority order: CEO > PMC Head > Team Leader > Coordinator > Site Engineers
    role_priority = [
        'CEO',
        'PMC Head',
        'Team Leader',
        'Coordinator',
        'Billing Site Engineer',
        'QAQC Site Engineer',
        'Site Engineer',
    ]
    
    for role in role_priority:
        if groups.filter(name=role).exists():
            return role
    
    # Return first group if no priority match
    return groups.first().name


def is_pmc_head(user):
    """Check if user is PMC Head"""
    return user.groups.filter(name='PMC Head').exists() if user else False


def is_ceo(user):
    """Check if user is CEO"""
    return user.groups.filter(name='CEO').exists() if user else False


def is_team_leader(user):
    """Check if user is Team Leader"""
    return user.groups.filter(name='Team Leader').exists() if user else False


def is_coordinator(user):
    """Check if user is Coordinator"""
    return user.groups.filter(name='Coordinator').exists() if user else False


def is_site_engineer(user):
    """Check if user is any type of Site Engineer"""
    if not user:
        return False
    return user.groups.filter(
        name__in=['Site Engineer', 'Billing Site Engineer', 'QAQC Site Engineer']
    ).exists()


def is_billing_site_engineer(user):
    """Check if user is Billing Site Engineer"""
    return user.groups.filter(name='Billing Site Engineer').exists() if user else False


def is_qaqc_site_engineer(user):
    """Check if user is QAQC Site Engineer"""
    return user.groups.filter(name='QAQC Site Engineer').exists() if user else False


def get_site_engineer_type(user):
    """
    Get the type of site engineer
    Returns: 'site_engineer', 'billing_site_engineer', 'qaqc_site_engineer', or None
    """
    if not user:
        return None
    
    try:
        profile = user.profile
        return profile.site_engineer_type
    except:
        # Fallback to group-based detection
        if user.groups.filter(name='Billing Site Engineer').exists():
            return 'billing_site_engineer'
        elif user.groups.filter(name='QAQC Site Engineer').exists():
            return 'qaqc_site_engineer'
        elif user.groups.filter(name='Site Engineer').exists():
            return 'site_engineer'
        return None
