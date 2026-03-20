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
