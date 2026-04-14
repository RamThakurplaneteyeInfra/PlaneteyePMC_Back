# Invoicing Information API

Complete API documentation for the Invoicing Information system.

## Overview

The Invoicing Information API allows **Billing Site Engineers** to manage billing and collection data for projects. The system tracks:
- **Gross Billed**: Total amount billed including VAT
- **Net Billed W/O VAT**: Net amount billed excluding VAT
- **Net Collected**: Amount actually collected
- **Net Due**: Outstanding amount (automatically calculated: Net Billed W/O VAT - Net Collected)

## Access Control

- **Billing Site Engineer**: Can view, create, update, and delete invoicing records
- **Other roles**: Access denied (403 Forbidden)

## API Endpoints

### Base URL
```
/api/invoicing/
```

### 1. Create Invoicing Record
**POST** `/api/invoicing/`

**Role Required**: `Billing Site Engineer`

**Request Body**:
```json
{
  "role": "Billing Site Engineer",
  "project_name": "Project Alpha",
  "gross_billed": 120000000.00,
  "net_billed_without_vat": 100000000.00,
  "net_collected": 80000000.00,
  "created_by": "Billing SE 1"
}
```

**Response** (201 Created):
```json
{
  "id": 1,
  "project_name": "Project Alpha",
  "gross_billed": "120000000.00",
  "net_billed_without_vat": "100000000.00",
  "net_collected": "80000000.00",
  "net_due": "20000000.00",
  "created_by": "Billing SE 1",
  "updated_by": null,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**Note**: `net_due` is automatically calculated as `net_billed_without_vat - net_collected`.

---

### 2. List All Invoicing Records
**GET** `/api/invoicing/`

**Role Required**: `Billing Site Engineer`

**Query Parameters**:
- `project_name` (optional): Filter by project name (case-insensitive partial match)
- `date` (optional): Filter by created date (YYYY-MM-DD format)
- `role` (required): Must be `"Billing Site Engineer"` (can be in query param or header `X-Role`)

**Example**:
```
GET /api/invoicing/?project_name=Alpha&date=2024-01-15&role=Billing Site Engineer
```

**Response** (200 OK):
```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "project_name": "Project Alpha",
      "gross_billed": "120000000.00",
      "net_billed_without_vat": "100000000.00",
      "net_collected": "80000000.00",
      "net_due": "20000000.00",
      "created_by": "Billing SE 1",
      "updated_by": null,
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

---

### 3. Retrieve Single Invoicing Record
**GET** `/api/invoicing/{id}/`

**Role Required**: `Billing Site Engineer`

**Response** (200 OK):
```json
{
  "id": 1,
  "project_name": "Project Alpha",
  "gross_billed": "120000000.00",
  "net_billed_without_vat": "100000000.00",
  "net_collected": "80000000.00",
  "net_due": "20000000.00",
  "created_by": "Billing SE 1",
  "updated_by": null,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

---

### 4. Update Invoicing Record (Full Update)
**PUT** `/api/invoicing/{id}/`

**Role Required**: `Billing Site Engineer`

**Request Body**:
```json
{
  "role": "Billing Site Engineer",
  "project_name": "Project Alpha",
  "gross_billed": 130000000.00,
  "net_billed_without_vat": 110000000.00,
  "net_collected": 90000000.00,
  "updated_by": "Billing SE 1"
}
```

**Response** (200 OK):
```json
{
  "id": 1,
  "project_name": "Project Alpha",
  "gross_billed": "130000000.00",
  "net_billed_without_vat": "110000000.00",
  "net_collected": "90000000.00",
  "net_due": "20000000.00",
  "created_by": "Billing SE 1",
  "updated_by": "Billing SE 1",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T11:00:00Z"
}
```

---

### 5. Partially Update Invoicing Record
**PATCH** `/api/invoicing/{id}/`

**Role Required**: `Billing Site Engineer`

**Request Body** (only include fields to update):
```json
{
  "role": "Billing Site Engineer",
  "net_collected": 95000000.00,
  "updated_by": "Billing SE 1"
}
```

**Response** (200 OK): Same format as PUT response.

---

### 6. Delete Invoicing Record
**DELETE** `/api/invoicing/{id}/`

**Role Required**: `Billing Site Engineer`

**Response** (204 No Content): Empty response body.

---

## Validation Rules

1. **All monetary fields** must be `>= 0`
2. **net_collected** cannot exceed **net_billed_without_vat**
3. **project_name** is required
4. **created_by** is required on creation
5. **net_due** is read-only and automatically calculated

## Error Responses

### 403 Forbidden (Insufficient Permissions)
```json
{
  "detail": "Only Billing Site Engineer can view invoicing information (role='Billing Site Engineer')."
}
```

### 400 Bad Request (Validation Error)
```json
{
  "net_collected": ["net_collected cannot exceed net_billed_without_vat."]
}
```

### 404 Not Found
```json
{
  "detail": "Not found."
}
```

## Testing with Swagger

1. Navigate to `https://fv5k8l3m-8000.inc1.devtunnels.ms/swagger/`
2. Find the **Invoicing Information** section
3. Click on any endpoint to expand
4. Click **"Try it out"**
5. Fill in the required fields:
   - `role`: `"Billing Site Engineer"` (required for all operations)
   - Other fields as needed
6. Click **"Execute"**

## Example Workflow

1. **Create** a new invoicing record:
   ```bash
   POST /api/invoicing/
   {
     "role": "Billing Site Engineer",
     "project_name": "Project Alpha",
     "gross_billed": 120000000.00,
     "net_billed_without_vat": 100000000.00,
     "net_collected": 80000000.00,
     "created_by": "Billing SE 1"
   }
   ```

2. **List** all records:
   ```bash
   GET /api/invoicing/?role=Billing Site Engineer
   ```

3. **Update** collected amount:
   ```bash
   PATCH /api/invoicing/1/
   {
     "role": "Billing Site Engineer",
     "net_collected": 85000000.00,
     "updated_by": "Billing SE 1"
   }
   ```
   Note: `net_due` will automatically update to `15000000.00`.

## Django Admin

The Invoicing Information model is registered in Django Admin. You can:
- View all records
- Filter by `created_by`, `updated_by`, `created_at`
- Search by `project_name`, `created_by`, `updated_by`
- Edit records (with automatic `net_due` calculation)

Access at: `https://fv5k8l3m-8000.inc1.devtunnels.ms/admin/invoicing/invoicinginformation/`

# Invoicing Information Module

## Overview

* Tracks billing and collection data per project
* Supports financial monitoring and reporting

## Key Fields

* project_name
* gross_billed
* net_billed_without_vat
* net_collected
* net_due (calculated)

## Calculation Logic

* net_due = net_billed_without_vat - net_collected
* Automatically calculated in save()

## Data Integrity

* All monetary fields use DecimalField for precision
* Values must be non-negative

## Performance Optimizations

* Indexed fields for faster queries
* Optimized save() method
* Efficient filtering by project and date

## Tracking Fields

* created_by
* updated_by
* created_at
* updated_at

## Developer Notes

* Do NOT modify net_due calculation logic
* Always rely on save() for derived field updates
* Maintain Decimal precision

## Best Practices

* Ensure consistent project_name formatting
* Avoid manual modification of net_due
* Use filters for efficient queries

# Invoicing Serializer

## Overview

* Handles validation and serialization of invoicing data
* Ensures data integrity for financial records

## Key Features

* Decimal-based financial validation
* Automatic net_due calculation (read-only)
* Logical constraint enforcement

## Validation Rules

* All monetary fields must be ≥ 0
* net_collected ≤ net_billed_without_vat

## Update Handling

* Automatically sets updated_by if provided in request
* Maintains audit trail

## Performance Optimizations

* Decimal precision for manhours
* Efficient validation logic
* Structured serializers

## Developer Notes

* Do NOT modify validation logic without impact analysis
* net_due is always calculated in model, not serializer
* Ensure Decimal precision is maintained

## Best Practices

* Always pass valid financial values
* Avoid manual manipulation of net_due
* Maintain consistent project_name formatting

# Invoicing ViewSet

## Overview

* Handles invoicing CRUD operations
* Implements role-based access control

## Endpoints

* POST /invoicing/
* GET /invoicing/
* GET /invoicing/{id}/
* PUT /invoicing/{id}/
* PATCH /invoicing/{id}/
* DELETE /invoicing/{id}/

## Role Access

* Billing Site Engineer → full access
* PMC Head, CEO, Coordinator → read-only

## Filtering

* project_name (partial match)
* date (YYYY-MM-DD)

## Performance Optimizations

* Reduced database payload
* Cached API responses
* Optimized role handling

## Developer Notes

* Do NOT modify role logic
* Ensure cache invalidation after changes
* Maintain response structure

## Best Practices

* Use filters to limit data
* Avoid unnecessary API calls
* Maintain consistent role values
