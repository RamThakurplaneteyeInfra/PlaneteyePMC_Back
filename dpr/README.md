# Daily Progress Report (DPR) System

Complete Django REST Framework implementation for Daily Progress Reports with nested activities support.

## Features

- ✅ Full CRUD operations for Daily Progress Reports
- ✅ Nested activities support (one-to-many relationship)
- ✅ Filtering by project name and date
- ✅ Pagination support (20 items per page)
- ✅ Validation (target_achieved: 0-100%)
- ✅ Django Admin interface
- ✅ Swagger/OpenAPI documentation
- ✅ No authentication required (for testing)
- ✅ Production-ready code with error handling

## Installation & Setup

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

Or install manually:
```bash
pip install drf-yasg  # For Swagger documentation
```

### 2. Database Migrations

Migrations have been created and applied. If you need to run them again:

```bash
python manage.py makemigrations dpr
python manage.py migrate
```

### 3. Run Server

```bash
python manage.py runserver
```

The API will be available at: `https://fv5k8l3m-8000.inc1.devtunnels.ms/api/dpr/`

### 4. Access Swagger Documentation

- **Swagger UI**: https://fv5k8l3m-8000.inc1.devtunnels.ms/swagger/
- **ReDoc**: https://fv5k8l3m-8000.inc1.devtunnels.ms/redoc/
- **OpenAPI JSON**: https://fv5k8l3m-8000.inc1.devtunnels.ms/swagger.json

See `SWAGGER_SETUP.md` for more details.

## API Endpoints

### Base URL
All endpoints are prefixed with `/api/dpr/`

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/dpr/` | List all DPRs (with pagination) |
| POST | `/api/dpr/` | Create new DPR with activities |
| GET | `/api/dpr/{id}/` | Retrieve single DPR |
| PUT | `/api/dpr/{id}/` | Update DPR (full update) |
| PATCH | `/api/dpr/{id}/` | Partial update DPR |
| DELETE | `/api/dpr/{id}/` | Delete DPR |
| GET | `/api/dpr/{id}/activities/` | Get activities for a DPR |

### Query Parameters (for GET /api/dpr/)

- `project_name` - Filter by project name (case-insensitive partial match)
- `date` - Filter by exact report date (YYYY-MM-DD)
- `date_from` - Filter reports from this date onwards
- `date_to` - Filter reports up to this date
- `page` - Page number for pagination

### Example Requests

#### 1. Create DPR (POST /api/dpr/)

**No authentication required!**

```bash
POST http://localhost:8000/api/dpr/
Content-Type: application/json

{
  "project_name": "Highway Construction Project",
  "job_no": "JOB-2024-001",
  "report_date": "2024-01-15",
  "unresolved_issues": "Material delivery delayed by 2 days",
  "pending_letters": "Letter to client regarding site access",
  "quality_status": "All quality checks passed",
  "next_day_incident": "Concrete pouring scheduled",
  "bill_status": "Invoice #1234 submitted",
  "gfc_status": "GFC drawings approved",
  "issued_by": "John Doe",
  "designation": "Site Engineer",
  "activities": [
    {
      "date": "2024-01-15",
      "activity": "Foundation excavation",
      "deliverables": "500 cubic meters excavated",
      "target_achieved": 85.5,
      "next_day_plan": "Continue excavation and prepare for concrete",
      "remarks": "Weather conditions favorable"
    }
  ]
}
```

#### 2. List DPRs with Filters (GET /api/dpr/)

```bash
# Filter by project name
GET /api/dpr/?project_name=Highway

# Filter by date
GET /api/dpr/?date=2024-01-15

# Filter by date range
GET /api/dpr/?date_from=2024-01-01&date_to=2024-01-31

# Combined filters
GET /api/dpr/?project_name=Highway&date_from=2024-01-01&page=1
```

#### 3. Get Single DPR (GET /api/dpr/{id}/)

```bash
GET /api/dpr/1/
```

#### 4. Update DPR (PUT /api/dpr/{id}/)

```bash
PUT /api/dpr/1/
Content-Type: application/json

{
  "project_name": "Updated Project Name",
  "job_no": "JOB-2024-001",
  "report_date": "2024-01-15",
  "issued_by": "John Doe",
  "designation": "Engineer",
  "activities": [...]
}
```

#### 5. Delete DPR (DELETE /api/dpr/{id}/)

```bash
DELETE /api/dpr/1/
```

## Response Format

### Success Response (GET /api/dpr/)

```json
{
  "count": 100,
  "next": "https://fv5k8l3m-8000.inc1.devtunnels.ms/api/dpr/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "project_name": "Highway Construction Project",
      "job_no": "JOB-2024-001",
      "report_date": "2024-01-15",
      "unresolved_issues": "Material delivery delayed",
      "pending_letters": "Letter to client",
      "quality_status": "All checks passed",
      "next_day_incident": "Concrete pouring",
      "bill_status": "Invoice submitted",
      "gfc_status": "GFC approved",
      "issued_by": "John Doe",
      "designation": "Site Engineer",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:30:00Z",
      "activities": [
        {
          "id": 1,
          "date": "2024-01-15",
          "activity": "Foundation excavation",
          "deliverables": "500 cubic meters",
          "target_achieved": 85.5,
          "next_day_plan": "Continue excavation",
          "remarks": "Weather favorable"
        }
      ]
    }
  ]
}
```

### Error Response

```json
{
  "target_achieved": ["Target achieved must be between 0 and 100."]
}
```

## Testing

### Using cURL

```bash
# Create DPR (no auth needed)
curl -X POST https://fv5k8l3m-8000.inc1.devtunnels.ms/api/dpr/ \
  -H "Content-Type: application/json" \
  -d @sample_post_request.json

# List DPRs
curl -X GET "https://fv5k8l3m-8000.inc1.devtunnels.ms/api/dpr/?project_name=Highway"

# Get single DPR
curl -X GET https://fv5k8l3m-8000.inc1.devtunnels.ms/api/dpr/1/
```

### Using Python requests

```python
import requests

BASE_URL = "https://fv5k8l3m-8000.inc1.devtunnels.ms/api"

# Create DPR (no auth needed)
data = {
    "project_name": "Test Project",
    "job_no": "JOB-001",
    "report_date": "2024-01-15",
    "issued_by": "John Doe",
    "designation": "Engineer",
    "activities": [
        {
            "date": "2024-01-15",
            "activity": "Test activity",
            "target_achieved": 75.0
        }
    ]
}

response = requests.post(f"{BASE_URL}/dpr/", json=data)
print(response.json())
```

## Django Admin

Access the admin interface at: `https://fv5k8l3m-8000.inc1.devtunnels.ms/admin/`

Features:
- View all DPRs in a list with filters
- Search by project name, job number, issuer
- Inline editing of activities
- Date hierarchy navigation

## React Dashboard Component

A ready-to-use React component is available at:
`components/DPRDashboard.tsx`

Usage:

```tsx
import DPRDashboard from './components/DPRDashboard';
import { dprApi } from './services/api';

function App() {
  return <DPRDashboard api={dprApi} />;
}
```

## Database Models

### DailyProgressReport

- `project_name` (CharField, max_length=255)
- `job_no` (CharField, max_length=100)
- `report_date` (DateField)
- `unresolved_issues` (TextField, optional)
- `pending_letters` (TextField, optional)
- `quality_status` (TextField, optional)
- `next_day_incident` (TextField, optional)
- `bill_status` (TextField, optional)
- `gfc_status` (TextField, optional)
- `issued_by` (CharField, max_length=255)
- `designation` (CharField, max_length=255)
- `created_at` (DateTimeField, auto)
- `updated_at` (DateTimeField, auto)

### DPRActivity

- `dpr` (ForeignKey to DailyProgressReport)
- `date` (DateField)
- `activity` (TextField)
- `deliverables` (TextField, optional)
- `target_achieved` (FloatField, 0-100, validated)
- `next_day_plan` (TextField, optional)
- `remarks` (TextField, optional)

## Validation Rules

1. **target_achieved**: Must be between 0.0 and 100.0 (inclusive)
2. **report_date**: Must be a valid date format (YYYY-MM-DD)
3. **All required fields**: Must be provided when creating/updating

## Notes

- The system uses SQLite by default but is structured to support PostgreSQL
- All timestamps are in UTC
- Reports are ordered by latest first (report_date, then created_at)
- Activities are automatically deleted when parent DPR is deleted (CASCADE)
- Pagination is set to 20 items per page
- **No authentication required** - endpoints are public for testing

## Swagger Documentation

Interactive API documentation is available at:

- **Swagger UI**: https://fv5k8l3m-8000.inc1.devtunnels.ms/swagger/
- **ReDoc**: https://fv5k8l3m-8000.inc1.devtunnels.ms/redoc/
- **OpenAPI JSON**: https://fv5k8l3m-8000.inc1.devtunnels.ms/swagger.json

All DPR endpoints are fully documented with:
- Request/response schemas
- Query parameters
- Example values
- Validation rules

See `SWAGGER_SETUP.md` for detailed setup instructions.

## Support

For issues or questions, check the Django admin interface or review the API responses for detailed error messages.
