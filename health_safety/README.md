# Health & Safety API

A production-ready REST API for Health & Safety Status based on a pyramid model for DPR (Daily Progress Report) dashboard.

## Overview

This API calculates health & safety metrics from incident data and manhours, providing:
- Safety status determination (safe, moderate, high_risk, critical)
- Incident breakdown with percentages
- Pyramid visualization data
- Human-readable insights
- Alert flags for critical conditions
- Normalized severity index (0-100)

## API Endpoints

### 1. Calculate Health & Safety Status

**POST** `/api/health-safety/status/`

Calculate complete health & safety status from incident data.

**Request Body:**
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

**Response:**
```json
{
  "summary": {
    "totalManhours": 500000,
    "totalIncidents": 18,
    "incidentRate": 36.0,
    "severityScore": 30,
    "status": "safe"
  },
  "breakdown": {
    "fatalities": { "count": 0, "percentage": 0.0 },
    "significant": { "count": 1, "percentage": 5.56 },
    "major": { "count": 2, "percentage": 11.11 },
    "minor": { "count": 5, "percentage": 27.78 },
    "nearMiss": { "count": 10, "percentage": 55.56 }
  },
  "pyramid": [
    { "label": "Fatalities", "value": 0, "color": "#000000" },
    { "label": "Significant", "value": 1, "color": "#FF0000" },
    { "label": "Major", "value": 2, "color": "#FFA500" },
    { "label": "Minor", "value": 5, "color": "#FFFF00" },
    { "label": "Near Miss", "value": 10, "color": "#00FF00" }
  ],
  "insights": [
    "Safety status is good - maintain current practices",
    "1 significant incident(s) need investigation"
  ],
  "alerts": {
    "hasFatality": false,
    "highNearMiss": false
  },
  "severityIndex": 3.0
}
```

---

### 2. Get Example Request/Response

**GET** `/api/health-safety/example/`

Returns example request and response format for testing and documentation.

---

### 3. List Health & Safety Reports

**GET** `/api/health-safety/reports/`

List all stored health & safety reports.

**Query Parameters:**
- `project_name` - Filter by project name (case-insensitive)
- `date` - Filter by exact report date (YYYY-MM-DD)
- `date_from` - Filter reports from this date onwards
- `date_to` - Filter reports up to this date

**Example:**
```
GET /api/health-safety/reports/?project_name=Highway
```

---

### 4. Create Health & Safety Report

**POST** `/api/health-safety/reports/`

Create a new health & safety report in the database.

**Request Body:**
```json
{
  "project_name": "Highway Construction",
  "report_date": "2024-01-15",
  "total_manhours": 500000,
  "fatalities": 0,
  "significant": 1,
  "major": 2,
  "minor": 5,
  "near_miss": 10
}
```

---

### 5. Get Specific Report

**GET** `/api/health-safety/reports/{id}/`

Get a specific health & safety report by ID.

---

### 6. Update Health & Safety Report

**PUT** `/api/health-safety/reports/{id}/`

Update an existing report (full update).

**PATCH** `/api/health-safety/reports/{id}/`

Partial update of a report.

---

### 7. Delete Health & Safety Report

**DELETE** `/api/health-safety/reports/{id}/`

Delete a health & safety report.

---

## Calculation Logic

### Total Incidents
```
totalIncidents = fatalities + significant + major + minor + nearMiss
```

### Incident Rate (per 1,000,000 manhours)
```
incidentRate = (totalIncidents / totalManhours) * 1,000,000
```

### Severity Score
```
severityScore = (fatalities * 5) + (significant * 4) + (major * 3) + (minor * 2) + (nearMiss * 1)
```

### Safety Status Determination
| Condition | Status |
|-----------|--------|
| fatalities > 0 | `critical` |
| significant > 2 | `high_risk` |
| incidentRate > 50 | `moderate` |
| otherwise | `safe` |

---

## Pyramid Visualization

The API returns pyramid data ordered from most severe to least severe:

| Level | Color | Weight |
|-------|-------|--------|
| Fatalities | #000000 (Black) | 5 |
| Significant | #FF0000 (Red) | 4 |
| Major | #FFA500 (Orange) | 3 |
| Minor | #FFFF00 (Yellow) | 2 |
| Near Miss | #00FF00 (Green) | 1 |

---

## Alert Flags

| Flag | Description |
|------|-------------|
| `hasFatality` | True if any fatalities recorded |
| `highNearMiss` | True if near miss count > 10 |

---

## Severity Index

Normalized severity score from 0-100:
```
severityIndex = (severityScore / 1000) * 100
```

---

## Edge Cases Handled

- **Zero incidents**: Returns 0% for all categories, safe status
- **Zero manhours**: Returns 0 incident rate, avoids division by zero
- **Negative numbers**: Validates input, returns 400 error
- **Missing fields**: Returns validation error with details

---

## Running the API

The server should be running on port 8000. Access the Swagger documentation at:
```
http://127.0.0.1:8000/swagger/
```

---

## Testing

Test the status endpoint:
```bash
curl -X POST http://127.0.0.1:8000/api/health-safety/status/ \
  -H "Content-Type: application/json" \
  -d '{"totalManhours": 500000, "incidents": {"fatalities": 0, "significant": 1, "major": 2, "minor": 5, "nearMiss": 10}}'
```

Test with critical status (fatality):
```bash
curl -X POST http://127.0.0.1:8000/api/health-safety/status/ \
  -H "Content-Type: application/json" \
  -d '{"totalManhours": 100000, "incidents": {"fatalities": 1, "significant": 0, "major": 0, "minor": 0, "nearMiss": 0}}'
```

Test with high risk status:
```bash
curl -X POST http://127.0.0.1:8000/api/health-safety/status/ \
  -H "Content-Type: application/json" \
