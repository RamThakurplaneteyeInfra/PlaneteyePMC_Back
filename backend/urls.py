from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from rest_framework import permissions

# Swagger/OpenAPI Schema View
schema_view = get_schema_view(
   openapi.Info(
      title="DPR API Documentation",
      default_version='v1',
      description="PMC API: DPR, Contracts, Cash flow, **Cost performance (EVM)**, Manpower, Equipment, Budget EVM. Swagger: **Cost performance**. All endpoints available without auth for testing.",
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
    
    # JWT Auth Endpoints
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    # User Profile API
    path('api/accounts/', include('accounts.urls')),
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
    path('api/', include('manpower.urls')),
    path('api/', include('cashflow.urls')),
    path('api/', include('cost_performance.urls')),
    # Health & Safety API
    path('api/health-safety/', include('health_safety.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
