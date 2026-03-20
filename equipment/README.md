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
