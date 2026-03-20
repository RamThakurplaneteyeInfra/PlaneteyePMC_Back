from django.utils.deprecation import MiddlewareMixin


class CSRFMiddleware(MiddlewareMixin):
    """
    Custom CSRF middleware that exempts API endpoints from CSRF protection.
    This is needed because we use JWT authentication, not session-based auth.
    """
    
    def process_request(self, request):
        # Exempt API endpoints from CSRF
        if request.path.startswith('/api/'):
            request.csrf_processing_done = True
        return None
