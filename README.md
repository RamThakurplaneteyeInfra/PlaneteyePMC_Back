#.PMC Backend API Documentations

A comprehensive REST API for Project Management & Construction (PMC) dashboard..

## Base URL

```
http://127.0.0.1:8000
```

## Authentication

### Basic Authentication

The API uses HTTP Basic Authentication. Include the `Authorization` header with `Basic <base64-encoded-username:password>` in all authenticated requests.

**Example using curl:**
```bash
curl -u username:password https://api.example.com/endpoint/
```

**Example using Python requests:**
```python
import requests
response = requests.get('https://api.example.com/endpoint/', auth=('username', 'password'))
```

---

## API Endpoints

### 1. User Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/accounts/me/` | GET | Get current user profile |

---

### 2. Projects

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/projects-data/projects/` | GET | List all projects |
| `/api/projects-data/projects/` | POST | Create new project |
| `/api/projects-data/projects/{id}/` | GET | Get project details |
| `/api/projects-data/projects/{id}/` | PUT | Update project |
| `/api/projects-data/projects/{id}/` | DELETE | Delete project |
| `/api/projects-data/sites/` | GET | List all sites |
| `/api/projects-data/sites/` | POST | Create new site |
| `/api/projects-data/sites/{id}/` | GET | Get site details |
| `/api/projects-data/sites/{id}/` | PUT | Update site |
| `/api/projects-data/sites/{id}/` | DELETE | Delete site |

---

### 3. Operations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/operations/tasks/` | GET | List all tasks |
| `/api/operations/tasks/` | POST | Create new task |
| `/api/operations/tasks/{id}/` | GET | Get task details |
| `/api/operations/tasks/{id}/` | PUT | Update task |
| `/api/operations/tasks/{id}/` | DELETE | Delete task |
| `/api/operations/reports/` | GET | List all operation reports |
| `/api/operations/reports/` | POST | Create new report |
| `/api/operations/reports/{id}/` | GET | Get report details |
| `/api/operations/reports/{id}/` | PUT | Update report |
| `/api/operations/reports/{id}/` | DELETE | Delete report |

---

### 4. Daily Progress Reports (DPR)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/dpr/` | GET | List all DPRs |
| `/api/dpr/` | POST | Create new DPR |
| `/api/dpr/{id}/` | GET | Get DPR details |
| `/api/dpr/{id}/` | PUT | Update DPR |
| `/api/dpr/{id}/` | PATCH | Partial update DPR |
| `/api/dpr/{id}/` | DELETE | Delete DPR |
| `/api/dpr/{id}/activities/` | GET | Get DPR activities |

**Query Parameters:**
- `project_name` - Filter by project name
- `date` - Filter by exact date (YYYY-MM-DD)
- `date_from` - Filter from date
- `date_to` - Filter to date

---

### 5. Contracts

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/contracts/` | GET | List all contracts |
| `/api/contracts/` | POST | Create new contract |
| `/api/contracts/{id}/` | GET | Get contract details |
| `/api/contracts/{id}/` | PUT | Update contract |
| `/api/contracts/{id}/` | DELETE | Delete contract |

---

### 6. Invoicing

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/invoicing/` | GET | List all invoicing records |
| `/api/invoicing/` | POST | Create new invoicing record |
| `/api/invoicing/{id}/` | GET | Get invoicing details |
| `/api/invoicing/{id}/` | PUT | Update invoicing record |
| `/api/invoicing/{id}/` | DELETE | Delete invoicing record |

---

### 7. Contract Performance

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/contract-performance/` | GET | List all contract performance records |
| `/api/contract-performance/` | POST | Create new record |
| `/api/contract-performance/{id}/` | GET | Get details |
| `/api/contract-performance/{id}/` | PUT | Update record |
| `/api/contract-performance/{id}/` | DELETE | Delete record |

---

### 8. Project Progress

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/project-progress/` | GET | List all progress records |
| `/api/project-progress/` | POST | Create new progress record |
| `/api/project-progress/{id}/` | GET | Get progress details |
| `/api/project-progress/{id}/` | PUT | Update progress record |
| `/api/project-progress/{id}/` | DELETE | Delete progress record |

---

### 9. Budget Performance (EVM)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/budget-performance/` | GET | List all budget records |
| `/api/budget-performance/` | POST | Create new budget record |
| `/api/budget-performance/{id}/` | GET | Get budget details |
| `/api/budget-performance/{id}/` | PUT | Update budget record |
| `/api/budget-performance/{id}/` | DELETE | Delete budget record |

---

### 10. Equipment

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/equipment/` | GET | List all equipment |
| `/api/equipment/` | POST | Create new equipment |
| `/api/equipment/{id}/` | GET | Get equipment details |
| `/api/equipment/{id}/` | PUT | Update equipment |
| `/api/equipment/{id}/` | DELETE | Delete equipment |

---

### 11. Manpower

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/manpower/` | GET | List all manpower records |
| `/api/manpower/` | POST | Create new manpower record |
| `/api/manpower/{id}/` | GET | Get manpower details |
| `/api/manpower/{id}/` | PUT | Update manpower record |
| `/api/manpower/{id}/` | DELETE | Delete manpower record |

---

### 12. Cashflow

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/cashflow/` | GET | List all cashflow records |
| `/api/cashflow/` | POST | Create new cashflow record |
| `/api/cashflow/{id}/` | GET | Get cashflow details |
| `/api/cashflow/{id}/` | PUT | Update cashflow record |
| `/api/cashflow/{id}/` | DELETE | Delete cashflow record |

---

### 13. Cost Performance (EVM)

Earned Value Management tracking with improved relational data model.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/cost-performance/` | GET | List all cost performance records (`?project_name=` filter) |
| `/api/cost-performance/` | POST | Create new cost record (auto-creates Project if needed) |
| `/api/cost-performance/dashboard/` | GET | EVM dashboard series for project |
| `/api/cost-performance/evm-dashboard/` | POST | Enhanced EVM dashboard computation |
| `/api/cost-performance/{id}/` | GET | Get cost details |
| `/api/cost-performance/{id}/` | PUT | Update cost record |
| `/api/cost-performance/{id}/` | DELETE | Delete cost record |

**Query Parameters:**
- `project_name` - Filter by project name (case-insensitive)

**Features:**
- Automatic Project creation from `project_name`
- ForeignKey relationships for data integrity
- Computed EVM metrics: EAC, CV, SV, CPI, VAC

---

### 14. Health & Safety

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health-safety/status/` | POST | Calculate health & safety status |
| `/api/health-safety/example/` | GET | Get example request/response |
| `/api/health-safety/reports/` | GET | List all health & safety reports |
| `/api/health-safety/reports/` | POST | Create new report |
| `/api/health-safety/reports/{id}/` | GET | Get report details |
| `/api/health-safety/reports/{id}/` | PUT | Update report |
| `/api/health-safety/reports/{id}/` | PATCH | Partial update report |
| `/api/health-safety/reports/{id}/` | DELETE | Delete report |

**Health & Safety Status Calculation:**

Input:
```json
{
  "totalManhours": 500000,
  "incidents": {
    "fatalities": 0,
    "significant": 1,
    "major": 2,
    "minor": 5,
    "nearMiss": 10
  }
}
```

Response includes:
- `summary` - Total manhours, incidents, incident rate, severity score, status
- `breakdown` - Each incident type with count and percentage
- `pyramid` - Visualization data with colors
- `insights` - Human-readable insights
- `alerts` - Alert flags (hasFatality, highNearMiss)
- `severityIndex` - Normalized 0-100 score

---

## Recent Data Model Improvements

### Cost Performance (EVM) Migration ✅
- **Module**: `cost_performance`
- **Before**: Used `project_name` CharField for project identification
- **After**: ForeignKey relationship to `Project` model
- **Benefits**:
  - Referential integrity constraints
  - Improved query performance with indexes
  - Prevention of orphaned records
  - Consistent project data across the system
- **API Compatibility**: All existing endpoints work unchanged
- **Migration**: Zero-downtime with automatic Project creation

### Other Modules
- **budget_performance**: Still uses `project_name` (separate EVM implementation)
- **Future migrations**: Consider similar improvements for other modules as needed

---

## Documentation

### Swagger UI
Access interactive API documentation at:
```
http://127.0.0.1:8000/swagger/
```

### ReDoc
Alternative documentation format:
```
http://127.0.0.1:8000/redoc/
```

### Django Admin
```
http://127.0.0.1:8000/admin/
```

---

## Running the Server

```bash
cd backend
python manage.py runserver 8000
```

**Note:** Use `127.0.0.1` or `localhost` in your browser, not `0.0.0.0`.

---

## Testing Examples

### Test DPR Endpoint
```bash
curl -X GET http://127.0.0.1:8000/api/dpr/
```

### Test Projects Endpoint
```bash
curl -X GET http://127.0.0.1:8000/api/projects-data/projects/
```

### Test Health & Safety Status
```bash
curl -X POST http://127.0.0.1:8000/api/health-safety/status/ \
  -H "Content-Type: application/json" \
  -d '{"totalManhours": 500000, "incidents": {"fatalities": 0, "significant": 1, "major": 2, "minor": 5, "nearMiss": 10}}'
```

---

## Project Structure

```
backend/
├── accounts/          # User authentication & profiles
├── projects/          # Projects & sites management
├── operations/       # Tasks & operation reports
├── dpr/             # Daily Progress Reports
├── contracts/       # Contract management (Contract values)
├── invoicing/      # Invoice tracking 
├── contract_performance/  # Contract performance metrics
├── project_progress/      # Project progress tracking
├── budget_performance/    # Budget vs cost (EVM)
├── equipment/            # Equipment management
├── manpower/            # Manpower tracking
├── cashflow/           # Cash flow management
├── cost_performance/   # Cost performance (EVM)
└── health_safety/      # Health & Safety status
```
