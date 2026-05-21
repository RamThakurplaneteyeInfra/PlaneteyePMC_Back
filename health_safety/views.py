# Health & Safety Views
import logging
from django.core.cache import cache
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
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
