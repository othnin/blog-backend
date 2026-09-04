"""
Security event logging utilities.
Provides a centralized place to log security-relevant events to the database and Sentry.
"""
import logging
from django.http import HttpRequest
from .models import SecurityEvent
from helpers.rate_limit import get_client_ip

logger = logging.getLogger(__name__)


def log_security_event(event_type, request=None, user=None, message="", details=None, severity="warning"):
    """
    Log a security event to the database and optionally to Sentry.

    Args:
        event_type: One of SecurityEvent.EVENT_TYPE_CHOICES
        request: Django HttpRequest object (used to extract IP address)
        user: Django User object (optional)
        message: Human-readable message describing the event
        details: Dictionary of structured data (e.g., {'status_code': 401})
        severity: One of SecurityEvent.SEVERITY_CHOICES

    This function is designed to never raise exceptions — failures in logging
    should not cascade into the calling code. All exceptions are logged but swallowed.
    """
    try:
        ip_address = None
        if request:
            ip_address = get_client_ip(request)

        # Default to 0.0.0.0 if no IP available (should be rare)
        if not ip_address:
            ip_address = "0.0.0.0"

        SecurityEvent.objects.create(
            event_type=event_type,
            severity=severity,
            ip_address=ip_address,
            user=user,
            message=message,
            details=details or {},
        )

        # Send to Sentry if configured
        try:
            import sentry_sdk
            if sentry_sdk.Hub.current.client:
                sentry_sdk.capture_message(
                    message,
                    level="error" if severity == "critical" else "warning",
                    tags={
                        "event_type": event_type,
                        "ip": ip_address,
                        "severity": severity,
                    },
                )
        except Exception:
            # Sentry not available or error during send — continue silently
            pass

    except Exception as e:
        # Last resort: log to Python logger but don't raise
        logger.error(
            f"Failed to log security event: {event_type}",
            exc_info=True,
            extra={"ip": request.META.get("REMOTE_ADDR", "unknown") if request else "unknown"},
        )
