"""
Fixed-window rate limiter backed by Django's cache framework.

Usage:
    from helpers.rate_limit import check_rate_limit

    # Inside a view/endpoint (raises HttpError 429 when exceeded):
    check_rate_limit(request, key='login', max_requests=5, period=600)

    # For user-keyed limits (comments):
    check_rate_limit(request, key='comment', max_requests=5, period=3600,
                     identifier=str(request.user.id))
"""
import time

from django.conf import settings
from django.core.cache import cache
from ninja.errors import HttpError


def _get_ip(request):
    """Return the real client IP, respecting X-Forwarded-For."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "0.0.0.0")


def check_rate_limit(request, key, max_requests, period, identifier=None):
    """
    Fixed-window rate limiter.

    Args:
        request:      Django HttpRequest (used to derive IP when identifier is None)
        key:          Short label for the endpoint, e.g. 'login', 'register'
        max_requests: Maximum allowed calls in the window
        period:       Window length in seconds
        identifier:   Cache-key suffix; defaults to client IP

    Raises:
        HttpError(429) with a human-readable retry message when the limit is hit.
    """
    if not getattr(settings, "RATE_LIMIT_ENABLED", True):
        return

    if identifier is None:
        identifier = _get_ip(request)

    cache_key = f"rl:{key}:{identifier}"
    now = int(time.time())

    data = cache.get(cache_key)

    if data is None:
        cache.set(cache_key, {"count": 1, "window_start": now}, timeout=period)
        return

    elapsed = now - data["window_start"]

    if elapsed >= period:
        # Window expired — open a fresh one
        cache.set(cache_key, {"count": 1, "window_start": now}, timeout=period)
        return

    if data["count"] >= max_requests:
        retry_after = period - elapsed
        raise HttpError(
            429,
            f"Rate limit exceeded. Try again in {retry_after} seconds.",
        )

    data["count"] += 1
    cache.set(cache_key, data, timeout=period - elapsed)
