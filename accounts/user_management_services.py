"""
Shared services for HO / Admin User Management.

Reuses Django auth password hashing, Groups for roles, and existing
Project FK/M2M assignment fields so RBAC access updates automatically.
"""

from __future__ import annotations

from typing import Iterable

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework.exceptions import ValidationError

from accounts.models import UserManagementAuditLog, UserProfile
from accounts.rbac import (
    MANAGEABLE_PROJECT_ROLES,
    ROLE_BILLING_SITE_ENGINEER,
    ROLE_HSE_SITE_ENGINEER,
    ROLE_QAQC_SITE_ENGINEER,
    ROLE_SITE_ENGINEER,
    ROLE_TEAM_LEAD_ALIAS,
    ROLE_TEAM_LEADER,
    is_manageable_project_role,
)
from accounts.utils import get_user_role
from projects.models import Project

User = get_user_model()

# Canonical role → profile site_engineer_type / designation
ROLE_PROFILE_MAP = {
    ROLE_TEAM_LEADER: {
        "designation": "PMC Team Leader",
        "site_engineer_type": None,
    },
    ROLE_SITE_ENGINEER: {
        "designation": "Site Engineer",
        "site_engineer_type": "site_engineer",
    },
    ROLE_BILLING_SITE_ENGINEER: {
        "designation": "Billing Site Engineer",
        "site_engineer_type": "billing_site_engineer",
    },
    ROLE_QAQC_SITE_ENGINEER: {
        "designation": "QA/QC Site Engineer",
        "site_engineer_type": "qaqc_site_engineer",
    },
    ROLE_HSE_SITE_ENGINEER: {
        "designation": "HSE Site Engineer",
        "site_engineer_type": "hse_site_engineer",
    },
}


def normalize_manageable_role(role: str | None) -> str:
    name = (role or "").strip()
    if name == ROLE_TEAM_LEAD_ALIAS:
        name = ROLE_TEAM_LEADER
    if name == "QA/QC Site Engineer":
        name = ROLE_QAQC_SITE_ENGINEER
    if not is_manageable_project_role(name):
        raise ValidationError(
            {
                "role": (
                    "Please select a valid role: Team Leader, Site Engineer, "
                    "Billing Site Engineer, QAQC Site Engineer, or HSE Site Engineer."
                )
            }
        )
    return name


def split_full_name(full_name: str | None) -> tuple[str, str]:
    text = (full_name or "").strip()
    if not text:
        return "", ""
    parts = text.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def apply_full_name(user: User, full_name: str | None) -> None:
    first, last = split_full_name(full_name)
    user.first_name = first
    user.last_name = last


def validate_password_pair(password: str, confirm_password: str | None, user: User | None = None) -> str:
    if password is None or str(password) == "":
        raise ValidationError({"password": "Please enter a password."})
    if confirm_password is not None and password != confirm_password:
        raise ValidationError({"confirm_password": "Passwords do not match."})
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise ValidationError(
            {
                "password": (
                    list(exc.messages)
                    if getattr(exc, "messages", None)
                    else ["Password must meet the required security criteria."]
                )
            }
        ) from exc
    return password


def resolve_projects(project_ids: Iterable | None) -> list[Project]:
    if project_ids is None:
        return []
    if isinstance(project_ids, (str, int)):
        project_ids = [project_ids]
    ids = []
    for raw in project_ids:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            raise ValidationError({"project_ids": "Please select valid projects."})
    if not ids:
        return []
    projects = list(Project.objects.filter(id__in=ids))
    found = {p.id for p in projects}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValidationError(
            {"project_ids": "One or more selected projects could not be found."}
        )
    # Preserve request order
    by_id = {p.id: p for p in projects}
    return [by_id[i] for i in ids]


def set_user_role(user: User, role: str) -> Group:
    role = normalize_manageable_role(role)
    group, _ = Group.objects.get_or_create(name=role)
    # Replace manageable role groups; keep unrelated groups (e.g. staff) intact.
    removable = list(
        user.groups.filter(name__in=list(MANAGEABLE_PROJECT_ROLES) + [ROLE_TEAM_LEAD_ALIAS])
    )
    if removable:
        user.groups.remove(*removable)
    user.groups.add(group)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    meta = ROLE_PROFILE_MAP[role]
    profile.designation = meta["designation"]
    profile.site_engineer_type = meta["site_engineer_type"]
    profile.save(update_fields=["designation", "site_engineer_type", "updated_at"])
    return group


def _clear_user_from_project_slots(user: User, project: Project) -> None:
    changed = False
    if project.team_lead_id == user.id:
        project.team_lead = None
        changed = True
    if project.site_engineer_id == user.id:
        project.site_engineer = None
        changed = True
    if project.billing_site_engineer_id == user.id:
        project.billing_site_engineer = None
        changed = True
    if project.qaqc_site_engineer_id == user.id:
        project.qaqc_site_engineer = None
        changed = True
    if project.hse_site_engineer_id == user.id:
        project.hse_site_engineer = None
        changed = True
    if changed:
        project.save(
            update_fields=[
                "team_lead",
                "site_engineer",
                "billing_site_engineer",
                "qaqc_site_engineer",
                "hse_site_engineer",
                "updated_at",
            ]
        )
    project.site_engineers.remove(user)
    project.assigned_users.remove(user)


def assign_user_to_projects(user: User, projects: list[Project], role: str | None = None) -> list[Project]:
    """
    Assign user to the given projects for their role slot.
    Removes the user from projects that are no longer in the list.
    """
    role = normalize_manageable_role(role or get_user_role(user))
    target_ids = {p.id for p in projects}

    # Clear concrete slots on projects no longer selected for this user.
    for project in Project.objects.filter(Q_team_or_engineer(user)).exclude(id__in=target_ids):
        _clear_user_from_project_slots(user, project)

    for project in projects:
        if role == ROLE_TEAM_LEADER:
            project.team_lead = user
            project.save(update_fields=["team_lead", "updated_at"])
        elif role == ROLE_SITE_ENGINEER:
            project.site_engineer = user
            project.save(update_fields=["site_engineer", "updated_at"])
            project.site_engineers.add(user)
        elif role == ROLE_BILLING_SITE_ENGINEER:
            project.billing_site_engineer = user
            project.save(update_fields=["billing_site_engineer", "updated_at"])
        elif role == ROLE_QAQC_SITE_ENGINEER:
            project.qaqc_site_engineer = user
            project.save(update_fields=["qaqc_site_engineer", "updated_at"])
        elif role == ROLE_HSE_SITE_ENGINEER:
            project.hse_site_engineer = user
            project.save(update_fields=["hse_site_engineer", "updated_at"])
        project.assigned_users.add(user)

    return projects


def Q_team_or_engineer(user: User):
    from django.db.models import Q

    return (
        Q(team_lead=user)
        | Q(site_engineer=user)
        | Q(billing_site_engineer=user)
        | Q(qaqc_site_engineer=user)
        | Q(hse_site_engineer=user)
        | Q(site_engineers=user)
        | Q(assigned_users=user)
    )


def get_assigned_projects_for_user(user: User) -> list[Project]:
    """Projects where this user occupies a concrete assignment slot (not org-wide admin view)."""
    return list(
        Project.objects.filter(Q_team_or_engineer(user)).distinct().order_by("name")
    )


def log_user_management_action(
    *,
    performed_by,
    target_user,
    action: str,
    detail: str = "",
    projects: list[Project] | None = None,
) -> UserManagementAuditLog:
    projects = projects or []
    primary = projects[0] if projects else None
    return UserManagementAuditLog.objects.create(
        performed_by=performed_by if getattr(performed_by, "is_authenticated", False) else None,
        target_user=target_user,
        target_username=getattr(target_user, "username", "") or "",
        target_role=get_user_role(target_user) or "",
        project=primary,
        project_names=", ".join(p.name for p in projects),
        action=action,
        detail=detail,
    )


@transaction.atomic
def create_managed_user(
    *,
    actor,
    username: str,
    password: str,
    confirm_password: str | None,
    role: str,
    project_ids,
    full_name: str | None = None,
    email: str | None = None,
    phone_number: str | None = None,
    is_active: bool = True,
) -> User:
    username = (username or "").strip()
    if not username:
        raise ValidationError({"username": "Please enter a username."})
    if User.objects.filter(username__iexact=username).exists():
        raise ValidationError({"username": "This username is already in use."})

    role = normalize_manageable_role(role)
    projects = resolve_projects(project_ids)
    if not projects:
        raise ValidationError({"project_ids": "Please select at least one project."})

    user = User(username=username, email=(email or "").strip(), is_active=bool(is_active))
    apply_full_name(user, full_name)
    validate_password_pair(password, confirm_password, user=user)
    user.set_password(password)
    user.save()

    set_user_role(user, role)
    if phone_number is not None:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.phone_number = (phone_number or "").strip()
        profile.save(update_fields=["phone_number", "updated_at"])

    assign_user_to_projects(user, projects, role=role)
    log_user_management_action(
        performed_by=actor,
        target_user=user,
        action=UserManagementAuditLog.ACTION_CREATED,
        detail=f"Created {role} and assigned to {len(projects)} project(s).",
        projects=projects,
    )
    return user


@transaction.atomic
def update_managed_user(
    *,
    actor,
    user: User,
    full_name: str | None = None,
    username: str | None = None,
    email: str | None = None,
    phone_number: str | None = None,
    role: str | None = None,
    project_ids=None,
    is_active: bool | None = None,
) -> User:
    # Protect privileged accounts from HO demotion/edit of identity as managed staff
    current_role = get_user_role(user)
    if current_role and not is_manageable_project_role(current_role):
        if user.is_superuser or current_role in {
            "CEO",
            "PMC Head",
            "Head Office",
            "PMC Manager",
        }:
            raise ValidationError(
                {
                    "non_field_errors": (
                        "This account cannot be managed through User Management. "
                        "Only Team Leaders and Engineers can be edited here."
                    )
                }
            )

    if username is not None:
        username = username.strip()
        if not username:
            raise ValidationError({"username": "Please enter a username."})
        if User.objects.filter(username__iexact=username).exclude(pk=user.pk).exists():
            raise ValidationError({"username": "This username is already in use."})
        user.username = username

    if full_name is not None:
        apply_full_name(user, full_name)
    if email is not None:
        user.email = email.strip()
    if is_active is not None:
        user.is_active = bool(is_active)

    user.save()

    if phone_number is not None:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.phone_number = (phone_number or "").strip()
        profile.save(update_fields=["phone_number", "updated_at"])

    effective_role = current_role
    if role is not None:
        effective_role = normalize_manageable_role(role)
        set_user_role(user, effective_role)

    projects = None
    if project_ids is not None:
        projects = resolve_projects(project_ids)
        if not projects:
            raise ValidationError({"project_ids": "Please select at least one project."})
        assign_user_to_projects(user, projects, role=effective_role)

    log_user_management_action(
        performed_by=actor,
        target_user=user,
        action=UserManagementAuditLog.ACTION_UPDATED,
        detail="User details updated.",
        projects=projects or get_assigned_projects_for_user(user),
    )
    return user


@transaction.atomic
def set_managed_user_password(
    *,
    actor,
    user: User,
    password: str,
    confirm_password: str | None,
    action: str = UserManagementAuditLog.ACTION_PASSWORD_CHANGED,
) -> User:
    validate_password_pair(password, confirm_password, user=user)
    user.set_password(password)
    user.save(update_fields=["password"])
    log_user_management_action(
        performed_by=actor,
        target_user=user,
        action=action,
        detail="Password updated by Head Office / Admin.",
        projects=get_assigned_projects_for_user(user),
    )
    return user


@transaction.atomic
def set_managed_user_status(*, actor, user: User, is_active: bool) -> User:
    user.is_active = bool(is_active)
    user.save(update_fields=["is_active"])
    state = "activated" if user.is_active else "deactivated"
    log_user_management_action(
        performed_by=actor,
        target_user=user,
        action=UserManagementAuditLog.ACTION_STATUS_CHANGED,
        detail=f"User {state}.",
        projects=get_assigned_projects_for_user(user),
    )
    return user
