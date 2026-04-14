# Project Equipment Tracking API

## Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/api/equipment/` | Add one month of planned/actual equipment (cumulatives recalculated). |
| GET | `/api/equipment/` | All rows, sorted by `project_name` then `month`. Optional `?project_name=`. |
| GET | `/api/equipment/dashboard/?project_name=` | Chart-ready arrays for one project. |

### POST body

```json
{
  "project_name": "Alpha Site",
  "month": "Jan-23",
  "planned_equipment": 20,
  "actual_equipment": 15
}
```

`month` accepts e.g. `Jan-23`, `2023-01`, `2023-01-01`.  
**One row per project per calendar month.** Cumulative fields are read-only.

### Dashboard response

`GET /api/equipment/dashboard/?project_name=Alpha%20Site`

```json
{
  "months": ["Jan-23", "Feb-23", "Mar-23"],
  "planned_monthly": [20, 22, 24],
  "actual_monthly": [15, 17, 19],
  "planned_cumulative": [20, 42, 66],
  "actual_cumulative": [15, 32, 51],
  "equipment_efficiency": [0.75, 0.7727, 0.7917],
  "actual_below_planned": [true, true, true]
}
```

`equipment_efficiency` is `actual / planned` (null if planned is 0).
`actual_below_planned` is true when actual &lt; planned.

# Project Equipment Module

## Overview

* Tracks monthly equipment usage per project
* Stores planned vs actual values
* Maintains cumulative totals

## Key Fields

* project_name
* month (first day of month)
* planned_equipment
* actual_equipment
* planned_cumulative
* actual_cumulative

## Cumulative Logic

* planned_cumulative = running sum of planned_equipment
* actual_cumulative = running sum of actual_equipment
* Calculated in chronological order per project

## Constraints

* Unique combination of:

  * project_name
  * month

## Performance Optimizations

* Bulk updates for cumulative calculation
* Indexed fields for faster filtering
* Reduced database queries

## Developer Notes

* Always call `recalculate_cumulatives()` after inserting new data
* Do NOT modify cumulative logic
* Ensure month is always first day of month

## Best Practices

* Avoid duplicate records per project/month
* Maintain consistent project_name formatting
* Use proper chronological order

# Project Equipment Serializer

## Overview

* Handles equipment data input and output
* Validates and normalizes incoming data
* Triggers cumulative recalculation after save

## Input Handling

* Accepts:

  * project_name
  * month (flexible formats like Jan-23, 2023-01)
  * planned_equipment
  * actual_equipment

## Month Parsing

* Supports multiple formats:

  * Jan-23
  * Jan-2023
  * 2023-01
  * 2023-01-01
* Converts to first day of the month

## Validation Rules

* project_name must not be empty
* planned_equipment ≥ 0
* actual_equipment ≥ 0
* Unique (project_name, month) enforced

## Output Fields

* planned_equipment
* actual_equipment
* planned_cumulative
* actual_cumulative
* equipment_efficiency
* actual_below_planned

## Performance Optimizations

* Removed redundant database queries
* Cached month parsing
* Transaction-safe operations

## Developer Notes

* Do NOT modify cumulative logic in serializer
* Cumulative calculation handled in model
* Always ensure transaction safety

## Best Practices

* Use consistent project_name formatting
* Avoid duplicate entries
* Ensure valid month formats

# Project Equipment ViewSet

## Overview

* Handles equipment tracking APIs
* Supports monthly and cumulative data

## Endpoints

* POST /equipment/
* GET /equipment/
* GET /equipment/dashboard/

## Input Fields

* project_name
* month
* planned_equipment
* actual_equipment

## Dashboard Output

* months
* planned_monthly
* actual_monthly
* planned_cumulative
* actual_cumulative
* equipment_efficiency
* actual_below_planned

## Filtering

* project_name (optional for list, required for dashboard)

## Performance Optimizations

* Reduced database payload using `.only()`
* Cached API responses
* Optimized data processing loops

## Developer Notes

* Do NOT modify cumulative logic
* Always invalidate cache after data changes
* Keep dashboard response structure unchanged

## Best Practices

* Use filtering to reduce data load
* Avoid repeated API calls
* Maintain consistent project_name values
