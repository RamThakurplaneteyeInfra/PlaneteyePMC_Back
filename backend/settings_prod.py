"""
Production settings for backend project.
"""
import os

import dj_database_url

from .settings import *  # noqa: F403, F401

# SECURITY
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise Exception('SECRET_KEY environment variable must be set in production.')

DEBUG = False

_allowed_hosts_env = os.environ.get('ALLOWED_HOSTS', '')
ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_env.split(',') if h.strip()]
if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ['*']

# Render / common PaaS hostnames (leading dot = all subdomains)
for _host in ('.onrender.com', '.vercel.app'):
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
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Site image uploads: up to 20 × 10 MB (+ multipart overhead)
DATA_UPLOAD_MAX_MEMORY_SIZE = 262144000  # 250 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 262144000

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
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# CSRF — full origins only (no wildcards). Add Render URL from env.
_render_external = (os.environ.get('RENDER_EXTERNAL_URL') or '').rstrip('/')
if _render_external and _render_external not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(_render_external)

_csrf_env = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
for _origin in _csrf_env.split(','):
    _origin = _origin.strip()
    if _origin and _origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_origin)

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# ================= CORS — allow all origins =================
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^.+$",  # match any non-empty Origin (http/https, any host/port)
]
CORS_ALLOW_CREDENTIALS = True

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
        'site_images': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
