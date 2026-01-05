"""
Utility functions for authentication.
"""
import secrets
from datetime import timedelta
from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from auth_app.models import EmailVerificationToken, PasswordResetToken


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
    """
    verification_url = f"{settings.FRONTEND_URL}/verify-email?token={token.token}"
    
    context = {
        'user': user,
        'verification_url': verification_url,
        'token': token.token,
    }
    
    subject = 'Verify Your Email Address'
    message = render_to_string('auth_app/verify_email.html', context)
    
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=message,
    )


def send_password_reset_email(user, token):
    """
    Send password reset email to user.
    """
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token.token}"
    
    context = {
        'user': user,
        'reset_url': reset_url,
        'token': token.token,
    }
    
    subject = 'Reset Your Password'
    message = render_to_string('auth_app/password_reset.html', context)
    
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=message,
    )
