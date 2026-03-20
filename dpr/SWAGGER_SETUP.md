# Swagger/OpenAPI Documentation Setup

## Installation

Install the required package:

```bash
pip install drf-yasg
```

Or add to `requirements.txt`:

```
drf-yasg>=1.21.7
```

## Access Swagger UI

After starting the server, access Swagger documentation at:

- **Swagger UI**: http://localhost:8000/swagger/
- **ReDoc**: http://localhost:8000/redoc/
- **OpenAPI JSON**: http://localhost:8000/swagger.json
- **OpenAPI YAML**: http://localhost:8000/swagger.yaml

## Features

✅ Interactive API documentation
✅ Try out endpoints directly from the browser
✅ View request/response schemas
✅ Filter parameters documentation
✅ Authentication information (if needed)
✅ Model schemas and validation rules

## Usage

1. Start the Django server:
   ```bash
   python manage.py runserver
   ```

2. Open your browser and navigate to:
   ```
   http://localhost:8000/swagger/
   ```

3. Explore the DPR API endpoints:
   - Click on any endpoint to expand it
   - View request/response schemas
   - Click "Try it out" to test endpoints directly
   - Fill in parameters and execute requests

## DPR Endpoints in Swagger

All DPR endpoints are documented with:
- Request body schemas
- Response schemas
- Query parameters
- Example values
- Validation rules

## Notes

- Swagger UI works best in Chrome/Firefox
- All DPR endpoints are marked as public (no authentication required)
- You can test all CRUD operations directly from Swagger UI
