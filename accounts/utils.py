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

    # Prefer prefetched groups (one query / in-memory) over N× exists() hits.
    group_names = {g.name for g in user.groups.all()}
    if not group_names:
        return None

    # Priority: CEO > Head Office > PMC Head > Team Leader > PMC Manager > Site Engineers
    role_priority = [
        "CEO",
        "Head Office",
        "HO",  # short-name alias → normalized below
        "PMC Head",
        "Team Leader",
        "PMC Manager",
        "Coordinator",  # legacy alias
        "Billing Site Engineer",
        "QAQC Site Engineer",
        "HSE Site Engineer",
        "Site Engineer",
    ]

    for role in role_priority:
        if role in group_names:
            if role in ("HO",):
                return "Head Office"
            if role == "Coordinator":
                return "PMC Manager"
            return role

    # Return first group if no priority match
    return groups.first().name


def is_pmc_head(user):
    """Check if user is PMC Head"""
    return user.groups.filter(name="PMC Head").exists() if user else False


def is_ceo(user):
    """Check if user is CEO"""
    return user.groups.filter(name="CEO").exists() if user else False


def is_head_office(user):
    """Check if user is Head Office (HO)."""
    if not user:
        return False
    return user.groups.filter(name__in=["Head Office", "HO"]).exists()


def is_team_leader(user):
    """Check if user is Team Leader"""
    return user.groups.filter(name="Team Leader").exists() if user else False


def is_pmc_manager(user):
    """Check if user is PMC Manager (includes legacy Coordinator group)."""
    if not user:
        return False
    return user.groups.filter(name__in=["PMC Manager", "Coordinator"]).exists()


def is_coordinator(user):
    """Legacy alias for is_pmc_manager."""
    return is_pmc_manager(user)


def is_site_engineer(user):
    """Check if user is any type of Site Engineer"""
    if not user:
        return False
    return user.groups.filter(
        name__in=[
            "Site Engineer",
            "Billing Site Engineer",
            "QAQC Site Engineer",
            "HSE Site Engineer",
        ]
    ).exists()


def is_billing_site_engineer(user):
    """Check if user is Billing Site Engineer"""
    return user.groups.filter(name="Billing Site Engineer").exists() if user else False


def is_qaqc_site_engineer(user):
    """Check if user is QAQC Site Engineer"""
    return user.groups.filter(name="QAQC Site Engineer").exists() if user else False


def is_hse_site_engineer(user):
    """Check if user is HSE Site Engineer"""
    return user.groups.filter(name="HSE Site Engineer").exists() if user else False


def get_site_engineer_type(user):
    """
    Get the type of site engineer
    Returns: 'site_engineer', 'billing_site_engineer', 'qaqc_site_engineer',
    'hse_site_engineer', or None
    """
    if not user:
        return None

    try:
        profile = user.profile
        return profile.site_engineer_type
    except Exception:
        # Fallback to group-based detection
        if user.groups.filter(name="Billing Site Engineer").exists():
            return "billing_site_engineer"
        elif user.groups.filter(name="QAQC Site Engineer").exists():
            return "qaqc_site_engineer"
        elif user.groups.filter(name="HSE Site Engineer").exists():
            return "hse_site_engineer"
        elif user.groups.filter(name="Site Engineer").exists():
            return "site_engineer"
        return None
