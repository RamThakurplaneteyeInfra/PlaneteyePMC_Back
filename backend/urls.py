from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from rest_framework import permissions

from accounts.auth_views import CustomTokenObtainPairView, TokenRefreshViewAllowAny

# Health check endpoint
def health_check(request):
    return JsonResponse({'status': 'healthy', 'service': 'PMC Backend'})

# Swagger/OpenAPI Schema View
schema_view = get_schema_view(
   openapi.Info(
      title="DPR API Documentation",
      default_version='v1',
      description=(
          "PMC API. Login via POST /api/token/ then send "
          "Authorization: Bearer <access_token> on protected routes."
      ),
      terms_of_service="https://www.google.com/policies/terms/",
      contact=openapi.Contact(email="contact@example.com"),
      license=openapi.License(name="BSD License"),
   ),
   public=True,
   permission_classes=(permissions.AllowAny,),
)


def api_root_help(request):
    """
    Browsers cannot open http://0.0.0.0:8000/ (ERR_ADDRESS_INVALID).
    Use 127.0.0.1 or localhost instead.
    """
    base = f"{request.scheme}://{request.get_host()}"
    return HttpResponse(
        f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>PMC API</title>
<style>body{{font-family:system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;line-height:1.5}}
code{{background:#f4f4f4;padding:.15rem .4rem;border-radius:4px}}</style></head><body>
<h1>PMC Backend</h1>
<p><a href="/swagger/"><strong>Swagger UI</strong></a> · <a href="/redoc/">ReDoc</a> · <a href="/admin/">Admin</a></p>
<p><strong>Swagger URL to use in your browser:</strong><br>
<code>{base}/swagger/</code></p>
<p><strong>Do not use</strong> <code>http://0.0.0.0:8000</code> in the address bar — that is invalid in browsers.
Use <code>http://127.0.0.1:8000/swagger/</code> or <code>http://localhost:8000/swagger/</code> instead
(when the server is bound with <code>runserver 0.0.0.0:8000</code>, that only means “listen on all interfaces”).</p>
</body></html>""",
        content_type="text/html; charset=utf-8",
    )


urlpatterns = [
    path('', api_root_help),
    path('admin/', admin.site.urls),
    
    # Swagger/OpenAPI Documentation
    re_path(r'^swagger(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    re_path(r'^swagger/$', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    re_path(r'^redoc/$', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    

    # JWT login (frontend uses /api/token/)
    path('api/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshViewAllowAny.as_view(), name='token_refresh'),
    # JWT auth aliases
    path('api/auth/', include('accounts.auth_urls')),
    # User profile (legacy path — JWT required)
    path('api/accounts/', include('accounts.urls')),
    # HO / Admin User Management (Team Leaders & Engineers)
    path('api/', include('accounts.user_management_urls')),
    # In-app alerts
    path('api/alerts/', include('accounts.alerts_urls')),
    # Projects and Sites API
    path('api/projects-data/', include('projects.urls')),
    # Project Initialization API (PMC Head)
    path('api/', include('projects.urls')),
    # Tasks and Reports API
    path('api/operations/', include('operations.urls')),
    # Daily Progress Report API
    path('api/', include('dpr.urls')),
    # Contracts API
    path('api/', include('contracts.urls')),
    # Invoicing Information API
    path('api/', include('invoicing.urls')),
    # Contract Performance API
    path('api/', include('contract_performance.urls')),
    # Project Progress Status API
    path('api/', include('project_progress.urls')),
    # Budget vs Cost Performance (EVM)
    path('api/', include('budget_performance.urls')),
    path('api/', include('equipment.urls')),
    path('api/', include('manpower_management.urls')),
    path('api/', include('manpower.urls')),
    path('api/', include('cashflow.urls')),
    path('api/', include('cost_performance.urls')),
    # Plant & Machinery Site Asset Inventory Management API
    path('api/', include('plant_machinery.urls')),
    # Health & Safety API (monthly records + analytics)
    # → /api/health-safety/                    — monthly CRUD + aggregation
    # → /api/health-safety/status/             — analytics calculator
    # → /api/health-safety/example/            — example payload
    # → /api/health-safety/reports/            — legacy date-based reports
    path('api/health-safety/', include('health_safety.urls')),
    # Legacy cumulative HSE records (project-wise, camelCase)
    # → /api/hse/  /api/hse/{id}/  /api/hse/project/{projectName}/
    path('api/', include('health_safety.hse_urls')),
    # Health Check
    path('api/health/', health_check, name='health-check'),
    path('api/system/', include('core.urls')),
    # Monthly Scope API
    path('api/monthly-scope/', include('monthly_scope.urls')),
    # Notifications API
    path('api/notifications/', include('notifications.urls')),

    # Internal scheduler hooks (shared-secret auth — no JWT)
    path('api/internal/dpr/', include('dpr.internal_urls')),

    # Notifications Test Page
    path('notifications/', include('notifications.urls')),

    # Drawings Management API
    path('api/', include('drawings.urls')),

    # Correspondence document tracking API
    # → /api/correspondence-documents/  (+ /dashboard/)
    path('api/', include('correspondence.urls')),

    # Planned vs Earned Value API
    path('api/', include('planned_earned_value.urls')),

    # Contract Values API (SCL + Contractor, single scalable API)
    path('api/', include('contract_values.urls')),

    # Project Quality Status API
    path('api/', include('project_quality_status.urls')),

    # Monthly Construction Progress API
    path('api/', include('construction_progress.urls')),

    # Monthly Project Equipment Tracking API
    path('api/', include('project_equipment.urls')),

    # Project Dates (SCL & Contractor) API
    path('api/', include('project_dates.urls')),

    # Contractor Master API
    path('api/', include('contractors.urls')),

    # Site Progress Images (S3 + Cloudinary fallback)
    path('api/', include('site_images.urls')),

    # Bottleneck register (Issue / Concern / Risk / Action)
    path('api/', include('bottlenecks.urls')),
    path('api/', include('reminders.urls')),

    # Meeting Documents (MoM / EDL) stored in private S3
    path('api/', include('meeting_documents.urls')),

    # Testing Documents (PDF / image / video) stored in private S3 under testing/
    path('api/', include('testing_documents.urls')),

    # Project Feedback Management (issue workflow with optional S3 image attachment)
    path('api/', include('feedback_management.urls')),
    path('api/', include('tutorial_videos.urls')),

    # Monthly Progress Report (server-side aggregation preview)
    path('api/', include('mpr.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
