"""
Production settings for backend project.
"""
import os

import dj_database_url

from .settings import *  # noqa: F403, F401


def _split_env_list(value: str) -> list[str]:
    """Parse comma-separated env values and strip wrapping quotes."""
    items = []
    for part in (value or '').split(','):
        item = part.strip().strip('"').strip("'").strip()
        if item:
            items.append(item)
    return items


# SECURITY
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise Exception('SECRET_KEY environment variable must be set in production.')

DEBUG = False

ALLOWED_HOSTS = _split_env_list(os.environ.get('ALLOWED_HOSTS', ''))

# Railway injects the public hostname — use it when ALLOWED_HOSTS is unset.
_railway_domain = (
    os.environ.get('RAILWAY_PUBLIC_DOMAIN')
    or os.environ.get('RAILWAY_STATIC_URL')
    or ''
).strip()
if _railway_domain:
    # RAILWAY_STATIC_URL may be a full URL
    if '://' in _railway_domain:
        from urllib.parse import urlparse

        _railway_domain = urlparse(_railway_domain).hostname or ''
    if _railway_domain and _railway_domain not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_railway_domain)

# Always allow the service hostname used in this 502 report pattern when provided via env.
_extra_host = os.environ.get('RAILWAY_SERVICE_DOMAIN', '').strip()
if _extra_host and _extra_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_extra_host)

if not ALLOWED_HOSTS:
    # Last-resort Railway default so a missing env var does not 502 the service.
    # Prefer setting ALLOWED_HOSTS explicitly in Railway Variables.
    ALLOWED_HOSTS = ['.up.railway.app']
    import logging

    logging.getLogger('django').warning(
        'ALLOWED_HOSTS unset — defaulting to .up.railway.app. '
        'Set ALLOWED_HOSTS explicitly in Railway Variables.'
    )

# Known Vercel backend host (PlanetEye PMC API).
for _host in ('planeteye-pmc-back-4fa2.vercel.app',):
    if _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)
# When running on Vercel, also accept the platform wildcard host pattern.
if os.environ.get('VERCEL') and '.vercel.app' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('.vercel.app')

# Optional PaaS hostnames when explicitly enabled
if os.environ.get('ALLOW_RENDER_HOSTS', '').lower() in ('1', 'true', 'yes'):
    for _host in ('.onrender.com', '.vercel.app', '.up.railway.app'):
        if _host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_host)

# DATABASE (Render PostgreSQL / Neon)
_database_url = os.environ.get('DATABASE_URL')
if _database_url:
    DATABASES = {
        'default': dj_database_url.parse(
            _database_url,
            conn_max_age=600,
            ssl_require=True,
        )
    }
else:
    _db_required = all(
        os.environ.get(k)
        for k in ('DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST')
    )
    if not _db_required:
        raise Exception(
            'Production requires DATABASE_URL or DB_NAME, DB_USER, '
            'DB_PASSWORD, and DB_HOST environment variables.'
        )
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME'),
            'USER': os.environ.get('DB_USER'),
            'PASSWORD': os.environ.get('DB_PASSWORD'),
            'HOST': os.environ.get('DB_HOST'),
            'PORT': os.environ.get('DB_PORT', '5432'),
            'OPTIONS': (
                {'sslmode': 'require'}
                if os.environ.get('DB_SSL', 'true').lower() == 'true'
                else {}
            ),
        }
    }

# ================= STATIC FILES (Render + WhiteNoise) =================
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# CompressedStaticFilesStorage avoids manifest missing-file failures on deploy.
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

# ================= MEDIA FILES =================
MEDIA_URL = '/media/'
# Vercel / Lambda: project disk is read-only — only /tmp is writable.
# Organization logos still prefer S3; this avoids hard crashes for any local FileField spill.
if os.environ.get('VERCEL') or os.environ.get('AWS_LAMBDA_FUNCTION_NAME'):
    MEDIA_ROOT = os.path.join('/tmp', 'pmc_media')
else:
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Site image uploads: up to 20 × 10 MB (+ multipart overhead).
# Keep total request body limit high so existing large uploads still succeed.
# Cap per-file in-memory buffering so large files spill to TemporaryUploadedFile.
DATA_UPLOAD_MAX_MEMORY_SIZE = 262144000  # 250 MB (unchanged total request limit)
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5 MB → TemporaryUploadedFile above this

# ================= MIDDLEWARE (order matters for CORS + static) =================
_EXCLUDED_MIDDLEWARE = {
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
}
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
] + [m for m in MIDDLEWARE if m not in _EXCLUDED_MIDDLEWARE]

# ================= SECURITY SETTINGS =================
# Behind Railway/Render reverse proxies, trust X-Forwarded-Proto for HTTPS.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# Default OFF: Railway internal health checks are plain HTTP and break with
# SECURE_SSL_REDIRECT=true (marks service unhealthy → 502 Bad Gateway).
# Edge TLS is terminated by Railway; enable only if you know health checks use HTTPS.
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'false').lower() in (
    '1',
    'true',
    'yes',
)
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True

# CSRF — full origins only (no wildcards). Add Render URL from env.
_render_external = (os.environ.get('RENDER_EXTERNAL_URL') or '').rstrip('/')
if _render_external and _render_external not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(_render_external)

for _origin in _split_env_list(os.environ.get('CSRF_TRUSTED_ORIGINS', '')):
    if _origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_origin)

# Hosted FE + local Vite (CSRF requires scheme + host; no wildcards).
_DEFAULT_FRONTEND_ORIGINS = [
    'https://planeteye-pmc-front.vercel.app',
    'http://localhost:5173',
    'http://localhost:5174',
    'http://localhost:5175',
    'http://localhost:5176',
    'http://localhost:5177',
    'http://localhost:5178',
    'http://localhost:5179',
    'http://127.0.0.1:5173',
    'http://127.0.0.1:5174',
    'http://127.0.0.1:5175',
    'http://127.0.0.1:5176',
    'http://127.0.0.1:5177',
    'http://127.0.0.1:5178',
    'http://127.0.0.1:5179',
]
for _origin in _DEFAULT_FRONTEND_ORIGINS:
    if _origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_origin)

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# ================= CORS — explicit origins (required for browser FE) =================
# Prefer CORS_ALLOWED_ORIGINS env on Vercel; code defaults cover hosted FE + Vite.
# Never use CORS_ALLOW_ALL_ORIGINS with credentials (browsers reject *).
CORS_ALLOWED_ORIGINS = _split_env_list(os.environ.get('CORS_ALLOWED_ORIGINS', ''))
# Reuse CSRF trusted origins if CORS list was not set (avoids boot crash / 502).
if not CORS_ALLOWED_ORIGINS:
    CORS_ALLOWED_ORIGINS = _split_env_list(os.environ.get('CSRF_TRUSTED_ORIGINS', ''))
for _origin in _DEFAULT_FRONTEND_ORIGINS:
    if _origin not in CORS_ALLOWED_ORIGINS:
        CORS_ALLOWED_ORIGINS.append(_origin)
CORS_ALLOW_ALL_ORIGINS = False
# 5170–5179 covers busy Vite ports without listing every one.
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost:517\d$",
    r"^http://127\.0\.0\.1:517\d$",
    r"^https://planeteye-pmc-front\.vercel\.app$",
    r"^https://.*\.ngrok(-free)?\.app$",
    r"^https://.*\.ngrok\.io$",
]
CORS_ALLOW_CREDENTIALS = True
if not CORS_ALLOWED_ORIGINS:
    # Boot without crashing; browser clients will get CORS errors until configured.
    import logging

    logging.getLogger('django').warning(
        'CORS_ALLOWED_ORIGINS is empty — set it to your frontend origin(s), '
        'e.g. https://planeteye-pmc-front.vercel.app'
    )

# ================= CHANNELS =================
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

# ================= LOGGING =================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'pmc.throttling': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'site_images': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'celery': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'pmc.dpr.email': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'services.email_utils': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
