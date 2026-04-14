# Contract Performance Module

## Overview

The Contract Performance module tracks and calculates Earned Value Management (EVM) metrics for construction contracts. It provides real-time performance analysis with automated status classification based on earned value percentages.

## Key Features

- **Earned Value Tracking**: Monitors work completed vs. work paid for
- **Automated Calculations**: All percentages and variances calculated automatically
- **Performance Status**: Color-coded status (Red/Yellow/Green) based on thresholds
- **Financial Precision**: Uses Decimal fields for accurate monetary calculations

## Data Model

### Core Fields

| Field | Type | Description |
|-------|------|-------------|
| `project_name` | CharField | Project identifier (indexed) |
| `contract_value` | Decimal(18,2) | Total contract value |
| `earned_value` | Decimal(18,2) | Value of work completed |
| `actual_billed` | Decimal(18,2) | Amount actually billed |

### Calculated Fields

| Field | Type | Description |
|-------|------|-------------|
| `earned_value_percentage` | Decimal(10,4) | `earned_value / contract_value * 100` |
| `actual_billed_percentage` | Decimal(10,4) | `actual_billed / contract_value * 100` |
| `variance` | Decimal(18,2) | `earned_value - actual_billed` |
| `variance_percentage` | Decimal(10,4) | `variance / contract_value * 100` |
| `performance_status` | CharField | Red/Yellow/Green based on thresholds |

## Calculations

### Percentage Calculations
```python
earned_value_percentage = (earned_value / contract_value) * 100
actual_billed_percentage = (actual_billed / contract_value) * 100
variance_percentage = ((earned_value - actual_billed) / contract_value) * 100
```

### Variance Calculation
```python
variance = earned_value - actual_billed
# Can be negative if actual_billed > earned_value
```

## Performance Status Thresholds

| Status | Range | Description |
|--------|-------|-------------|
| **Red** | < 90% | Poor performance - significant underperformance |
| **Yellow** | 90% - 99% | Moderate performance - needs attention |
| **Green** | ≥ 100% | Good performance - meeting or exceeding targets |

### Status Logic
```python
if earned_value_percentage < 90:
    status = "red"
elif 90 <= earned_value_percentage < 100:
    status = "yellow"
else:  # >= 100
    status = "green"
```

## Usage Examples

### Creating a Performance Record
```python
from contract_performance.models import ContractPerformance
from decimal import Decimal

record = ContractPerformance.objects.create(
    project_name="Highway Project A",
    contract_value=Decimal("5000000.00"),
    earned_value=Decimal("4500000.00"),
    actual_billed=Decimal("4200000.00"),
    created_by="billing_engineer"
)

# Automatically calculated:
# earned_value_percentage = 90.0000
# actual_billed_percentage = 84.0000
# variance = 300000.00
# variance_percentage = 6.0000
# performance_status = "yellow"
```

## API Endpoints

### List/Create Contract Performance
```
GET/POST /api/contract-performance/
```
- **GET**: List all performance records (newest first)
- **POST**: Create new performance record with automatic calculations

### Retrieve/Update/Delete
```
GET/PUT/PATCH/DELETE /api/contract-performance/{id}/
```

## Database Optimizations

### Indexing Strategy
- `project_name`: Indexed for fast filtering
- `created_at`: Indexed for time-based queries
- Composite index: `(project_name, -created_at)` for dashboard queries
- Composite index: `(performance_status, -created_at)` for status reports

### Precision Handling
- **Decimal Fields**: All financial calculations use Decimal for precision
- **No Float Conversions**: Avoids floating-point rounding errors
- **Conditional Updates**: Recalculations only when base values change

## Business Logic Notes

### Important Considerations
- **Negative Variance**: Allowed and preserved (when actual_billed > earned_value)
- **Zero Contract Value**: Handled gracefully (percentages set to 0)
- **Precision**: All calculations maintain 4 decimal places for accuracy

### Data Integrity
- **Uniqueness**: `(project_name, month_year)` constraint (if month_year added)
- **Validation**: MinValue validators on financial fields
- **Normalization**: project_name automatically stripped

## Development Guidelines

### Calculations Location
All derived field calculations happen in the model's `save()` method:
- Ensures consistency across all creation/update paths
- Prevents calculation drift between different API endpoints

### Warning: Logic Changes
⚠️ **Never modify calculation formulas without impact analysis**
- Used by dashboards and financial reporting
- Changes affect historical data interpretation
- Requires testing against existing records

### Testing Requirements
- Verify calculations match expected results
- Test edge cases (zero values, negative variance)
- Ensure status thresholds work correctly
- Validate API responses unchanged

## Performance Characteristics

- **Calculation Efficiency**: Conditional updates prevent unnecessary work
- **Query Performance**: Indexed fields for fast retrieval
- **Memory Usage**: Minimal - calculations done in-place
- **Scalability**: Suitable for large numbers of projects

## Contract Performance Serializer

### Purpose and Design

The `ContractPerformanceSerializer` handles serialization and validation for contract performance data. It follows a clear separation of concerns:

- **Input Fields**: `project_name`, `contract_value`, `earned_value`, `actual_billed`, `created_by`, `updated_by`
- **Calculated Fields**: All percentage and variance fields are read-only and computed by the model
- **Validation**: Ensures data integrity before saving to the database

### Field Configuration

#### Input Fields (Editable)
| Field | Type | Validation | Description |
|-------|------|------------|-------------|
| `project_name` | CharField | Required, stripped | Project identifier |
| `contract_value` | Decimal | > 0 | Total contract value |
| `earned_value` | Decimal | ≥ 0 | Value of completed work |
| `actual_billed` | Decimal | ≥ 0 | Amount actually billed |
| `created_by` | CharField | Required | User creating record |
| `updated_by` | CharField | Optional | User updating record |

#### Calculated Fields (Read-Only)
| Field | Type | Description |
|-------|------|-------------|
| `earned_value_percentage` | Decimal | `(earned_value / contract_value) * 100` |
| `actual_billed_percentage` | Decimal | `(actual_billed / contract_value) * 100` |
| `variance` | Decimal | `earned_value - actual_billed` |
| `variance_percentage` | Decimal | `(variance / contract_value) * 100` |
| `performance_status` | CharField | Red/Yellow/Green status |
| `performance_status_display` | CharField | Human-readable status |

### Validation Rules

#### Field-Specific Validation
- **contract_value**: Must be greater than 0 (required for percentage calculations)
- **earned_value**: Must be ≥ 0 (can be 0 for projects just started)
- **actual_billed**: Must be ≥ 0 (can be 0 if no billing yet)
- **project_name**: Cannot be blank, automatically stripped of whitespace

#### Reusable Validation Logic
The serializer uses a helper method `_validate_non_negative_decimal()` for consistent validation of monetary fields, ensuring:
- Null values default to `Decimal("0")`
- Negative values are rejected with appropriate error messages
- Consistent error messaging across fields

### Read-Only Fields Behavior

All calculated fields are marked as `read_only=True` in the serializer:
- **Purpose**: Prevents clients from attempting to set calculated values
- **Model Responsibility**: Calculations happen in the model's `save()` method
- **Consistency**: Ensures calculations are always correct regardless of input source

### performance_status_display Field

This SerializerMethodField provides a human-readable version of the performance status:
- **Source**: `get_performance_status_display()` method from the model
- **Purpose**: Converts enum values to display strings (e.g., "Red (< 90%)")
- **Usage**: Frontend can display user-friendly status descriptions

## Serializer Optimizations

### Decimal Handling
- **Consistent Types**: All monetary values use Decimal throughout validation and serialization
- **Precision Preservation**: No unnecessary float conversions that could introduce rounding errors
- **Model Alignment**: Matches the model's DecimalField precision settings

### Code Quality Improvements
- **DRY Principle**: Reusable `_validate_non_negative_decimal()` helper method
- **Consistent Validation**: Standardized error messages and validation logic
- **Clean Separation**: Input validation separate from calculated field handling

### Context Handling
- **updated_by Extraction**: Safely extracts `updated_by` from serializer context
- **Backward Compatibility**: Maintains support for request.data fallback
- **Clean Defaults**: Uses `extra_kwargs` for required field configuration

## Developer Notes

### Calculation Location
⚠️ **Important**: All business logic calculations happen in the model's `save()` method, not in the serializer.

**Why not in serializer?**
- **Consistency**: Ensures calculations happen regardless of how the model is saved
- **Testing**: Easier to test model logic independently
- **Maintenance**: Single source of truth for calculation formulas

### Serializer Responsibilities
- **Validation Only**: Input validation and type conversion
- **Serialization**: Converting model instances to JSON responses
- **Context Passing**: Safely passing user context (created_by, updated_by)

### Warning: Serializer Logic Changes
⚠️ **Never add calculation logic to the serializer**
- Serializer should remain lightweight and focused on validation/serialization
- Business logic belongs in the model
- Changes to serializer validation must be thoroughly tested

### Testing Recommendations
- **Unit Tests**: Test validation methods individually
- **Integration Tests**: Verify end-to-end serialization with model calculations
- **Edge Cases**: Test null values, zero values, and boundary conditions
- **Backward Compatibility**: Ensure existing API responses remain unchanged

## Contract Performance ViewSet

### Overview

The `ContractPerformanceViewSet` provides RESTful API endpoints for managing contract performance records with role-based access control. It implements comprehensive CRUD operations with filtering, pagination, caching, and performance optimizations.

### Supported Endpoints

| Method | Endpoint | Description | Access |
|--------|----------|-------------|--------|
| `GET` | `/api/contract-performance/` | List all records with filtering | Billing Site Engineer, PMC Head, CEO, Coordinator |
| `POST` | `/api/contract-performance/` | Create new record | Billing Site Engineer only |
| `GET` | `/api/contract-performance/{id}/` | Retrieve single record | Billing Site Engineer, PMC Head, CEO, Coordinator |
| `PUT` | `/api/contract-performance/{id}/` | Full update | Billing Site Engineer only |
| `PATCH` | `/api/contract-performance/{id}/` | Partial update | Billing Site Engineer only |
| `DELETE` | `/api/contract-performance/{id}/` | Delete record | Billing Site Engineer only |

### Role-Based Access Control

#### Access Levels
- **Billing Site Engineer**: Full CRUD access (create, read, update, delete)
- **PMC Head, CEO, Coordinator**: Read-only access (list, retrieve)
- **Invalid/Unknown roles**: Access denied with 403 Forbidden

#### Role Input Methods
Roles can be provided via:
- **Query Parameter**: `?role=billing site engineer`
- **HTTP Header**: `X-Role: billing site engineer`

Role input is **case-insensitive** and automatically normalized:
- `"pmc head"` → `"PMC Head"`
- `"CEO"` → `"CEO"`
- `"billing site engineer"` → `"Billing Site Engineer"`

### Filtering Options

The list endpoint supports comprehensive filtering:

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `project_name` | string | Case-insensitive partial match | `?project_name=highway` |
| `date` | string | Filter by creation date (YYYY-MM-DD) | `?date=2024-01-15` |
| `performance_status` | string | Filter by status (red/yellow/green) | `?performance_status=red` |
| `page` | integer | Pagination page number | `?page=2` |
| `page_size` | integer | Records per page (max 100) | `?page_size=50` |

### Performance Optimizations

#### Query Optimization
- **Field Selection**: Uses `.only()` to fetch only required fields, reducing memory usage
- **Action-Based Filtering**: Filtering applied only for list endpoint, retrieve gets full queryset
- **Database Ordering**: Efficient database-level sorting instead of Python sorting

#### Caching Strategy
- **List Endpoint**: 5-minute cache with query parameter-based keys
- **Cache Keys**: `contract_performance_list:{filter_params}`
- **Cache Invalidation**: Automatic clearing on create/update/delete operations

#### Pagination Support
- **Page Size**: Default 20 records, configurable up to 100
- **Response Format**: Compatible with frontend expectations
- **Memory Efficient**: Large datasets handled gracefully

### Developer Notes

#### Role Extraction Logic
Role extraction happens in the `initial()` method and is cached per request:
```python
def initial(self, request, *args, **kwargs):
    super().initial(request, *args, **kwargs)
    self._cached_role = _get_role_from_request(request)
```

#### Permission Checking
Permissions are checked using cached roles to avoid redundant extraction:
```python
def _check_billing_engineer_permission(self, request, action_name):
    role = self._get_role_from_cache()
    # Check role against allowed values
```

#### Warning: Logic Changes
⚠️ **Never modify role validation logic without thorough testing**
- Role mappings affect security and access control
- Changes should be reviewed by security team
- Test all role variations and edge cases

### Best Practices

#### API Usage
- **Always provide role**: Include `?role=...` in requests for testing
- **Use query parameters**: Preferred for GET requests
- **Handle 403 errors**: Check role parameter when access is denied

#### Performance Considerations
- **Use filtering**: Reduce response size with appropriate filters
- **Pagination**: Use for large result sets
- **Cache awareness**: Responses may be cached for 5 minutes

#### Development Guidelines
- **Test with different roles**: Verify access control works for all user types
- **Check cache invalidation**: Ensure updates appear immediately
- **Validate pagination**: Test with different page sizes and large datasets

## Migration History

- **Initial**: Basic FloatField implementation
- **Optimization**: DecimalField conversion + indexing improvements
- **ViewSet Enhancement**: Caching, pagination, role optimization, and performance improvements
- **Future**: Potential month_year field addition for time-series analysis