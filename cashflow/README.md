# Cash-In vs Cash-Out API

## Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/api/cashflow/` | Add monthly row; cumulatives recalculated. |
| GET | `/api/cashflow/` | List rows; optional `?project_name=`. Chronological per project. |
| GET | `/api/cashflow/dashboard/?project_name=` | Arrays for bar + line charts. |

## POST body

| Field | Rule |
|-------|------|
| `project_name` | string |
| `month_year` | `Jan-2023` style |
| `cash_in_monthly_plan`, `cash_in_monthly_actual` | ≥ 0 |
| `cash_out_monthly_plan`, `cash_out_monthly_actual` | ≥ 0 |
| `actual_cost_monthly` | ≥ 0 |

Cumulative fields are **not** accepted.

## Dashboard

- `months`: e.g. `Jan-23`, `Feb-23`
- All monthly and cumulative series as parallel arrays
- **`profit_cumulative_actual`**: `cash_in_cumulative_actual − cash_out_cumulative_actual` per month-end
- **`cash_out_exceeds_cash_in_actual`**: `true` when monthly actual cash-out &gt; monthly actual cash-in
- **`actual_cost_monthly`** included for bar charts

Swagger tag: **Cash flow — in vs out**.
