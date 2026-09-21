# User Roles Setup Guide

## Roles Created

The system now supports the following roles:

1. **PMC Head** - Full system access and project oversight
2. **CEO** - Executive level access to all projects and reports
3. **Coordinator** - Manages project coordination and communication
4. **Team Leader** - Leads project teams and manages project execution
5. **Site Engineer** - General site engineering and project execution
6. **Billing Site Engineer** - Handles billing, invoicing, and financial aspects
7. **QAQC Site Engineer** - Quality Assurance and Quality Control

## Setup Instructions

### Step 1: Run Migrations

```bash
cd backend
python manage.py migrate accounts
```

### Step 2: Create Roles (Group)

```bash
python manage.py create_roles
```

This will create all 7 role groups in Django.

### Step 3: Assign Roles to Users

#### Option A: Using Django Admin

1. Go to Django Admin: `http://localhost:8000/admin/`
2. Navigate to **Users** → Select a user
3. In the **Groups** section, assign the appropriate role(s)
4. If the user is a Site Engineer, go to **User Profiles** and set the `site_engineer_type`:
   - `site_engineer` - Regular Site Engineer
   - `billing_site_engineer` - Billing Site Engineer
   - `qaqc_site_engineer` - QAQC Site Engineer

#### Option B: Using Django Shell

```python
from django.contrib.auth.models import User, Group
from accounts.models import UserProfile

# Get user
user = User.objects.get(username='username')

# Assign role (group)
role_group = Group.objects.get(name='Site Engineer')
user.groups.add(role_group)

# If Site Engineer, set type
profile = user.profile
profile.site_engineer_type = 'billing_site_engineer'  # or 'qaqc_site_engineer' or 'site_engineer'
profile.save()
```

## Role Priority

When a user has multiple roles, the system uses this priority order:

1. CEO
2. PMC Head
3. Team Leader
4. Coordinator
5. Billing Site Engineer
6. QAQC Site Engineer
7. Site Engineer

The highest priority role becomes the "primary role" for the user.

## API Response

The User API now returns:

```json
{
  "id": 1,
  "username": "john_doe",
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "groups": ["Site Engineer"],
  "primary_role": "Site Engineer",
  "role_display": "Site Engineer",
  "site_engineer_type": "Billing Site Engineer",
  "profile": {
    "site_engineer_type": "billing_site_engineer",
    "phone_number": "",
    "designation": "",
    "department": ""
  }
}
```

## Frontend Integration

The frontend `types.ts` has been updated with all new roles:

```typescript
export enum UserRole {
  PMC_HEAD = 'PMC_HEAD',
  CEO = 'CEO',
  COORDINATOR = 'COORDINATOR',
  TEAM_LEAD = 'TEAM_LEAD',
  SITE_ENGINEER = 'SITE_ENGINEER',
  BILLING_SITE_ENGINEER = 'BILLING_SITE_ENGINEER',
  QAQC_SITE_ENGINEER = 'QAQC_SITE_ENGINEER'
}
```

## Utility Functions

Backend utility functions available in `accounts/utils.py`:

- `get_user_role(user)` - Get primary role
- `is_pmc_head(user)` - Check if PMC Head
- `is_ceo(user)` - Check if CEO
- `is_team_leader(user)` - Check if Team Leader
- `is_coordinator(user)` - Check if Coordinator
- `is_site_engineer(user)` - Check if any Site Engineer type
- `is_billing_site_engineer(user)` - Check if Billing Site Engineer
- `is_qaqc_site_engineer(user)` - Check if QAQC Site Engineer
- `get_site_engineer_type(user)` - Get Site Engineer subtype

## Usage in Views

```python
from accounts.utils import get_user_role, is_ceo, is_pmc_head

def my_view(request):
    user = request.user
    role = get_user_role(user)
    
    if is_ceo(user) or is_pmc_head(user):
        # Full access
        pass
    elif is_site_engineer(user):
        # Site engineer access
        pass
```

## Notes

- UserProfile is automatically created when a User is created (via signals)
- Site Engineer types are stored in UserProfile, not in groups
- A user can have multiple groups, but only one primary role (highest priority)
- Site Engineer subtypes (Billing, QAQC) are separate groups AND stored in profile
