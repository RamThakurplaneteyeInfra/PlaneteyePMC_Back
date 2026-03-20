# Project Cost Performance (EVM)

## Endpoints

- `POST /api/cost-performance/`
- `GET /api/cost-performance/?project_name=` (optional filter)
- `GET /api/cost-performance/dashboard/?project_name=` (required)

## POST body

| Field | Description |
|-------|-------------|
| `project_name` | string |
| `month_year` | `Jan-2023` |
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

Swagger tag: **Cost performance (EVM)**.
