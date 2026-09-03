"""Global rate-limit middleware for all /api/* endpoints."""
from django.http import JsonResponse
from ninja.errors import HttpError
from helpers.rate_limit import check_rate_limit


class GlobalRateLimitMiddleware:
    """Apply a global rate limit (100 requests/min per IP) to all /api/* paths.

    This middleware catches rate-limit exceptions from check_rate_limit() and
    returns a 429 response in the same shape as Ninja's error handler, so the
    frontend doesn't need to distinguish between endpoint-specific and global limits.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only rate-limit /api/* paths (other paths like /admin go unchecked)
        if request.path.startswith("/api/"):
            try:
                check_rate_limit(request, key="global", max_requests=100, period=60)
            except HttpError as e:
                # Return 429 in the same {"detail": ...} shape as Ninja's error handler
                return JsonResponse({"detail": e.message}, status=e.status_code)

        return self.get_response(request)
