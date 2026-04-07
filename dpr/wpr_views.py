from datetime import date, datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django.utils.dateparse import parse_date
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import DailyProgressReport
from .wpr_helpers import aggregate_dpr_activities_by_week
from .wpr_serializers import WPRSerializer


class WeeklyProgressReportAPIView(APIView):
    """
    Weekly Progress Report API
    
    Aggregates Daily Progress Report (DPR) data into weekly reports.
    
    Endpoint: /api/dpr/wpr/
    
    Query Parameters:
    - project_name: Filter by project name (case-insensitive) - Required
    
    Optional Parameters (for specific period):
    - month: Month (1-12) - Optional, if not provided returns latest available
    - year: Year (e.g., 2024) - Optional, if not provided returns latest available
    - week: Week number (1-5) - Optional, specific week only
    """
    
    permission_classes = [AllowAny]  # No authentication required for testing
    
    @swagger_auto_schema(
        operation_description="Get Weekly Progress Report aggregated from Daily Progress Reports. If month/year not provided, returns latest available data for the project.",
        manual_parameters=[
            openapi.Parameter(
                'project_name',
                openapi.IN_QUERY,
                description="Filter by project name (case-insensitive partial match)",
                type=openapi.TYPE_STRING,
                required=True
            ),
            openapi.Parameter(
                'month',
                openapi.IN_QUERY,
                description="Month (1-12) - Optional, if not provided returns latest available",
                type=openapi.TYPE_INTEGER,
                required=False,
                minimum=1,
                maximum=12
            ),
            openapi.Parameter(
                'year',
                openapi.IN_QUERY,
                description="Year (e.g., 2024) - Optional, if not provided returns latest available",
                type=openapi.TYPE_INTEGER,
                required=False,
                minimum=2000,
                maximum=2100
            ),
            openapi.Parameter(
                'week',
                openapi.IN_QUERY,
                description="Week number (1-5) - Optional, specific week only",
                type=openapi.TYPE_INTEGER,
                required=False,
                minimum=1,
                maximum=5
            ),
        ],
        responses={
            200: WPRSerializer,
            400: "Bad Request - Invalid parameters",
            404: "Not Found - No data found for the specified period"
        }
    )
    def get(self, request):
        """
        Get Weekly Progress Report for the specified project.
        
        If month/year are provided, returns data for that specific period.
        If not provided, automatically returns the latest available weekly report for the project.
        
        Aggregates DPR data by weeks and calculates:
        - Activity progress tracking
        - Weekly summaries
        - Deliverables, issues, remarks
        - Quality, billing, and drawing status
        """
        # Get query parameters
        month_str = request.query_params.get('month')
        year_str = request.query_params.get('year')
        week_str = request.query_params.get('week')
        project_name = request.query_params.get('project_name')
        
        # Validate required parameter
        if not project_name:
            return Response(
                {
                    'error': 'Missing required parameter',
                    'details': 'project_name parameter is required'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Initialize month and year
        month = None
        year = None
        
        # If month/year are provided, validate them
        if month_str or year_str:
            if not month_str or not year_str:
                return Response(
                    {
                        'error': 'Invalid parameters',
                        'details': 'Both month and year must be provided together'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                month = int(month_str)
                year = int(year_str)
                
                if not (1 <= month <= 12):
                    raise ValueError("Month must be between 1 and 12")
                
                if year < 2000 or year > 2100:
                    raise ValueError("Year must be between 2000 and 2100")
                    
            except ValueError as e:
                return Response(
                    {
                        'error': 'Invalid parameters',
                        'details': str(e)
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Validate optional week parameter
        week = None
        if week_str:
            try:
                week = int(week_str)
                if not (1 <= week <= 5):
                    raise ValueError("Week must be between 1 and 5")
            except ValueError as e:
                return Response(
                    {
                        'error': 'Invalid week parameter',
                        'details': str(e)
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Build DPR queryset with project filter
        # Use case-insensitive search with PostgreSQL
        queryset = DailyProgressReport.objects.filter(
            project_name__iexact=project_name
        )
        
        # If no exact match, try icontains as fallback
        if not queryset.exists():
            queryset = DailyProgressReport.objects.filter(
                project_name__icontains=project_name
            )
        
        # If month/year are not specified, get the latest available data
        if month is None or year is None:
            # Get the latest report date for this project
            latest_dpr = queryset.order_by('-report_date').first()
            if not latest_dpr:
                return Response(
                    {
                        'error': 'No data found',
                        'details': f'No Daily Progress Reports found for project "{project_name}"'
                    },
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Use the month/year from the latest report
            latest_date = latest_dpr.report_date
            month = latest_date.month
            year = latest_date.year
        
        # Filter by month/year
        queryset = queryset.filter(
            report_date__year=year,
            report_date__month=month
        )
        
        # Check if we have any data
        if not queryset.exists():
            return Response(
                {
                    'error': 'No data found',
                    'details': f'No Daily Progress Reports found for project "{project_name}" in {month}/{year}'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Aggregate data by week
        try:
            aggregated_data = aggregate_dpr_activities_by_week(
                queryset, 
                year, 
                month, 
                week
            )
            
            # If specific week was requested but no data found
            if week and not aggregated_data['weeks']:
                return Response(
                    {
                        'error': 'No data found',
                        'details': f'No data found for Week {week} of project "{project_name}" in {month}/{year}'
                    },
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Add metadata about the period returned
            response_data = {
                'project_name': project_name,
                'period': {
                    'month': month,
                    'year': year,
                    'auto_selected': month_str is None or year_str is None
                },
                'weeks': aggregated_data['weeks'],
                'project_summary': aggregated_data['project_summary']
            }
            
            # Serialize the response
            serializer = WPRSerializer(response_data)
            
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {
                    'error': 'An error occurred while aggregating data',
                    'details': str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
