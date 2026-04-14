# Project Manpower & Man-Hours API

## Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/api/manpower/` | Add monthly row; MH and cumulatives computed server-side. |
| GET | `/api/manpower/` | List rows (optional `?project_name=`). Sorted by project, then calendar month. |
| GET | `/api/manpower/dashboard/?project_name=` | Chart arrays + efficiency flags. |

### POST body

- `project_name` (string)
- `month_year` — **`Jan-2023`** format (3-letter month, hyphen, 4-digit year)
- `planned_manpower`, `actual_manpower` (integers ≥ 0)
- `working_hours_per_day` (float **> 0**)
- `working_days_per_month` (integer **> 0**)

**Formulas**

- `planned_mh` = planned_manpower × working_hours_per_day × working_days_per_month  
- `actual_mh` = actual_manpower × working_hours_per_day × working_days_per_month  
- Cumulative MH = running sum of monthly MH in **calendar order** (year, then month).

### Dashboard response

`months` use short year labels (e.g. `Jan-23`). Arrays align by index.

```json
{
  "months": ["Jan-23", "Feb-23", "Mar-23"],
  "planned_manpower": [50, 100, 150],
  "actual_manpower": [25, 75, 125],
  "planned_mh_cumulative": [10400.0, 31200.0, 62400.0],
  "actual_mh_cumulative": [5200.0, 20800.0, 46800.0],
  "manpower_efficiency": [0.5, 0.75, 0.8333],
  "actual_below_planned": [true, true, true]
}
```

Swagger: `/swagger/` → tag **Manpower — MH tracking**.

# Project Manpower Module

## Overview

* Tracks manpower and man-hours per project per month
* Supports cumulative analysis

## Key Fields

* project_name
* month_year
* planned_manpower
* actual_manpower
* working_hours_per_day
* working_days_per_month

## Calculated Fields

* planned_mh = planned_manpower × working_hours × working_days
* actual_mh = actual_manpower × working_hours × working_days
* cumulative fields:

  * planned_mh_cumulative
  * actual_mh_cumulative

## Cumulative Logic

* Sorted by calendar month
* Running sum calculation
* Recomputed on each insert/update

## Performance Optimizations

* Reduced DB queries using bulk operations
* Optimized memory usage
* Indexed fields for faster filtering

## Data Integrity

* Unique constraint on (project_name, month_year)
* Ensures no duplicate monthly records

## Developer Notes

* Do NOT modify cumulative logic
* Always use recalculate_cumulatives() after changes
* Maintain month_year format consistency

## Best Practices

* Use consistent month format (Jan-2023)
* Avoid duplicate entries
* Use filters for efficient queries

# Project Manpower ViewSet

## Overview

* Handles manpower tracking APIs
* Supports monthly and cumulative analysis

## Endpoints

* POST /manpower/
* GET /manpower/
* GET /manpower/dashboard/

## Input Fields

* project_name
* month_year
* manpower data

## Dashboard Output

* months
* planned_manpower
* actual_manpower
* cumulative MH
* efficiency metrics

## Performance Optimizations

* Reduced DB queries
* Cached responses
* Optimized data processing

## Developer Notes

* Do NOT modify cumulative logic
* Always invalidate cache after data changes
* Maintain response structure

## Best Practices

* Use filtering for performance
* Avoid duplicate API calls
* Maintain consistent data formats

# Project Manpower Serializer

## Overview

* Handles input and output of manpower data
* Calculates man-hours and triggers cumulative updates

## Input Fields

* project_name
* month_year
* planned_manpower
* actual_manpower
* working_hours_per_day
* working_days_per_month

## Calculations

* planned_mh = planned_manpower × hours × days
* actual_mh = actual_manpower × hours × days

## Cumulative Logic

* Automatically triggered after record creation
* Maintains running totals

## Validation Rules

* manpower ≥ 0
* working hours > 0
* working days > 0
* unique (project_name, month_year)

## Output Fields

* planned_mh
* actual_mh
* cumulative fields
* efficiency metrics

## Performance Optimizations

* Removed redundant DB queries
* Cached month parsing
* Transaction-safe operations

## Developer Notes

* Do NOT modify calculation logic
* Always trigger cumulative recalculation
* Maintain month format consistency

## Best Practices

* Use consistent month format (Jan-2023)
* Avoid duplicate entries
* Validate inputs before sending
