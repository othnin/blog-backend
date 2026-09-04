"""Views for the home app."""
from django.http import JsonResponse
from django.db import connection
from django.core.cache import cache


def health_check(request):
    """
    Health check endpoint for uptime monitoring.
    Checks database and cache connectivity.
    Returns 200 if all checks pass, 503 otherwise.
    """
    db_ok = False
    cache_ok = False

    # Check database
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_ok = True
    except Exception:
        pass

    # Check cache
    try:
        cache.set("_health_check", "ok", 10)
        cache_ok = cache.get("_health_check") == "ok"
    except Exception:
        pass

    status = "ok" if (db_ok and cache_ok) else "unhealthy"
    status_code = 200 if status == "ok" else 503

    return JsonResponse(
        {
            "status": status,
            "checks": {
                "database": db_ok,
                "cache": cache_ok,
            }
        },
        status=status_code,
    )
