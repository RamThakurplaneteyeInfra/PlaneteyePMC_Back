# Budget vs Cost Performance (EVM) API

Earned Value Management metrics: CPI, EAC, ETG, VAC, CV from BAC, BCWP, and ACWP.

**Swagger UI:** `/swagger/` → tag **budget-performance** (or search for `budget-performance`)

**Base path:** `/api/budget-performance/`

Use your server host, e.g. `http://127.0.0.1:8000/api/budget-performance/`.

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| **POST** | `/api/budget-performance/` | Submit inputs; server computes and stores metrics; returns calculated JSON. |
| **GET** | `/api/budget-performance/` | List all saved records (newest first), for dashboards. |

---

## POST — Create & calculate

**URL:** `POST /api/budget-performance/`

**Content-Type:** `application/json`

### Request body (required fields)

| Field | Type | Description |
|-------|------|-------------|
| `project_name` | string | Project name |
| `budget_at_completion` | number | BAC — budget at completion |
| `earned_value` | number | BCWP — earned value |
| `actual_cost` | number | ACWP — actual cost |

**Optional aliases:** `bac` → `budget_at_completion`, `bcwp` → `earned_value`, `acwp` → `actual_cost`.

### Example request

```json
{
  "project_name": "Atlas Project",
  "budget_at_completion": 112000000,
  "earned_value": 17160000,
  "actual_cost": 21360000
}
```

### Example response — `201 Created`

```json
{
  "project_name": "Atlas Project",
  "bac": 112000000.0,
  "bcwp": 17160000.0,
  "acwp": 21360000.0,
  "cpi": 0.803371,
  "eac": 139412903.2258,
  "etg": 118052903.2258,
  "vac": -27412903.2258,
  "cv": -4200000.0
}
```

### Formulas (server-side)

- **CPI** = BCWP / ACWP  
- **EAC** = BAC / CPI  
- **ETG** = EAC − ACWP  
- **VAC** = BAC − EAC  
- **CV** = BCWP − ACWP  

### Validation

- `budget_at_completion` must be **> 0**  
- `actual_cost` must be **> 0**  
- `earned_value` must be **≥ 0** and **> 0** (so CPI/EAC are defined)  

---

## GET — List all records

**URL:** `GET /api/budget-performance/`

Returns an array of objects. Each item includes the same metrics as above plus:

- `id` — record ID  
- `created_at` — ISO timestamp  

Example (truncated):

```json
[
  {
    "project_name": "Atlas Project",
    "bac": 112000000.0,
    "bcwp": 17160000.0,
    "acwp": 21360000.0,
    "cpi": 0.803371,
    "eac": 139412903.2258,
    "etg": 118052903.2258,
    "vac": -27412903.2258,
    "cv": -4200000.0,
    "id": 1,
    "created_at": "2026-03-18T12:00:00.000000Z"
  }
]
```

---

## Notes

- **Auth:** Currently `AllowAny` (no JWT required unless you change the viewset).  
- **Other methods:** Only `GET` and `POST` are enabled for this resource.
