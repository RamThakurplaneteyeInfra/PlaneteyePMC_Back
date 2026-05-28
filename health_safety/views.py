# Health & Safety Views
import logging
from django.core.cache import cache
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.pagination import PageNumberPagination
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import HealthSafetyReport
from .serializers import HealthSafetyReportSerializer, HealthSafetyInputSerializer
from .services import calculate_health_safety_status, validate_input

logger = logging.getLogger(__name__)


# =============================================================================
# API ENDPOINTS
# =============================================================================

@swagger_auto_schema(
    method='post',
    operation_description="""
    Calculate Health & Safety Status based on incident data and manhours.
    
    **Pyramid Model Logic:**
    - Total Incidents = sum of all incident types
    - Incident Rate = (totalIncidents / totalManhours) * 1,000,000
    - Severity Score = (fatalities*5) + (significant*4) + (major*3) + (minor*2) + (nearMiss*1)
    
    **Safety Status Logic:**
    - fatalities > 0 → "critical"
    - significant > 2 → "high_risk"  
    - incidentRate > 50 → "moderate"
    - otherwise → "safe"
    
    **Example Request:**
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
    """,
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=['totalManhours', 'incidents'],
        properties={
            'totalManhours': openapi.Schema(
                type=openapi.TYPE_NUMBER,
                description='Total manhours worked',
                example=500000
            ),
            'incidents': openapi.Schema(
                type=openapi.TYPE_OBJECT,
                description='Incident counts by category',
                properties={
                    'fatalities': openapi.Schema(type=openapi.TYPE_INTEGER, example=0),
                    'significant': openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                    'major': openapi.Schema(type=openapi.TYPE_INTEGER, example=2),
                    'minor': openapi.Schema(type=openapi.TYPE_INTEGER, example=5),
                    'nearMiss': openapi.Schema(type=openapi.TYPE_INTEGER, example=10),
                }
            )
        }
    ),
    responses={
        200: openapi.Response(
            description="Health & Safety Status calculated successfully",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'summary': openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            'totalManhours': openapi.Schema(type=openapi.TYPE_NUMBER),
                            'totalIncidents': openapi.Schema(type=openapi.TYPE_INTEGER),
                            'incidentRate': openapi.Schema(type=openapi.TYPE_NUMBER),
                            'severityScore': openapi.Schema(type=openapi.TYPE_INTEGER),
                            'status': openapi.Schema(type=openapi.TYPE_STRING, enum=['safe', 'moderate', 'high_risk', 'critical']),
                        }
                    ),
                    'breakdown': openapi.Schema(type=openapi.TYPE_OBJECT),
                    'pyramid': openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_OBJECT)),
                    'insights': openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_STRING)),
                }
            )
        ),
        400: "Bad Request - Invalid input data"
    }
)
@api_view(['POST'])
@permission_classes([AllowAny])
def health_safety_status(request):
    """
    POST /api/health-safety/status/

    Calculate health & safety status from incident data.
    Returns complete response with summary, breakdown, pyramid data, and insights.
    """
    try:
        # Validate input using serializer
        serializer = HealthSafetyInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': 'Validation failed', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Generate cache key from validated data
        cache_key = f"health_safety_status:{hash(str(serializer.validated_data))}"
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        # Calculate health & safety status using service
        result = calculate_health_safety_status(serializer.validated_data)

        cache.set(cache_key, result, 300)  # 5 minutes
        return Response(result, status=status.HTTP_200_OK)

    except ValueError as e:
        logger.warning(f"Health safety status validation error: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Health safety status calculation error: {e}")
        return Response(
            {'error': 'An error occurred', 'message': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@swagger_auto_schema(
    method='get',
    operation_description="""
    Get example request/response format for Health & Safety Status API.
    Useful for testing and documentation.
    """,
    responses={
        200: "Example request and response format"
    }
)
@api_view(['GET'])
@permission_classes([AllowAny])
def health_safety_example(request):
    """
    GET /api/health-safety/example/

    Returns example request and response format.
    """
    cache_key = "health_safety_example"
    data = cache.get(cache_key)
    if data is not None:
        return Response(data)

    example_request = {
        "totalManhours": 500000,
        "incidents": {
            "fatalities": 0,
            "significant": 1,
            "major": 2,
            "minor": 5,
            "near_miss": 10
        }
    }

    example_response = {
        "summary": {
            "totalManhours": 500000,
            "totalIncidents": 18,
            "incidentRate": 36.0,
            "severityScore": 25,
            "status": "safe"
        },
        "breakdown": {
            "fatalities": {"count": 0, "percentage": 0.0},
            "significant": {"count": 1, "percentage": 5.56},
            "major": {"count": 2, "percentage": 11.11},
            "minor": {"count": 5, "percentage": 27.78},
            "near_miss": {"count": 10, "percentage": 55.56}
        },
        "pyramid": [
            {"label": "Fatalities", "value": 0, "color": "#000000"},
            {"label": "Significant", "value": 1, "color": "#FF0000"},
            {"label": "Major", "value": 2, "color": "#FFA500"},
            {"label": "Minor", "value": 5, "color": "#FFFF00"},
            {"label": "Near Miss", "value": 10, "color": "#00FF00"}
        ],
        "insights": [
            "Safety status is good - maintain current practices",
            "1 significant incident(s) need investigation",
            "2 major incident(s) require follow-up",
            "5 minor incident(s) recorded",
            "10 near miss(es) indicate potential future risks"
        ],
        "alerts": {
            "hasFatality": False,
            "highNearMiss": True
        },
        "severityIndex": 2.5
    }

    data = {
        'request': example_request,
        'response': example_response
    }

    cache.set(cache_key, data, 300)  # 5 minutes
    return Response(data)


# =============================================================================
# MODEL VIEW SET (For storing reports in database)
# =============================================================================

class HealthSafetyReportViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Health & Safety Report CRUD operations

    Supports:
    - GET /api/health-safety/reports/ - List all reports
    - GET /api/health-safety/reports/{id}/ - Get specific report
    - POST /api/health-safety/reports/ - Create new report
    - PUT /api/health-safety/reports/{id}/ - Update report
    - DELETE /api/health-safety/reports/{id}/ - Delete report
    """
    queryset = HealthSafetyReport.objects.all()
    serializer_class = HealthSafetyReportSerializer
    permission_classes = [AllowAny]  # No authentication for testing
    pagination_class = PageNumberPagination
    
    def get_queryset(self):
        """Filter reports by query parameters"""
        queryset = HealthSafetyReport.objects.only(
            "id", "project_name", "report_date", "total_manhours",
            "fatalities", "significant", "major", "minor", "near_miss",
            "created_at", "updated_at"
        )

        # Filter by project_name
        project_name = self.request.query_params.get('project_name', None)
        if project_name:
            queryset = queryset.filter(project_name__icontains=project_name.strip())

        # Filter by date
        report_date = self.request.query_params.get('date', None)
        if report_date:
            queryset = queryset.filter(report_date=report_date.strip() if report_date else None)

        # Filter by date range
        date_from = self.request.query_params.get('date_from', None)
        if date_from:
            queryset = queryset.filter(report_date__gte=date_from.strip() if date_from else None)

        date_to = self.request.query_params.get('date_to', None)
        if date_to:
            queryset = queryset.filter(report_date__lte=date_to.strip() if date_to else None)

        return queryset.order_by('-report_date', '-created_at')

    def list(self, request, *args, **kwargs):
        cache_key = f"health_safety_reports:{request.get_full_path()}"
        data = cache.get(cache_key)
        if data is not None:
            return Response(data)

        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, 300)  # 5 minutes
        return response

    def _invalidate_health_safety_cache(self):
        """
        Safely invalidate health & safety cache.
        Works with LocMemCache (development) and Redis (production).
        """
        try:
            if hasattr(cache, 'delete_pattern'):
                cache.delete_pattern("health_safety_reports:*")
            else:
                cache.clear()
        except Exception:
            try:
                cache.clear()
            except Exception:
                pass

    def perform_create(self, serializer):
        super().perform_create(serializer)
        # Cache invalidation (safe for LocMemCache)
        self._invalidate_health_safety_cache()

    def perform_update(self, serializer):
        super().perform_update(serializer)
        # Cache invalidation (safe for LocMemCache)
        self._invalidate_health_safety_cache()

    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        # Cache invalidation (safe for LocMemCache)
        self._invalidate_health_safety_cache()

    def create(self, request, *args, **kwargs):
        """Create a new Health & Safety Report"""
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': 'Validation failed', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# =============================================================================
# HSE RECORD VIEWSET
# Project-wise HSE CRUD — one record per project.
# Endpoints (mounted at /api/hse/ in backend/urls.py):
#   POST   /api/hse/                          -> create HSE record
#   GET    /api/hse/                          -> list all records (paginated)
#   GET    /api/hse/{id}/                     -> retrieve by ID
#   PUT    /api/hse/{id}/                     -> full update
#   PATCH  /api/hse/{id}/                     -> partial update
#   DELETE /api/hse/{id}/                     -> delete
#   GET    /api/hse/project/{projectName}/    -> lookup by project name
# =============================================================================

from .models import HSERecord
from .serializers import HSERecordSerializer

_HSE_CACHE_KEY_LIST = "hse_records_list"
_HSE_CACHE_TIMEOUT = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Swagger schema helpers
# ---------------------------------------------------------------------------

_HSE_POST_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["projectName"],
    properties={
        "projectName": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Unique project name",
            example="Atlas Tower",
        ),
        "fatalities": openapi.Schema(
            type=openapi.TYPE_INTEGER, description="Fatality count (≥ 0)", example=0
        ),
        "significant": openapi.Schema(
            type=openapi.TYPE_INTEGER, description="Significant incident count (≥ 0)", example=1
        ),
        "major": openapi.Schema(
            type=openapi.TYPE_INTEGER, description="Major incident count (≥ 0)", example=2
        ),
        "minor": openapi.Schema(
            type=openapi.TYPE_INTEGER, description="Minor incident count (≥ 0)", example=5
        ),
        "nearMiss": openapi.Schema(
            type=openapi.TYPE_INTEGER, description="Near-miss count (≥ 0)", example=10
        ),
        "totalManhours": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Total manhours worked (≥ 0)",
            example=500000,
        ),
        "lossOfManhours": openapi.Schema(
            type=openapi.TYPE_NUMBER,
            description="Manhours lost due to incidents (≥ 0, ≤ totalManhours)",
            example=120,
        ),
    },
)

_HSE_RESPONSE_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
        "message": openapi.Schema(
            type=openapi.TYPE_STRING, example="HSE record created successfully"
        ),
        "data": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "id": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                "projectName": openapi.Schema(type=openapi.TYPE_STRING, example="Atlas Tower"),
                "fatalities": openapi.Schema(type=openapi.TYPE_INTEGER, example=0),
                "significant": openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                "major": openapi.Schema(type=openapi.TYPE_INTEGER, example=2),
                "minor": openapi.Schema(type=openapi.TYPE_INTEGER, example=5),
                "nearMiss": openapi.Schema(type=openapi.TYPE_INTEGER, example=10),
                "totalManhours": openapi.Schema(type=openapi.TYPE_NUMBER, example=500000),
                "lossOfManhours": openapi.Schema(type=openapi.TYPE_NUMBER, example=120),
                "totalIncidents": openapi.Schema(type=openapi.TYPE_INTEGER, example=18),
                "ltifr": openapi.Schema(type=openapi.TYPE_NUMBER, example=0.24),
                "incidentRate": openapi.Schema(type=openapi.TYPE_NUMBER, example=36.0),
                "created_at": openapi.Schema(type=openapi.TYPE_STRING, example="2024-01-15T10:30:00Z"),
                "updated_at": openapi.Schema(type=openapi.TYPE_STRING, example="2024-01-15T10:30:00Z"),
            },
        ),
    },
)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class HSERecordPagination(PageNumberPagination):
    """Pagination for HSE records (20 per page, configurable up to 100)."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# ---------------------------------------------------------------------------
# ViewSet
# ---------------------------------------------------------------------------

class HSERecordViewSet(viewsets.ModelViewSet):
    """
    HSE Record Management ViewSet.

    One record per project — tracks cumulative incident counts and manhour data.
    All endpoints return a uniform {success, message, data} envelope.

    Computed KPI fields returned on every response (never sent by client):
      - totalIncidents  : sum of all incident categories
      - ltifr           : Lost Time Injury Frequency Rate
      - incidentRate    : Total incidents per 1,000,000 manhours

    Scalable for future additions:
      - monthly HSE tracking
      - incident history
      - safety score calculation
      - LTIFR / TRIR calculations
      - project-wise HSE analytics
      - charts and KPI cards
    """

    queryset = HSERecord.objects.all()
    serializer_class = HSERecordSerializer
    permission_classes = [AllowAny]
    pagination_class = HSERecordPagination

    # -------------------------------------------------------------------------
    # Queryset
    # -------------------------------------------------------------------------

    def get_queryset(self):
        """
        Optimised queryset.
        Supports optional ?project_name= filter for project-wise filtering.
        """
        qs = HSERecord.objects.only(
            "id",
            "projectName",
            "fatalities",
            "significant",
            "major",
            "minor",
            "nearMiss",
            "totalManhours",
            "lossOfManhours",
            "created_at",
            "updated_at",
        )

        # Optional project-wise filter: ?project_name=Atlas
        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(projectName__icontains=project_name.strip())

        return qs

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _invalidate_cache(self):
        """Invalidate the list cache whenever data changes."""
        cache.delete(_HSE_CACHE_KEY_LIST)

    def _success(self, message: str, data, http_status=status.HTTP_200_OK):
        """Uniform success response: {success, message, data}."""
        return Response(
            {"success": True, "message": message, "data": data},
            status=http_status,
        )

    def _error(self, message: str, errors=None, http_status=status.HTTP_400_BAD_REQUEST):
        """Uniform error response: {success, message, errors?}."""
        payload = {"success": False, "message": message}
        if errors is not None:
            payload["errors"] = errors
        return Response(payload, status=http_status)

    # -------------------------------------------------------------------------
    # CREATE  POST /api/hse/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Create HSE Record",
        operation_description=(
            "Create a new HSE record for a project. "
            "totalIncidents, ltifr, and incidentRate are auto-calculated."
        ),
        request_body=_HSE_POST_SCHEMA,
        responses={
            201: openapi.Response("Created", _HSE_RESPONSE_SCHEMA),
            400: "Validation error",
        },
        tags=["HSE Records"],
    )
    def create(self, request, *args, **kwargs):
        """
        Create or update a project-level HSE record (upsert by projectName).

        If a record already exists for the given projectName it is updated
        in-place rather than returning a 500 uniqueness error.
        Auto-calculates totalIncidents, ltifr, and incidentRate.
        """
        project_name = str(request.data.get("projectName", "")).strip()

        # Strip read-only / auto-calculated fields the frontend should not send
        _READ_ONLY = {"totalIncidents", "ltifr", "incidentRate", "id", "created_at", "updated_at"}
        payload = {k: v for k, v in request.data.items() if k not in _READ_ONLY}

        # Upsert: if a record already exists for this project, update it.
        existing = None
        if project_name:
            try:
                existing = HSERecord.objects.get(
                    projectName__iexact=project_name
                )
            except HSERecord.DoesNotExist:
                pass

        if existing is not None:
            serializer = HSERecordSerializer(
                existing, data=payload, partial=False
            )
        else:
            serializer = HSERecordSerializer(data=payload)

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            instance = serializer.save()
        except Exception as exc:
            logger.error(f"HSE record create error: {exc}")
            return self._error(
                "Failed to save HSE record",
                errors=str(exc),
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        self._invalidate_cache()

        http_status = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        message = (
            "HSE record updated successfully"
            if existing
            else "HSE record created successfully"
        )

        return self._success(
            message,
            HSERecordSerializer(instance).data,
            http_status=http_status,
        )

    # -------------------------------------------------------------------------
    # LIST  GET /api/hse/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get All HSE Records",
        operation_description=(
            "Retrieve all HSE records. "
            "Supports optional ?project_name= filter and pagination."
        ),
        manual_parameters=[
            openapi.Parameter(
                "project_name",
                openapi.IN_QUERY,
                description="Filter by project name (case-insensitive partial match)",
                type=openapi.TYPE_STRING,
                required=False,
            ),
            openapi.Parameter(
                "page",
                openapi.IN_QUERY,
                description="Page number",
                type=openapi.TYPE_INTEGER,
                required=False,
            ),
            openapi.Parameter(
                "page_size",
                openapi.IN_QUERY,
                description="Records per page (max 100)",
                type=openapi.TYPE_INTEGER,
                required=False,
            ),
        ],
        responses={200: openapi.Response("OK", _HSE_RESPONSE_SCHEMA)},
        tags=["HSE Records"],
    )
    def list(self, request, *args, **kwargs):
        """
        Return all HSE records (paginated).
        Results are cached for 5 minutes; cache is invalidated on any write.
        """
        project_filter = request.query_params.get("project_name")
        page_param = request.query_params.get("page", "1")
        use_cache = not project_filter and page_param == "1"

        if use_cache:
            cached = cache.get(_HSE_CACHE_KEY_LIST)
            if cached is not None:
                return Response(cached)

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = HSERecordSerializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            payload = {
                "success": True,
                "message": "HSE records retrieved successfully",
                "data": paginated.data,
            }
            if use_cache:
                cache.set(_HSE_CACHE_KEY_LIST, payload, _HSE_CACHE_TIMEOUT)
            return Response(payload)

        serializer = HSERecordSerializer(queryset, many=True)
        payload = {
            "success": True,
            "message": "HSE records retrieved successfully",
            "data": serializer.data,
        }
        if use_cache:
            cache.set(_HSE_CACHE_KEY_LIST, payload, _HSE_CACHE_TIMEOUT)
        return Response(payload)

    # -------------------------------------------------------------------------
    # RETRIEVE  GET /api/hse/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get HSE Record by ID",
        responses={
            200: openapi.Response("OK", _HSE_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["HSE Records"],
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single HSE record by its primary key."""
        try:
            instance = HSERecord.objects.get(pk=kwargs["pk"])
        except HSERecord.DoesNotExist:
            return self._error("HSE record not found", http_status=status.HTTP_404_NOT_FOUND)

        return self._success(
            "HSE record retrieved successfully",
            HSERecordSerializer(instance).data,
        )

    # -------------------------------------------------------------------------
    # UPDATE  PUT /api/hse/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Update HSE Record",
        operation_description=(
            "Full or partial update of an HSE record. "
            "KPI fields (totalIncidents, ltifr, incidentRate) are recalculated automatically."
        ),
        request_body=_HSE_POST_SCHEMA,
        responses={
            200: openapi.Response("OK", _HSE_RESPONSE_SCHEMA),
            400: "Validation error",
            404: "Not found",
        },
        tags=["HSE Records"],
    )
    def update(self, request, *args, **kwargs):
        """
        Full update (PUT) of an HSE record.
        KPI fields are recalculated after update.
        """
        partial = kwargs.pop("partial", False)

        try:
            instance = HSERecord.objects.get(pk=kwargs["pk"])
        except HSERecord.DoesNotExist:
            return self._error("HSE record not found", http_status=status.HTTP_404_NOT_FOUND)

        _READ_ONLY = {"totalIncidents", "ltifr", "incidentRate", "id", "created_at", "updated_at"}
        payload = {k: v for k, v in request.data.items() if k not in _READ_ONLY}

        serializer = HSERecordSerializer(instance, data=payload, partial=partial)

        if not serializer.is_valid():
            return self._error("Invalid data provided", errors=serializer.errors)

        try:
            updated = serializer.save()
        except Exception as exc:
            logger.error(f"HSE record update error: {exc}")
            return self._error("Failed to update HSE record", errors=str(exc),
                               http_status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        self._invalidate_cache()

        return self._success(
            "HSE record updated successfully",
            HSERecordSerializer(updated).data,
        )

    def partial_update(self, request, *args, **kwargs):
        """PATCH — partial update, delegates to update() with partial=True."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # -------------------------------------------------------------------------
    # DELETE  DELETE /api/hse/{id}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Delete HSE Record",
        responses={
            200: openapi.Response("OK"),
            404: "Not found",
        },
        tags=["HSE Records"],
    )
    def destroy(self, request, *args, **kwargs):
        """Delete an HSE record by its primary key."""
        try:
            instance = HSERecord.objects.get(pk=kwargs["pk"])
        except HSERecord.DoesNotExist:
            return self._error("HSE record not found", http_status=status.HTTP_404_NOT_FOUND)

        project_name = instance.projectName
        instance.delete()
        self._invalidate_cache()

        return self._success(
            f"HSE record for '{project_name}' deleted successfully",
            {},
        )

    # -------------------------------------------------------------------------
    # CUSTOM ACTION  GET /api/hse/project/{projectName}/
    # -------------------------------------------------------------------------

    @swagger_auto_schema(
        operation_summary="Get HSE Record by Project Name",
        operation_description=(
            "Retrieve an HSE record using the exact project name (case-insensitive). "
            "Useful for dashboard KPI lookups where the project name is known."
        ),
        responses={
            200: openapi.Response("OK", _HSE_RESPONSE_SCHEMA),
            404: "Not found",
        },
        tags=["HSE Records"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"project/(?P<projectName>[^/.]+)",
        url_name="by-project-name",
    )
    def get_by_project_name(self, request, projectName: str = None):
        """
        Retrieve an HSE record by exact project name (case-insensitive).
        Returns all KPI fields ready for dashboard card rendering.
        """
        if not projectName or not projectName.strip():
            return self._error("projectName is required.")

        try:
            instance = HSERecord.objects.get(projectName__iexact=projectName.strip())
        except HSERecord.DoesNotExist:
            return self._error(
                f"No HSE record found for project '{projectName}'",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        return self._success(
            "HSE record retrieved successfully",
            HSERecordSerializer(instance).data,
        )
