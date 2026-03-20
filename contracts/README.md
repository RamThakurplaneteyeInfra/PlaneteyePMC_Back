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

## Filtering

List endpoint supports:

- `GET /api/contracts/?project_name=Alpha` (case-insensitive contains)
- `GET /api/contracts/?date=YYYY-MM-DD` (filters by created date)

