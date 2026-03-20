# Health & Safety Views
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import HealthSafetyReport
from .serializers import HealthSafetyReportSerializer
from .services import calculate_health_safety_status, validate_input


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
        data = request.data
        
        # Validate input data
        if not data:
            return Response(
                {'error': 'Request body is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Calculate health & safety status using service
        result = calculate_health_safety_status(data)
        
        return Response(result, status=status.HTTP_200_OK)
        
    except ValueError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
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
    example_request = {
        "totalManhours": 500000,
        "incidents": {
            "fatalities": 0,
            "significant": 1,
            "major": 2,
            "minor": 5,
            "nearMiss": 10
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
            "nearMiss": {"count": 10, "percentage": 55.56}
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
    
    return Response({
        'request': example_request,
        'response': example_response
    })


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
    
    def get_queryset(self):
        """Filter reports by query parameters"""
        queryset = HealthSafetyReport.objects.all()
        
        # Filter by project_name
        project_name = self.request.query_params.get('project_name', None)
        if project_name:
            queryset = queryset.filter(project_name__icontains=project_name)
        
        # Filter by date
        report_date = self.request.query_params.get('date', None)
        if report_date:
            queryset = queryset.filter(report_date=report_date)
        
        # Filter by date range
        date_from = self.request.query_params.get('date_from', None)
        if date_from:
            queryset = queryset.filter(report_date__gte=date_from)
        
        date_to = self.request.query_params.get('date_to', None)
        if date_to:
            queryset = queryset.filter(report_date__lte=date_to)
        
        return queryset.order_by('-report_date', '-created_at')
    
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
