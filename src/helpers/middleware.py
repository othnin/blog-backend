"""Global rate-limit middleware for all /api/* endpoints."""
import time
from django.http import JsonResponse
from django.core.cache import cache
from django.conf import settings
from ninja.errors import HttpError
from helpers.rate_limit import check_rate_limit, get_client_ip

# Status code rate thresholds (per-minute, process-wide)
STATUS_RATE_THRESHOLDS = {
    '401': 20,  # 20 unauthorized per minute
    '403': 20,  # 20 forbidden per minute
    '429': 30,  # 30 too many requests per minute
    '5xx': 10,  # 10 server errors per minute
}


class GlobalRateLimitMiddleware:
    """Apply a global rate limit (100 requests/min per IP) to all /api/* paths.

    This middleware catches rate-limit exceptions from check_rate_limit() and
    returns a 429 response in the same shape as Ninja's error handler, so the
    frontend doesn't need to distinguish between endpoint-specific and global limits.

    Also tracks status code rates (401, 403, 429, 5xx) and logs security events
    when thresholds are crossed, helping detect attacks or service issues.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only rate-limit /api/* paths (other paths like /admin go unchecked)
        # Exempt health checks and other non-user paths
        if request.path.startswith("/api/") and request.path != "/api/health/":
            try:
                check_rate_limit(request, key="global", max_requests=100, period=60)
            except HttpError as e:
                # Return 429 in the same {"detail": ...} shape as Ninja's error handler
                return JsonResponse({"detail": e.message}, status=e.status_code)

        response = self.get_response(request)

        # Track status code rates for /api/* paths
        if request.path.startswith("/api/"):
            self._track_status_rate(request, response)

        return response

    def _track_status_rate(self, request, response):
        """Track status codes and log security events on threshold crossing."""
        try:
            status_code = response.status_code
            bucket = None

            if status_code == 401:
                bucket = '401'
            elif status_code == 403:
                bucket = '403'
            elif status_code == 429:
                bucket = '429'
            elif 500 <= status_code < 600:
                bucket = '5xx'

            if not bucket:
                return

            threshold = STATUS_RATE_THRESHOLDS.get(bucket)
            if not threshold:
                return

            minute_epoch = int(time.time()) // 60
            cache_key = f"status_rate:{bucket}:{minute_epoch}"

            try:
                count = cache.incr(cache_key)
                cache.touch(cache_key, 90)
            except (ValueError, KeyError):
                cache.set(cache_key, 1, 90)
                count = 1

            # Log security event only when crossing the threshold
            if count == threshold:
                self._log_status_rate_event(request, bucket, threshold)

        except Exception:
            pass

    def _log_status_rate_event(self, request, bucket, threshold):
        """Log a security event for elevated status code rate."""
        try:
            from blog.security_utils import log_security_event
            ip = get_client_ip(request)
            log_security_event(
                'elevated_error_rate' if bucket == '5xx' else 'permission_denied' if bucket == '403' else 'rate_limited' if bucket == '429' else 'permission_denied',
                request=request,
                message=f"Elevated {bucket} rate detected: {threshold} requests/minute",
                details={'status_code': bucket, 'threshold': threshold},
                severity='critical',
            )
        except Exception:
            pass


class SSLRedirectMiddleware:
    """
    Force HTTPS in production, but exempt certain paths (like /api/health/).
    This allows Railway's healthcheck probe (which uses HTTP) to work while still
    enforcing HTTPS for all other requests.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Exempt paths that should allow plain HTTP
        exempt_paths = ['/api/health/']

        if not settings.DEBUG and request.scheme == 'http':
            # Check if this path is exempt from SSL redirect
            if not any(request.path == path for path in exempt_paths):
                # Redirect to HTTPS
                url = request.build_absolute_uri()
                secure_url = url.replace('http://', 'https://', 1)
                from django.http import HttpResponsePermanentRedirect
                return HttpResponsePermanentRedirect(secure_url)

        return self.get_response(request)
