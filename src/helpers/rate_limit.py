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


def get_client_ip(request):
    """Return the real client IP by parsing X-Forwarded-For.

    Takes the rightmost (client-closest) IP from X-Forwarded-For, respecting
    NUM_TRUSTED_PROXIES. Railway's edge is a single hop, so NUM_TRUSTED_PROXIES=1
    by default; rightmost IP is most trustworthy since it's added by the closest
    trusted proxy (Railway's edge) to the actual client.
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    remote_addr = request.META.get("REMOTE_ADDR", "0.0.0.0")
    if not xff:
        return remote_addr
    addrs = [a.strip() for a in xff.split(",") if a.strip()]
    if not addrs:
        return remote_addr
    num_proxies = getattr(settings, "NUM_TRUSTED_PROXIES", 1)
    return addrs[-min(num_proxies, len(addrs))]


def check_rate_limit(request, key, max_requests, period, identifier=None):
    """
    Fixed-window rate limiter using atomic cache operations.

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
        identifier = get_client_ip(request)

    cache_key = f"rl:{key}:{identifier}"

    # Atomic set-if-absent: opens a new window (first request)
    if cache.add(cache_key, 1, timeout=period):
        return

    # Window exists; atomically increment request count
    try:
        count = cache.incr(cache_key)
    except ValueError:
        # Rare edge case: key expired between add() and incr() (at window boundary).
        # Reopen the window and allow this request through.
        cache.add(cache_key, 1, timeout=period)
        return

    if count > max_requests:
        raise HttpError(
            429,
            f"Rate limit exceeded. Try again in {period} seconds.",
        )
