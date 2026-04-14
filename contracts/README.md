# Contract Management Workflow API

Swagger: `https://fv5k8l3m-8000.inc1.devtunnels.ms/swagger/`

Base URL: `https://fv5k8l3m-8000.inc1.devtunnels.ms/api/contracts/`

## Roles (temporary)

For now, permissions use `role` from request body/query (no JWT required for contracts):

- **Billing Site Engineer**
  - Can: create/update contracts
- **CEO**
  - Can: approve/reject contracts
  - Can: view all contracts via `/all/`

## Endpoints

### 1) Create Contract (Billing Site Engineer)

`POST /api/contracts/`

Body:
```json
{
  "role": "Billing Site Engineer",
  "project_name": "Project Alpha",
  "original_contract_value": 1000000,
  "approved_vo": 50000,
  "pending_vo": 25000,
  "created_by": "Billing SE 1"
}
```

Notes:
- Status is always set to `pending` when created.

### 2) Dashboard Contracts (Approved Only)

`GET /api/contracts/`

Returns only `approved` contracts (dashboard-ready response).

### 3) Admin View - All Contracts (CEO only)

`GET /api/contracts/all/?role=CEO`

### 4) Approve Contract (CEO by Project Name)

`POST /api/contracts/approve/`

Body:
```json
{
  "role": "CEO",
  "project_name": "Project Alpha"
}
```

Behavior:
- Approves the **latest pending** contract for that project.
- Calculates:
  - `revised_contract_value = original_contract_value + approved_vo`
  - `approved_vo_percentage = (approved_vo / original_contract_value) * 100`

### 5) Reject Contract (CEO by Project Name)

`POST /api/contracts/reject/`

Body:
```json
{
  "role": "CEO",
  "project_name": "Project Alpha"
}
```

Behavior:
- Rejects the **latest pending** contract for that project.

### 6) Dashboard Summary Totals (Approved Only)

`GET /api/contracts/summary/`

Response:
```json
{
  "original_contract_value_total": 0,
  "approved_vo_total": 0,
  "revised_contract_value_total": 0,
  "pending_vo_total": 0
}
```

## Contracts Module

### Overview

The Contract module manages the complete contract workflow lifecycle, from creation through approval/rejection. It handles financial contract data including variation orders (VOs) and provides workflow state management for Billing Site Engineers and CEO approval processes.

### Key Fields

#### Input Fields (Editable)
| Field | Type | Description |
|-------|------|-------------|
| `project_name` | CharField | Project identifier (indexed for fast queries) |
| `original_contract_value` | Decimal(18,2) | Base contract amount (≥ 0) |
| `approved_vo` | Decimal(18,2) | Approved variation orders (≥ 0) |
| `pending_vo` | Decimal(18,2) | Pending variation orders (≥ 0) |
| `created_by` | CharField | User creating the contract |

#### Calculated Fields (Read-Only)
| Field | Type | Description |
|-------|------|-------------|
| `revised_contract_value` | Decimal(18,2) | `original_contract_value + approved_vo` |
| `approved_vo_percentage` | Decimal(10,4) | `(approved_vo / original_contract_value) * 100` |

#### Metadata Fields
| Field | Type | Description |
|-------|------|-------------|
| `status` | CharField | Workflow state (Draft/Pending/Approved/Rejected) |
| `approved_by` | CharField | User who approved (CEO) |
| `created_at` | DateTime | Creation timestamp (indexed) |
| `updated_at` | DateTime | Last update timestamp |

### Workflow Explanation

#### Contract Lifecycle
1. **Draft**: Initial state (not currently used in API)
2. **Pending**: Created by Billing Site Engineer, awaiting CEO approval
3. **Approved**: CEO-approved with calculated financial values stored
4. **Rejected**: CEO-rejected, no calculations performed

#### Role Responsibilities
- **Billing Site Engineer**: Can create contracts (auto-sets to Pending)
- **CEO**: Can approve/reject pending contracts, view all contracts

### Calculations

#### Approval Calculations (CEO Action)
When a contract is approved, these calculations are performed and stored:

```python
# Revised contract value
revised_contract_value = original_contract_value + approved_vo

# Variation order percentage
approved_vo_percentage = (approved_vo / original_contract_value) * 100
```

#### Calculation Notes
- Calculations only occur on **approval** (status = APPROVED)
- Values are **frozen** in the database for audit trails
- All calculations use `Decimal` for financial precision
- Percentages stored with 4 decimal places for accuracy

### Performance Optimizations

#### Database Indexing
- `project_name`: Indexed for fast project-based queries
- `created_at`: Indexed for time-based sorting and filtering
- Composite indexes: `(project_name, -created_at)` and `(status, -created_at)`

#### Financial Precision
- **Decimal Fields**: All monetary values use `DecimalField` to prevent floating-point errors
- **Validation**: `MinValueValidator(0)` prevents negative financial values
- **Normalization**: `project_name` automatically stripped of whitespace

#### Query Performance
- **Stored Calculations**: Pre-computed values reduce runtime calculations
- **Selective Indexing**: Optimized for common query patterns
- **Efficient Workflow**: Calculations only on state changes

## Filtering

List endpoint supports:

- `GET /api/contracts/?project_name=Alpha` (case-insensitive contains)
- `GET /api/contracts/?date=YYYY-MM-DD` (filters by created date)

## Developer Notes

### Calculation Location
⚠️ **Important**: Contract calculations happen in the ViewSet approve action, not in the model save method.

**Why in ViewSet?**
- Calculations are **workflow-dependent** (only on CEO approval)
- Model save() focuses on data integrity and normalization
- Clear separation between data validation and business logic

### Model Responsibilities
The Contract model handles:
- **Data Validation**: Financial field constraints
- **Normalization**: project_name whitespace handling
- **Indexing**: Optimized database queries
- **Status Defaults**: Auto-setting Pending for new contracts

### ViewSet Responsibilities
The Contract ViewSet handles:
- **Workflow Logic**: Approval/rejection state transitions
- **Calculations**: Financial computations on approval
- **Role-Based Access**: Permission checks for different user roles

### Warning: Business Logic Changes
⚠️ **Never modify calculation formulas without thorough testing**
- Financial calculations affect reporting and billing
- Changes should be reviewed by finance and legal teams
- Always test with existing approved contracts

### Best Practices

#### Contract Creation
- Always provide `original_contract_value > 0`
- Set appropriate `approved_vo` and `pending_vo` values
- Include meaningful `created_by` for audit trails

#### Financial Data Handling
- Never allow negative monetary values
- Use Decimal types consistently in calculations
- Validate all financial inputs before processing

#### Workflow Management
- Respect the approval workflow (Pending → Approved/Rejected)
- Only CEO can change contract status after creation
- Maintain audit trail with `approved_by` field

#### Performance Considerations
- Use appropriate filtering to reduce result sets
- Leverage database indexes for fast queries
- Consider pagination for large contract lists

## Contract Serializer

### Overview

The `ContractSerializer` handles serialization and validation for contract workflow data. It enforces the contract creation workflow while ensuring data integrity and providing appropriate read/write permissions for different fields.

### Purpose and Design

- **Workflow Enforcement**: Automatically sets contract status to PENDING on creation
- **Data Validation**: Comprehensive validation of monetary values and project information
- **Read/Write Permissions**: Clear separation between user-editable and system-calculated fields
- **Normalization**: Consistent data formatting and validation

### Input Fields (Editable)

| Field | Type | Validation | Required | Description |
|-------|------|------------|----------|-------------|
| `project_name` | CharField | Not blank, stripped | Yes | Project identifier |
| `original_contract_value` | Decimal | > 0 | Yes | Base contract amount |
| `approved_vo` | Decimal | ≥ 0, defaults to 0 | No | Approved variation orders |
| `pending_vo` | Decimal | ≥ 0, defaults to 0 | No | Pending variation orders |
| `created_by` | CharField | Required | Yes | User creating the contract |

### Read-Only Fields (Calculated/System)

| Field | Type | Description |
|-------|------|-------------|
| `id` | Integer | Auto-generated primary key |
| `revised_contract_value` | Decimal | `original + approved_vo` (CEO approval) |
| `approved_vo_percentage` | Decimal | `(approved_vo / original) * 100` (CEO approval) |
| `status` | CharField | Workflow state (always PENDING on create) |
| `approved_by` | CharField | CEO who approved/rejected |
| `created_at` | DateTime | Creation timestamp |
| `updated_at` | DateTime | Last modification timestamp |

### Validation Rules

#### Field-Specific Validation
- **project_name**: Cannot be blank, automatically stripped of whitespace
- **original_contract_value**: Must be greater than 0 (required for percentage calculations)
- **approved_vo/pending_vo**: Must be ≥ 0, defaults to 0 if not provided

#### Reusable Validation Logic
The serializer uses a `_validate_non_negative_decimal()` helper method for consistent validation of monetary fields:
- Null values default to `Decimal("0")`
- Negative values are rejected with field-specific error messages
- Maintains consistent validation behavior across similar fields

#### Cross-Field Validation
The `validate()` method ensures:
- All monetary values are consistently stored as Decimal types
- Automatic conversion from string inputs to Decimal
- Consistent data typing across the API

### Workflow Logic

#### Contract Creation
- **Status Override**: Any provided `status` field is ignored
- **Forced PENDING**: New contracts are always created with `status = "pending"`
- **Default Values**: Monetary fields default to 0 if not provided
- **User Attribution**: `created_by` field is required and preserved

#### Business Rule Enforcement
- **Immutable Status**: Status cannot be set directly via API (controlled by workflow actions)
- **Calculated Fields Protection**: Read-only fields prevent direct modification
- **Audit Trail**: `created_by` and `approved_by` maintain accountability

### Performance Optimizations

#### Efficient Validation
- **Reusable Helpers**: `_validate_non_negative_decimal()` eliminates code duplication
- **Centralized Logic**: `validate()` method handles cross-field concerns
- **Type Consistency**: Decimal conversion ensures consistent processing

#### Memory Optimization
- **Minimal Overhead**: Lightweight validation methods
- **No Unnecessary Operations**: Defaults handled efficiently
- **Clean Architecture**: Separation of concerns between validation and business logic

### Developer Notes

#### Calculation Location
⚠️ **Important**: Contract calculations (`revised_contract_value`, `approved_vo_percentage`) are handled in the ViewSet approve action, not in the serializer.

**Why in ViewSet?**
- Calculations are **workflow-triggered** (only on CEO approval)
- ViewSet has access to business logic and validation
- Serializer focuses on data validation and formatting
- Clear separation between data integrity and business calculations

#### Serializer Responsibilities
- **Input Validation**: Ensure data quality before model creation
- **Type Conversion**: Consistent Decimal handling for monetary values
- **Normalization**: Standardize input formats (project_name stripping)
- **Workflow Enforcement**: Status control and defaults

#### Warning: Logic Separation
⚠️ **Never add calculation logic to the serializer**
- Business calculations belong in workflow actions (ViewSet)
- Serializer should remain focused on validation and serialization
- Changes to calculations must be tested against existing approved contracts

### Best Practices

#### API Usage
- **Provide project_name**: Always include meaningful project identifiers
- **Validate Amounts**: Ensure monetary values are reasonable and positive
- **Accept Defaults**: Rely on automatic defaults for optional fields
- **Workflow Respect**: Don't attempt to set status or calculated fields via API

#### Data Integrity
- **Consistent Formatting**: Use stripped project names for consistency
- **Type Safety**: Rely on Decimal types for all financial calculations
- **Validation Coverage**: All monetary inputs are validated for reasonableness
- **Audit Preservation**: created_by field maintains accountability

#### Development Guidelines
- **Test Validation**: Verify all validation rules work as expected
- **Check Defaults**: Ensure optional fields get appropriate defaults
- **Validate Workflow**: Confirm status handling works correctly
- **Maintain Compatibility**: Changes should not break existing API consumers

## Contract ViewSet

### Overview

The `ContractViewSet` provides RESTful API endpoints for managing contract workflow with comprehensive role-based access control. It implements the complete contract lifecycle from creation through approval/rejection with optimized performance and caching.

### Supported Endpoints

| Method | Endpoint | Description | Access |
|--------|----------|-------------|--------|
| `POST` | `/api/contracts/` | Create new contract (status=pending) | Billing Site Engineer |
| `GET` | `/api/contracts/` | List approved contracts (dashboard) | All authenticated roles |
| `GET` | `/api/contracts/{id}/` | Retrieve single contract | CEO (all), others (approved only) |
| `PUT` | `/api/contracts/{id}/` | Update contract (if not approved) | Billing Site Engineer |
| `PATCH` | `/api/contracts/{id}/` | Partial update contract | Billing Site Engineer |
| `DELETE` | `/api/contracts/{id}/` | Delete contract | Billing Site Engineer |
| `POST` | `/api/contracts/approve/` | CEO approve latest pending contract | CEO |
| `POST` | `/api/contracts/reject/` | CEO reject latest pending contract | CEO |
| `GET` | `/api/contracts/summary/` | Dashboard totals (approved contracts) | All roles |
| `GET` | `/api/contracts/all/` | Admin view (all contracts) | PMC Head, Coordinator, Billing Site Engineer, CEO |

### Role-Based Access Control

#### Permission Matrix
- **Billing Site Engineer**: Full CRUD access (create, read, update, delete)
- **PMC Head**: Read access to all contracts, can see full dashboard
- **CEO**: Read access to all contracts, approve/reject permissions
- **Coordinator**: Read access to approved contracts
- **Unauthorized**: Access denied

#### Role Input Methods
Roles can be provided via:
- **Query Parameter**: `?role=billing site engineer`
- **HTTP Header**: `X-Role: billing site engineer`

Role input is **case-insensitive** and automatically normalized:
- `"pmc head"` → `"PMC Head"`
- `"CEO"` → `"CEO"`
- `"billing site engineer"` → `"Billing Site Engineer"`

### Filtering Options

#### List Endpoint Filtering
| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `project_name` | string | Case-insensitive partial match | `?project_name=highway` |
| `date` | string | Filter by creation date (YYYY-MM-DD) | `?date=2024-01-15` |
| `role` | string | User role (case-insensitive) | `?role=pmc head` |

#### Access Control Notes
- **Regular users** (Coordinator): See only approved contracts
- **Privileged users** (PMC Head, CEO): See all contracts in list view
- **CEO**: Can retrieve any contract by ID
- **Others**: Can only retrieve approved contracts

### Workflow Logic

#### Contract Creation
- **Status**: Automatically set to `PENDING`
- **Override Protection**: Explicitly prevents any status override
- **Validation**: Full business rule validation
- **User Tracking**: Records `created_by` user

#### Approval Process
- **Target**: Latest PENDING contract for project
- **Calculations**: Automatic computation of financial metrics
- **Status Change**: `PENDING` → `APPROVED`
- **Audit Trail**: Records `approved_by` as "CEO"

#### Rejection Process
- **Target**: Latest PENDING contract for project
- **Status Change**: `PENDING` → `REJECTED`
- **Audit Trail**: Records `approved_by` as "CEO"

### Performance Optimizations

#### Query Optimization
- **Field Selection**: Uses `.only()` to load only required fields
- **Action-Based Filtering**: Different queryset logic for list vs retrieve
- **Memory Efficiency**: Reduced database I/O and memory usage

#### Caching Strategy
- **List Endpoint**: 5-minute cache with role and filter-based keys
- **Summary Endpoint**: 5-minute cache for dashboard totals
- **Cache Keys**: `contracts_list:{params}` and `contracts_summary:{params}`
- **Invalidation**: Automatic cache clearing on create/update/approve/reject

#### Role Extraction Optimization
- **Request-Level Caching**: Role extracted once in `initial()` method
- **Per-Request Efficiency**: Reused across all permission checks
- **Reduced Overhead**: Eliminates multiple role parsing operations

### Developer Notes

#### Role Extraction Logic
Role extraction happens in the `initial()` method and is cached per request:
```python
def initial(self, request, *args, **kwargs):
    super().initial(request, *args, **kwargs)
    self._cached_role = _get_role_from_request(request)
```

#### Permission Checking
Permissions are checked using cached roles:
```python
def _check_billing_engineer_permission(self, request, action_name):
    role = self._get_role_from_cache()
    # Check against allowed roles
```

#### Calculation Location
Financial calculations (`revised_contract_value`, `approved_vo_percentage`) are performed in the ViewSet approve action:
- **Workflow-Timed**: Only executed on CEO approval
- **Audit Trail**: Values are frozen in database
- **Decimal Precision**: All calculations use Decimal for accuracy

#### Cache Management
Cache invalidation occurs on all write operations:
```python
def _invalidate_contract_cache(self):
    cache.delete_pattern("contracts_list:*")
    cache.delete_pattern("contracts_summary:*")
```

### Best Practices

#### API Usage
- **Always provide role**: Include `?role=...` for testing and production
- **Use appropriate endpoints**: Dashboard for approved contracts, admin for all
- **Handle 403 errors**: Check role parameter when access is denied
- **Respect workflow**: Don't attempt to modify approved contracts

#### Performance Considerations
- **Leverage caching**: Repeated requests are served from cache
- **Use filtering**: Reduce response size with appropriate filters
- **Role awareness**: Different roles see different data scopes
- **Pagination**: Large result sets are automatically paginated

#### Development Guidelines
- **Test with different roles**: Verify access control for all user types
- **Check cache behavior**: Ensure updates appear immediately
- **Validate calculations**: Confirm financial computations are accurate
- **Monitor performance**: Use appropriate filtering to avoid large datasets

