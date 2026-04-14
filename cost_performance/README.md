# Project Cost Performance (EVM)

Earned Value Management (EVM) tracking per project per month. Now uses proper relational data model with ForeignKey to Project.

## Data Model Improvements

- **ForeignKey Relationship**: Uses `Project` model instead of string `project_name`
- **Data Integrity**: Enforced referential integrity and constraints
- **Performance**: Indexed ForeignKey lookups for better query performance
- **Automatic Project Creation**: New projects are created automatically if they don't exist

## Endpoints

- `POST /api/cost-performance/`
- `GET /api/cost-performance/?project_name=` (optional filter)
- `GET /api/cost-performance/dashboard/?project_name=` (required)

## POST body

| Field | Description |
|-------|-------------|
| `project_name` | **string** - Project name (creates Project object if doesn't exist) |
| `month_year` | `Jan-2023` format |
| `bcws` | Planned cost (BCWS) ≥ 0 |
| `bcwp` | Earned value (BCWP) ≥ 0 |
| `acwp` | Actual cost (ACWP) ≥ 0 |
| `fcst` | Forecast remaining cost ≥ 0 |
| `bac` | Optional; if set, **VAC** = BAC − EAC |

**Computed (not in POST):** `eac`, `cv`, `sv`, `cpi`, `vac`

- **EAC** = ACWP + FCST  
- **CV** = BCWP − ACWP (negative → over budget on cost)  
- **SV** = BCWP − BCWS (negative → behind schedule)  
- **CPI** = BCWP / ACWP (omitted if ACWP = 0)  
- **VAC** = BAC − EAC when `bac` provided  

## Dashboard

Parallel arrays: `months`, `bcws`, `bcwp`, `acwp`, `fcst`, `eac`, `cv`, `sv`, plus `cpi`, `vac`, `over_budget_cost`, `behind_schedule`.

## Enhanced EVM Dashboard (POST)

Compute complete EVM metrics from monthly data with BAC input.

**Request:**
```json
{
  "project_name": "Project Alpha",
  "bac": 1000000,
  "monthly_data": [
    {
      "month": "Jan-2022",
      "bcws": 100000,
      "percent_complete": 50,
      "bcwp": 50000,
      "ac": 55000
    }
  ]
}
```

**Response:**
- `summary` - Final BCWP, AC, CV, CPI, EAC, ETC
- `monthly` - Month-by-month computed metrics
- `cumulative` - Running totals

## Data Relationships

- **ProjectCostPerformance** → **Project** (ForeignKey)
- Automatic Project creation when `project_name` provided
- Unique constraint on (project, month_year)

Swagger tag: **Cost performance (EVM)**.

# Project Cost Performance Module

## Overview

The Project Cost Performance module implements Earned Value Management (EVM) calculations for tracking project cost performance metrics on a monthly basis. It provides real-time cost variance analysis and performance indicators for project monitoring and control.

## Key Features

- **EVM Calculations**: Automated computation of cost performance metrics
- **Monthly Tracking**: Time-series analysis of project cost performance
- **Performance Indicators**: Cost Variance (CV), Schedule Variance (SV), Cost Performance Index (CPI)
- **Forecasting**: Estimate at Completion (EAC) and Variance at Completion (VAC)
- **Precision**: Decimal-based calculations for financial accuracy

## Data Model

### Core Fields

| Field | Type | Description |
|-------|------|-------------|
| `project` | ForeignKey | Reference to Project model |
| `project_name` | CharField | Cached project name (synced automatically) |
| `month_year` | CharField | Period identifier (e.g., "Jan-2024") |

### Input Fields (Financial Metrics)

| Field | Type | Description |
|-------|------|-------------|
| `bcws` | Decimal(18,4) | Budgeted Cost of Work Scheduled (planned cost) |
| `bcwp` | Decimal(18,4) | Budgeted Cost of Work Performed (earned value) |
| `acwp` | Decimal(18,4) | Actual Cost of Work Performed |
| `fcst` | Decimal(18,4) | Forecast cost of remaining work |

### Calculated Fields (EVM Metrics)

| Field | Type | Description |
|-------|------|-------------|
| `eac` | Decimal(18,4) | Estimate at Completion = ACWP + FCST |
| `cv` | Decimal(18,4) | Cost Variance = BCWP - ACWP |
| `sv` | Decimal(18,4) | Schedule Variance = BCWP - BCWS |
| `cpi` | Decimal(10,6) | Cost Performance Index = BCWP / ACWP |
| `bac` | Decimal(18,4) | Budget at Completion (optional) |
| `vac` | Decimal(18,4) | Variance at Completion = BAC - EAC |

## Calculations

### Core EVM Formulas

All calculations use Decimal arithmetic for precision and are performed automatically on save:

```python
# Estimate at Completion
eac = acwp + fcst

# Cost Variance (< 0 means over budget)
cv = bcwp - acwp

# Schedule Variance (< 0 means behind schedule)
sv = bcwp - bcws

# Cost Performance Index (undefined if acwp = 0)
cpi = bcwp / acwp if acwp != 0 else None

# Variance at Completion (requires BAC)
vac = bac - eac if bac is not None else None
```

### Calculation Timing

- **Automatic**: All calculations occur in the model's `save()` method
- **Conditional**: Recalculations only happen when input values change
- **Stored**: Results are persisted in database for fast retrieval

## Usage Examples

### Creating Performance Record
```python
from cost_performance.models import ProjectCostPerformance
from projects.models import Project
from decimal import Decimal

project = Project.objects.get(name="Highway Project A")

record = ProjectCostPerformance.objects.create(
    project=project,
    month_year="Jan-2024",
    bcws=Decimal("100000.0000"),  # Planned
    bcwp=Decimal("95000.0000"),   # Earned
    acwp=Decimal("105000.0000"),  # Actual
    fcst=Decimal("150000.0000"),  # Forecast
    bac=Decimal("500000.0000")    # Budget at completion
)

# Automatically calculated:
# eac = 255000.0000  # ACWP + FCST
# cv = -10000.0000   # BCWP - ACWP (over budget)
# sv = -5000.0000    # BCWP - BCWS (behind schedule)
# cpi = 0.904762     # BCWP / ACWP
# vac = 245000.0000  # BAC - EAC
```

## API Endpoints

### List/Create Cost Performance
```
GET/POST /api/cost-performance/
```
- **GET**: List all records with filtering
- **POST**: Create new performance record

### Retrieve/Update/Delete
```
GET/PUT/PATCH/DELETE /api/cost-performance/{id}/
```

### Dashboard Data
```
GET /api/cost-performance/dashboard/?project_name=...
```

## Filtering Options

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `project_name` | string | Partial match filter | `?project_name=highway` |
| `date` | string | Created date filter | `?date=2024-01-15` |

## Performance Optimizations

### Database Indexing
- `project_name`: Indexed for fast project-based queries
- `created_at`: Indexed for time-based sorting and filtering
- Composite index: `(project, month_year)` for unique constraint support
- Composite index: `(project_name, -created_at)` for dashboard queries

### Decimal Precision
- **Financial Accuracy**: All monetary calculations use DecimalField
- **No Float Conversion**: Eliminates floating-point rounding errors
- **Consistent Scale**: 4 decimal places for most fields, 6 for CPI

### Calculation Optimization
- **Conditional Updates**: Only recalculates when input values change
- **Field Synchronization**: project_name automatically synced with project.name
- **Input Normalization**: month_year whitespace stripped

## Business Logic Notes

### Important Considerations
- **Cost Variance (CV)**: Negative values indicate over-budget conditions
- **Schedule Variance (SV)**: Negative values indicate behind-schedule conditions
- **CPI Values**: Values > 1.0 indicate better-than-planned performance
- **VAC Calculation**: Only computed when Budget at Completion (BAC) is provided

### Data Integrity
- **Unique Constraint**: `(project, month_year)` prevents duplicate entries
- **Foreign Key**: Ensures valid project references
- **Validation**: Financial fields validated for reasonableness
- **Synchronization**: project_name stays in sync with project relationship

## Developer Notes

### Calculation Location
⚠️ **Critical**: All EVM calculations happen in the model's `save()` method, not in views or serializers.

**Why in Model?**
- **Consistency**: Calculations occur regardless of creation method
- **Audit Trail**: Values are frozen in database for historical accuracy
- **Performance**: Pre-calculated values enable fast dashboard queries

### Model Save Behavior
The `save()` method implements smart recalculation:
```python
# Only recalculate if input values changed
if base_values_changed:
    perform_evm_calculations()
    sync_project_name()
```

### Field Synchronization
The project_name field is automatically maintained:
```python
# Sync with project relationship
self.project_name = self.project.name
```

### Warning: Formula Changes
⚠️ **Never modify EVM formulas without financial analysis**
- Formulas are industry-standard EVM calculations
- Changes affect project performance reporting
- Require validation against existing financial data

## Best Practices

#### Data Entry
- **Consistent Units**: Ensure all monetary values use same currency units
- **Complete Data**: Provide BAC when available for VAC calculations
- **Accurate Forecasting**: FCST values directly impact EAC calculations

#### Performance Monitoring
- **CV Tracking**: Monitor cost variance trends over time
- **CPI Analysis**: Values < 1.0 indicate cost performance issues
- **EAC Forecasting**: Use EAC for project completion cost estimates

#### API Usage
- **Filtering**: Use project_name and date filters for targeted queries
- **Data Validation**: Ensure all required fields are provided
- **Calculation Trust**: Rely on automatic EVM calculations

#### Development Guidelines
- **Test Calculations**: Verify EVM formulas against known examples
- **Decimal Handling**: Always use Decimal for financial operations
- **Index Awareness**: Leverage database indexes for query performance
- **Sync Awareness**: project_name field is automatically maintained

## Migration History

- **Initial**: Basic FloatField implementation with manual calculations
- **Foreign Key**: Added Project relationship for data integrity
- **Decimal Conversion**: FloatField to DecimalField for precision
- **Indexing**: Added database indexes for query performance
- **Smart Recalculation**: Conditional updates to avoid unnecessary computation

# Cost Performance ViewSet

## Overview

* Purpose of the API
* Supports EVM-based cost tracking and dashboards

## Endpoints

* POST /cost-performance/
* GET /cost-performance/
* GET /cost-performance/dashboard/
* POST /cost-performance/evm-dashboard/

## Input Fields

* project_name
* month_year
* bcws, bcwp, acwp, fcst
* optional bac

## Dashboard Output

* Monthly series:

  * bcws, bcwp, acwp, fcst
  * eac, cv, sv, cpi, vac
* Flags:

  * over_budget_cost
  * behind_schedule

## EVM Dashboard API

* Accepts monthly project data
* Computes:

  * BCWP, AC, CV, CPI
  * EAC, ETC
* Returns:

  * summary
  * monthly data
  * cumulative data

## Performance Optimizations

* Query optimization using `.only()` and `select_related()`
* Database-level sorting
* Response caching for heavy endpoints
* Reduced redundant computations

## Developer Notes

* Do NOT modify calculation logic
* Keep dashboard response format unchanged
* Use caching for performance-sensitive endpoints

## Best Practices

* Always pass project_name for filtering
* Use consistent month format (Jan-2023)
* Avoid unnecessary repeated API calls
