"""
Utility functions for authentication.
"""
import secrets
import logging
from datetime import timedelta
from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from auth_app.models import EmailVerificationToken, PasswordResetToken

try:
    import resend
except ImportError:
    resend = None

logger = logging.getLogger(__name__)


def generate_token():
    """Generate a secure random token."""
    return secrets.token_urlsafe(32)


def create_email_verification_token(user):
    """
    Create and return an email verification token for a user.
    Tokens expire after 24 hours.
    """
    token_string = generate_token()
    expires_at = timezone.now() + timedelta(hours=24)
    
    token = EmailVerificationToken.objects.create(
        user=user,
        token=token_string,
        expires_at=expires_at
    )
    
    return token


def create_password_reset_token(user):
    """
    Create and return a password reset token for a user.
    Tokens expire after 24 hours and are single-use.
    """
    token_string = generate_token()
    expires_at = timezone.now() + timedelta(hours=24)
    
    token = PasswordResetToken.objects.create(
        user=user,
        token=token_string,
        expires_at=expires_at
    )
    
    return token


def send_verification_email(user, token):
    """
    Send email verification email to user.
    Uses Resend API if RESEND_API_KEY is set, otherwise falls back to Django's send_mail.
    """
    verification_url = f"{settings.FRONTEND_URL}/verify-email?token={token.token}"

    context = {
        'user': user,
        'verification_url': verification_url,
        'token': token.token,
    }

    subject = 'Verify Your Email Address'
    message = render_to_string('auth_app/verify_email.html', context)

    if settings.RESEND_API_KEY and resend:
        try:
            resend.api_key = settings.RESEND_API_KEY
            resend.Emails.send({
                "from": settings.DEFAULT_FROM_EMAIL,
                "to": user.email,
                "subject": subject,
                "html": message,
            })
        except Exception as e:
            logger.error(f"Failed to send verification email via Resend for user {user.id}: {str(e)}")
    else:
        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                html_message=message,
            )
        except Exception as e:
            logger.error(f"Failed to send verification email via SMTP for user {user.id}: {str(e)}")


def send_password_reset_email(user, token):
    """
    Send password reset email to user.
    Uses Resend API if RESEND_API_KEY is set, otherwise falls back to Django's send_mail.
    """
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token.token}"

    context = {
        'user': user,
        'reset_url': reset_url,
        'token': token.token,
    }

    subject = 'Reset Your Password'
    message = render_to_string('auth_app/password_reset.html', context)

    if settings.RESEND_API_KEY and resend:
        try:
            resend.api_key = settings.RESEND_API_KEY
            resend.Emails.send({
                "from": settings.DEFAULT_FROM_EMAIL,
                "to": user.email,
                "subject": subject,
                "html": message,
            })
        except Exception as e:
            logger.error(f"Failed to send password reset email via Resend for user {user.id}: {str(e)}")
    else:
        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                html_message=message,
            )
        except Exception as e:
            logger.error(f"Failed to send password reset email via SMTP for user {user.id}: {str(e)}")
