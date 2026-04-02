# Render Deployment Setup - Summary

## Files Created

I've created the following files to help you deploy your Django backend to Render:

### 1. [`Dockerfile`](backend/Dockerfile)
- **Purpose**: Defines how to build your Docker image for production
- **Key Features**:
  - Uses Python 3.11 slim image (compatible with Django 6.0)
  - Installs system dependencies (PostgreSQL client, build tools)
  - Installs Python dependencies from [`requirements.txt`](backend/requirements.txt)
  - Installs Gunicorn for production WSGI server
  - Collects static files automatically
  - Runs on port 8000 with 3 Gunicorn workers

### 2. [`.dockerignore`](backend/.dockerignore)
- **Purpose**: Excludes unnecessary files from Docker build context
- **Benefits**: Faster builds, smaller image size
- **Excludes**: Git files, Python cache, IDE files, test files, documentation

### 3. [`render.yaml`](backend/render.yaml)
- **Purpose**: Infrastructure-as-code for Render deployment
- **Features**:
  - Defines web service configuration
  - Sets up PostgreSQL database automatically
  - Configures environment variables
  - Uses Render's free tier

### 4. [`backend/settings_prod.py`](backend/backend/settings_prod.py)
- **Purpose**: Production-specific Django settings
- **Key Changes**:
  - `DEBUG = False`
  - `ALLOWED_HOSTS` from environment variable
  - PostgreSQL database configuration
  - Security settings (SSL, secure cookies)
  - Production logging configuration

### 5. [`RENDER_DEPLOYMENT.md`](backend/RENDER_DEPLOYMENT.md)
- **Purpose**: Comprehensive deployment guide
- **Contents**:
  - Step-by-step deployment instructions
  - Environment variables reference
  - Troubleshooting guide
  - Post-deployment tasks (migrations, superuser creation)

## Quick Start

### Option 1: Using render.yaml (Easiest)

1. **Push your code to Git**:
   ```bash
   cd backend
   git add .
   git commit -m "Add Render deployment configuration"
   git push origin main
   ```

2. **Deploy on Render**:
   - Go to [Render Dashboard](https://dashboard.render.com)
   - Click "New +" → "Blueprint"
   - Connect your Git repository
   - Render will auto-detect [`render.yaml`](backend/render.yaml)
   - Click "Apply"

3. **Set Environment Variables**:
   - `SECRET_KEY`: Render can auto-generate this
   - `ALLOWED_HOSTS`: Your Render URL (e.g., `pmc-backend.onrender.com`)

### Option 2: Manual Setup

Follow the detailed instructions in [`RENDER_DEPLOYMENT.md`](backend/RENDER_DEPLOYMENT.md).

## Environment Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key | Auto-generated |
| `DEBUG` | Debug mode | `False` |
| `ALLOWED_HOSTS` | Allowed hostnames | `.onrender.com` |
| `USE_POSTGRESQL` | Use PostgreSQL | `True` |
| `DB_NAME` | Database name | `pmc_db` |
| `DB_USER` | Database user | `postgres` |
| `DB_PASSWORD` | Database password | From Render |
| `DB_HOST` | Database host | From Render |
| `DB_PORT` | Database port | `5432` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CORS_ALLOW_ALL_ORIGINS` | Allow all CORS origins | `False` |
| `CORS_ALLOW_CREDENTIALS` | Allow CORS credentials | `True` |
| `CSRF_COOKIE_SECURE` | Secure CSRF cookie | `True` |

## Post-Deployment Tasks

After your first deployment, run these commands in Render's shell:

1. **Run Migrations**:
   ```bash
   python manage.py migrate
   ```

2. **Create Superuser**:
   ```bash
   python manage.py createsuperuser
   ```

3. **Collect Static Files** (if needed):
   ```bash
   python manage.py collectstatic --noinput
   ```

## Testing Locally

To test the Docker setup locally before deploying:

```bash
cd backend

# Build the Docker image
docker build -t pmc-backend .

# Run the container
docker run -p 8000:8000 \
  -e SECRET_KEY=your-secret-key \
  -e DEBUG=False \
  -e ALLOWED_HOSTS=localhost,127.0.0.1 \
  -e USE_POSTGRESQL=False \
  pmc-backend
```

## Troubleshooting

### Build Fails
- Check [`requirements.txt`](backend/requirements.txt) has all dependencies
- Ensure [`Dockerfile`](backend/Dockerfile) is in `backend/` directory
- Check build logs in Render dashboard

### Database Connection Issues
- Verify database environment variables
- Check database is running in Render
- Ensure `USE_POSTGRESQL=True`

### Static Files Not Loading
- Run `python manage.py collectstatic` in shell
- Check `STATIC_ROOT` in settings
- Verify `STATIC_URL` is set

### Application Crashes
- Check logs in Render dashboard
- Verify all environment variables
- Run `python manage.py check` in shell

## Next Steps

1. **Deploy your backend** using one of the methods above
2. **Run migrations** to set up your database
3. **Create a superuser** for admin access
4. **Update your frontend** to point to your new Render URL
5. **Test all endpoints** to ensure everything works

## Support

- **Render Documentation**: https://render.com/docs
- **Django Deployment**: https://docs.djangoproject.com/en/6.0/howto/deployment/
- **Gunicorn Documentation**: https://docs.gunicorn.org/

## Files Reference

- [`Dockerfile`](backend/Dockerfile) - Docker image configuration
- [`.dockerignore`](backend/.dockerignore) - Docker build exclusions
- [`render.yaml`](backend/render.yaml) - Render infrastructure config
- [`backend/settings_prod.py`](backend/backend/settings_prod.py) - Production settings
- [`RENDER_DEPLOYMENT.md`](backend/RENDER_DEPLOYMENT.md) - Detailed deployment guide
- [`requirements.txt`](backend/requirements.txt) - Python dependencies
- [`.env.example`](backend/.env.example) - Environment variables template
