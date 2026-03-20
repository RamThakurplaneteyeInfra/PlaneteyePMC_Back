# Swagger Troubleshooting Guide

## Common Issues and Solutions

### Issue: "Failed to load API definition" / "Internal Server Error"

**Solution 1: Check if drf-yasg is installed**
```bash
pip install drf-yasg
```

**Solution 2: Restart the Django server**
```bash
# Stop the server (Ctrl+C) and restart
python manage.py runserver
```

**Solution 3: Clear browser cache**
- Hard refresh: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)
- Or clear browser cache completely

**Solution 4: Check server logs**
Look at the terminal where the server is running for detailed error messages.

**Solution 5: Verify URL configuration**
Make sure `drf_yasg` is in `INSTALLED_APPS` in `settings.py`:
```python
INSTALLED_APPS = [
    ...
    'drf_yasg',
    ...
]
```

**Solution 6: Check for import errors**
Run:
```bash
python manage.py check
```

If there are errors, fix them before accessing Swagger.

### Issue: Swagger page loads but endpoints are not visible

**Solution:**
- Make sure the DPR app is in `INSTALLED_APPS`
- Check that `path('api/', include('dpr.urls'))` is in the main `urls.py`
- Verify the router is properly configured in `dpr/urls.py`

### Issue: "Schema validation failed"

**Solution:**
- Check that all serializers are properly defined
- Ensure models have proper field types
- Verify that ForeignKey relationships are correct

### Issue: CORS errors when accessing Swagger

**Solution:**
Make sure CORS is configured in `settings.py`:
```python
CORS_ALLOW_ALL_ORIGINS = True  # For development
```

## Testing Swagger

1. **Start the server:**
   ```bash
   python manage.py runserver
   ```

2. **Access Swagger UI:**
   ```
   http://localhost:8000/swagger/
   ```

3. **If you see errors:**
   - Check the browser console (F12) for JavaScript errors
   - Check the server terminal for Python errors
   - Try accessing the JSON schema directly: `http://localhost:8000/swagger.json`

## Alternative: Access OpenAPI JSON directly

If Swagger UI doesn't work, you can access the schema directly:

- **JSON:** http://localhost:8000/swagger.json
- **YAML:** http://localhost:8000/swagger.yaml

You can then use tools like:
- Postman (import OpenAPI)
- Insomnia (import OpenAPI)
- Swagger Editor (online)

## Still having issues?

1. Check Django version compatibility:
   ```bash
   python -c "import django; print(django.get_version())"
   ```

2. Check drf-yasg version:
   ```bash
   pip show drf-yasg
   ```

3. Try updating drf-yasg:
   ```bash
   pip install --upgrade drf-yasg
   ```

4. Check for conflicting packages or middleware
