"""
API endpoints for authentication.
Includes registration, email verification, and password reset.
"""
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from ninja import Router, Schema, File
from ninja.files import UploadedFile
# SuspendAwareJWTAuth rejects suspended users on every request (see helpers/api_auth.py).
from helpers.api_auth import SuspendAwareJWTAuth as JWTAuth
from pydantic import ValidationError as PydanticValidationError
from typing import Optional
import helpers
import io
import logging
import os
import uuid
import re
from PIL import Image
from django.conf import settings
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from django.http import JsonResponse
from ninja_jwt.tokens import RefreshToken
from auth_app.serializers import (
    RegisterSerializer,
    EmailVerificationSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    UserResponseSchema,
    LoginSerializer,
    UserSettingsSchema,
    UserSettingsUpdateSchema,
    ChangePasswordSchema,
)
from auth_app.models import EmailVerificationToken, PasswordResetToken, UserProfile
from helpers.rate_limit import check_rate_limit
from helpers.storage import get_presigned_url_or_none, get_presigned_url, is_safe_storage_key
from auth_app.utils import (
    create_email_verification_token,
    create_password_reset_token,
    send_verification_email,
    send_password_reset_email,
)

router = Router()

logger = logging.getLogger('auth_app')


def _generate_unique_username(email):
    """Generate a unique username from an email address."""
    base = re.sub(r'[^a-z0-9]', '', email.split('@')[0].lower()) or 'user'
    username, counter = base, 1
    while User.objects.filter(username=username).exists():
        username = f"{base}{counter}"
        counter += 1
    return username


def _get_avatar_url(profile):
    """Get a fresh signed URL for a user's avatar, or None if no avatar."""
    if not profile or not profile.avatar:
        return None
    url = get_presigned_url_or_none(profile.avatar.name)
    return str(url) if url else None


class AuthResponseSchema(Schema):
    """Response schema for auth endpoints."""
    status: str
    message: str
    user: Optional[UserResponseSchema] = None


class GoogleLoginSchema(Schema):
    """Request schema for Google OAuth login."""
    credential: str


class TokenResponseSchema(Schema):
    """Response schema for token endpoints."""
    status: str
    message: str


@router.post("/register", response=AuthResponseSchema)
def register(request, data: RegisterSerializer):
    """
    Register a new user account.
    
    Required fields:
    - email: Valid email address (must be unique)
    - password: At least 8 chars, with uppercase, lowercase, and digit
    - password_confirm: Must match password
    - username: Required, unique username
    
    Response:
    - Returns new user data on success
    - Returns error message on validation failure
    """
    # Rate limit: 3 registration attempts per day per IP
    check_rate_limit(request, key="register", max_requests=3, period=86400)

    try:
        # Check if user with email already exists
        if User.objects.filter(email=data.email).exists():
            return {
                'status': 'error',
                'message': 'User with this email already exists',
                'user': None
            }
        
        # Check if username already exists
        if User.objects.filter(username=data.username).exists():
            return {
                'status': 'error',
                'message': 'Username already exists',
                'user': None
            }
        
        # Create user
        user = User.objects.create_user(
            username=data.username,
            email=data.email,
            password=data.password,
        )
        
        # Create email verification token and send email
        token = create_email_verification_token(user)
        send_verification_email(user, token, request=request)
        
        user_data = UserResponseSchema(
            id=user.id,
            username=user.username,
            email=user.email,
            email_verified=False,
        )
        
        return {
            'status': 'success',
            'message': 'User registered successfully. Please check your email to verify your account.',
            'user': user_data,
        }
    
    except PydanticValidationError as e:
        error_messages = '; '.join([f"{error['loc'][0]}: {error['msg']}" for error in e.errors()])
        return {
            'status': 'error',
            'message': f'Validation error: {error_messages}',
            'user': None
        }
    except IntegrityError:
        # Lost a race against a concurrent registration. Say only that the name
        # is taken; the DB error would name the table and constraint.
        logger.info('Registration hit an integrity error (duplicate username/email)')
        return {
            'status': 'error',
            'message': 'Username or email already exists',
            'user': None
        }
    except OperationalError:
        # The database is unreachable. That is our outage, not the user's
        # mistake, and the driver message would leak the hostname and vendor.
        logger.exception('Registration failed: database unavailable')
        return {
            'status': 'error',
            'message': 'Registration is temporarily unavailable. Please try again.',
            'user': None
        }
    except Exception:
        # Full traceback to the log, nothing internal to the client.
        logger.exception('Registration failed for %s', data.username)
        return {
            'status': 'error',
            'message': 'Registration failed. Please try again later.',
            'user': None
        }


@router.post("/login", response=AuthResponseSchema)
def login(request, data: LoginSerializer):
    """
    User login endpoint that checks email verification status.
    Returns user data if successful.
    
    Required fields:
    - username: User's username
    - password: User's password
    
    Response:
    - Returns user data on successful login (only if email is verified)
    - Returns error message if credentials are invalid or email not verified
    
    Note: This endpoint validates email verification status.
    Use /api/token/pair for JWT token generation.
    """
    # Shares the "login" key with /api/token/pair so an attacker cannot double
    # their attempt budget by splitting across both endpoints.
    check_rate_limit(request, key="login", max_requests=5, period=600)

    try:
        from django.contrib.auth import authenticate
        
        # Authenticate user
        user = authenticate(username=data.username, password=data.password)
        
        if user is None:
            return {
                'status': 'error',
                'message': 'Invalid credentials',
                'user': None
            }

        # A suspended user must not be able to log in. Admin accounts are exempt
        # (see helpers.api_auth.is_suspended).
        if helpers.api_auth.is_suspended(user):
            logger.warning(f'Login blocked - suspended user: {user.username}')
            return {
                'status': 'error',
                'message': 'Your account has been suspended. Contact an administrator.',
                'user': None
            }
        
        # Check if email is verified
        if not user.profile.email_verified:
            return {
                'status': 'error',
                'message': 'Email not verified. Please check your email to verify your account.',
                'user': None
            }
        
        user_data = UserResponseSchema(
            id=user.id,
            username=user.username,
            email=user.email,
            email_verified=True,
        )
        
        return {
            'status': 'success',
            'message': 'Login successful',
            'user': user_data,
        }

    except OperationalError:
        logger.exception('Login failed: database unavailable')
        return {
            'status': 'error',
            'message': 'Login is temporarily unavailable. Please try again.',
            'user': None
        }
    except Exception:
        logger.exception('Login failed for %s', data.username)
        return {
            'status': 'error',
            'message': 'Login failed. Please try again later.',
            'user': None
        }

@router.post("/google-login", auth=None)
def google_login(request, payload: GoogleLoginSchema):
    """
    Authenticate using Google OAuth. Accepts a Google ID token.
    Creates a new user if the email doesn't exist, or links to existing account.
    Returns JWT tokens for successful authentication.

    Required fields:
    - credential: Google ID token from Google Identity Services

    Response:
    - Returns status and JWT tokens on success
    - Returns error message on invalid token or verification failure
    """
    check_rate_limit(request, key="google_login", max_requests=10, period=600)

    try:
        idinfo = id_token.verify_oauth2_token(
            payload.credential,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
    except ValueError:
        return {"status": "error", "message": "Invalid Google credential"}

    if not idinfo.get('email_verified'):
        return {"status": "error", "message": "Google email not verified"}

    email = idinfo['email']

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        user = User.objects.create_user(
            username=_generate_unique_username(email),
            email=email,
        )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    if not profile.email_verified:
        profile.email_verified = True
        profile.save(update_fields=['email_verified'])

    # Google login is a separate token-issuing path from /api/auth/login and
    # must honour suspension too, otherwise a suspended user could keep
    # re-authenticating via Google.
    if helpers.api_auth.is_suspended(user):
        logger.warning(f'Google login blocked - suspended user: {user.username}')
        return {
            "status": "error",
            "message": "Your account has been suspended. Contact an administrator.",
        }

    refresh = RefreshToken.for_user(user)
    return {
        "status": "success",
        "refresh": str(refresh),
        "access": str(refresh.access_token),
        "username": user.username,
    }

@router.post("/verify-email", response=AuthResponseSchema)
def verify_email(request, data: EmailVerificationSerializer):
    """
    Verify user email address using token from verification link.
    
    Required fields:
    - token: Email verification token sent to user's email
    
    Response:
    - Returns user data on successful verification
    - Returns error message if token is invalid or expired
    """
    # Tokens are high-entropy, so this bounds automated guessing rather than
    # making it infeasible.
    check_rate_limit(request, key="verify_email", max_requests=10, period=600)
    try:
        token_obj = EmailVerificationToken.objects.get(token=data.token)
        
        if not token_obj.is_valid():
            return {
                'status': 'error',
                'message': 'Verification token is invalid or expired',
                'user': None
            }
        
        # Mark token as used
        token_obj.is_used = True
        token_obj.save()
        
        # Mark user email as verified
        user = token_obj.user
        profile = user.profile
        profile.email_verified = True
        profile.save()
        
        user_data = UserResponseSchema(
            id=user.id,
            username=user.username,
            email=user.email,
            email_verified=True,
        )
        
        return {
            'status': 'success',
            'message': 'Email verified successfully',
            'user': user_data,
        }
    
    except EmailVerificationToken.DoesNotExist:
        return {
            'status': 'error',
            'message': 'Verification token not found',
            'user': None
        }
    except Exception:
        logger.exception('Email verification failed')
        return {
            'status': 'error',
            'message': 'Email verification failed. Please request a new link.',
            'user': None
        }


@router.post("/password-reset-request", response=TokenResponseSchema)
def password_reset_request(request, data: PasswordResetRequestSerializer):
    """
    Request a password reset. Sends reset link to user's email.
    
    Required fields:
    - email: Email address associated with account
    
    Response:
    - Always returns success message for security (prevents email enumeration)
    """
    # Without this, an attacker can trigger unlimited reset emails to a known
    # address (email bombing / reputation abuse of the sending domain).
    check_rate_limit(request, key="password_reset_request", max_requests=5, period=3600)
    try:
        try:
            user = User.objects.get(email=data.email)
            
            # Create password reset token
            token = create_password_reset_token(user)

            # Send password reset email
            send_password_reset_email(user, token, request=request)
            
        except User.DoesNotExist:
            # Don't reveal if user exists (security best practice)
            pass
        
        return {
            'status': 'success',
            'message': 'If a user with that email exists, a password reset link has been sent to their email address.',
        }
    
    except Exception:
        logger.exception('Password reset request failed')
        return {
            'status': 'error',
            'message': 'Password reset request failed. Please try again later.',
        }


@router.post("/password-reset-confirm", response=TokenResponseSchema)
def password_reset_confirm(request, data: PasswordResetConfirmSerializer):
    """
    Confirm password reset using token and set new password.
    
    Required fields:
    - token: Password reset token sent to user's email
    - new_password: New password (at least 8 chars, with uppercase, lowercase, digit)
    - new_password_confirm: Must match new_password
    
    Response:
    - Returns success message on successful reset
    - Returns error message if token is invalid or expired
    """
    # Tightest limit of the auth endpoints: a successful guess here resets a
    # password, so keep automated attempts low.
    check_rate_limit(request, key="password_reset_confirm", max_requests=5, period=600)
    try:
        token_obj = PasswordResetToken.objects.get(token=data.token)
        
        if not token_obj.is_valid():
            return {
                'status': 'error',
                'message': 'Password reset token is invalid or expired',
            }
        
        # Mark token as used
        token_obj.is_used = True
        token_obj.save()
        
        # Update user password
        user = token_obj.user
        user.set_password(data.new_password)
        user.save()
        
        return {
            'status': 'success',
            'message': 'Password has been reset successfully. You can now login with your new password.',
        }
    
    except PasswordResetToken.DoesNotExist:
        return {
            'status': 'error',
            'message': 'Password reset token not found',
        }
    except PydanticValidationError as e:
        error_messages = '; '.join([f"{error['loc'][0]}: {error['msg']}" for error in e.errors()])
        return {
            'status': 'error',
            'message': f'Validation error: {error_messages}',
        }
    except Exception:
        logger.exception('Password reset failed')
        return {
            'status': 'error',
            'message': 'Password reset failed. Please try again later.',
        }

class ResendVerificationSchema(Schema):
    email: str


@router.post("/resend-verification", response=TokenResponseSchema)
def resend_verification_email(request, data: ResendVerificationSchema):
    """
    Resend email verification link. Rate limited to 3 requests per hour per IP.
    Always returns a generic success message to prevent email enumeration.
    """
    check_rate_limit(request, key="resend_verification", max_requests=3, period=3600)

    try:
        user = User.objects.select_related('profile').get(email=data.email)
        if not user.profile.email_verified:
            # Invalidate any existing unused tokens
            EmailVerificationToken.objects.filter(user=user, is_used=False).update(is_used=True)
            token = create_email_verification_token(user)
            send_verification_email(user, token, request=request)
    except User.DoesNotExist:
        pass  # Don't reveal whether the email exists
    except Exception:
        pass  # Silently fail; generic message returned below

    return {
        'status': 'success',
        'message': 'If that email belongs to an unverified account, a new verification link has been sent.',
    }


@router.get("/me", auth=JWTAuth())
def get_current_user(request):
    """
    Get the current authenticated user's information.

    Requires JWT authentication.

    Response:
    - Returns current user data on success
    """
    user = request.user

    try:
        profile = user.profile
        role = profile.role
        avatar_url = _get_avatar_url(profile)
    except UserProfile.DoesNotExist:
        role = 'reader'
        avatar_url = None
        profile = None

    return {
        'id': int(user.id),
        'username': str(user.username),
        'email': str(user.email),
        'first_name': str(user.first_name) if user.first_name else None,
        'last_name': str(user.last_name) if user.last_name else None,
        'profile': {
            'role': str(role) if role else None,
            'avatar': str(avatar_url) if avatar_url else None,
            'display_name': str(profile.display_name) if profile and profile.display_name else '',
            'bio': str(profile.bio) if profile and profile.bio else '',
            'email_notifications': bool(profile.email_notifications) if profile else True,
            'twitter_url': str(profile.twitter_url) if profile and profile.twitter_url else '',
            'github_url': str(profile.github_url) if profile and profile.github_url else '',
            'website_url': str(profile.website_url) if profile and profile.website_url else '',
            'profile_public': bool(profile.profile_public) if profile else True,
        }
    }


@router.get("/settings", auth=JWTAuth())
def get_settings(request):
    """Get the current user's profile settings."""
    user = request.user
    profile = user.profile
    avatar_url = _get_avatar_url(profile)
    return {
        'display_name': str(profile.display_name) if profile.display_name else '',
        'bio': str(profile.bio) if profile.bio else '',
        'email_notifications': bool(profile.email_notifications),
        'twitter_url': str(profile.twitter_url) if profile.twitter_url else '',
        'github_url': str(profile.github_url) if profile.github_url else '',
        'website_url': str(profile.website_url) if profile.website_url else '',
        'profile_public': bool(profile.profile_public),
        'avatar_url': str(avatar_url) if avatar_url else None,
    }


@router.patch("/settings", auth=JWTAuth())
def update_settings(request, data: UserSettingsUpdateSchema):
    """Update the current user's profile settings."""
    user = request.user
    profile = user.profile
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    profile.save()
    avatar_url = _get_avatar_url(profile)
    return {
        'display_name': str(profile.display_name) if profile.display_name else '',
        'bio': str(profile.bio) if profile.bio else '',
        'email_notifications': bool(profile.email_notifications),
        'twitter_url': str(profile.twitter_url) if profile.twitter_url else '',
        'github_url': str(profile.github_url) if profile.github_url else '',
        'website_url': str(profile.website_url) if profile.website_url else '',
        'profile_public': bool(profile.profile_public),
        'avatar_url': str(avatar_url) if avatar_url else None,
    }


@router.post("/avatar", auth=JWTAuth())
def upload_avatar(request, file: UploadedFile = File(...)):
    """
    Upload and resize a user avatar image.
    Accepts JPEG, PNG, WebP. Resizes to max 400x400 before saving.
    Works with both local filesystem and S3-compatible storage (Tigris).
    """
    from django.core.files.storage import default_storage
    from ninja.errors import HttpError

    allowed = {'image/jpeg', 'image/png', 'image/webp'}
    if file.content_type not in allowed:
        raise HttpError(400, "Only JPEG, PNG, and WebP images are allowed.")
    if file.size > 10 * 1024 * 1024:
        raise HttpError(400, "Image must be under 10 MB.")

    img = Image.open(file)
    img = img.convert('RGB')
    img.thumbnail((400, 400), Image.LANCZOS)

    ext = 'jpg'
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = f'avatars/{filename}'

    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG', quality=85)
    img_bytes.seek(0)

    try:
        default_storage.save(filepath, img_bytes)
    except Exception as e:
        from blog.security_utils import log_security_event
        log_security_event(
            'storage_failed',
            request=request,
            user=request.user,
            message=f"Failed to upload avatar: {str(e)}",
            details={'filename': filename},
            severity='warning',
        )
        raise HttpError(500, "Failed to upload avatar. Please try again.")

    profile = request.user.profile
    if profile.avatar:
        old_filepath = profile.avatar.name
        if default_storage.exists(old_filepath):
            default_storage.delete(old_filepath)

    profile.avatar = filepath
    profile.save(update_fields=['avatar'])

    return {'filename': filepath}


@router.get("/avatar-url")
def get_avatar_url(request, filename: str):
    """
    Generate a fresh signed URL for an avatar image.
    For private S3 buckets, returns a presigned URL with 24-hour expiration.
    For local filesystem storage, returns the standard media URL.
    """
    from ninja.errors import HttpError

    if not is_safe_storage_key(filename, 'avatars'):
        raise HttpError(400, "Invalid avatar filename")

    try:
        url = get_presigned_url(filename)
        return {"url": url}
    except Exception:
        # boto3 errors carry the bucket name and endpoint host; keep them in the log.
        logger.exception('Failed to presign avatar URL for %s', filename)
        raise HttpError(500, "Failed to generate avatar URL")


@router.post("/change-password", auth=JWTAuth())
def change_password(request, data: ChangePasswordSchema):
    """Change the authenticated user's password after verifying the current one."""
    from django.contrib.auth import authenticate
    user = request.user
    if not authenticate(username=user.username, password=data.current_password):
        return {'status': 'error', 'message': 'Current password is incorrect'}
    user.set_password(data.new_password)
    user.save()
    return {'status': 'success', 'message': 'Password changed successfully'}


@router.delete("/delete-account", auth=JWTAuth())
@transaction.atomic
def delete_account(request):
    """
    Delete the authenticated user's account and anonymize their content.
    - Deletes user profile and account
    - Sets all blog posts, recipes, and comments to anonymous (author=null)
    - Deletes avatar file
    """
    from blog.models import BlogPost, Comment
    from recipes.models import Recipe
    from django.core.files.storage import default_storage

    user = request.user

    try:
        # Get user profile to access avatar
        profile = UserProfile.objects.get(user=user)

        # Delete avatar file if it exists
        if profile.avatar:
            avatar_path = profile.avatar.name
            if default_storage.exists(avatar_path):
                default_storage.delete(avatar_path)

        # Anonymize content. author is nullable with SET_NULL, so content
        # survives the account deletion and is simply attributed to nobody.
        BlogPost.objects.filter(author=user).update(author=None)
        Comment.objects.filter(author=user).update(author=None)
        Recipe.objects.filter(author=user).update(author=None)

        # Delete all email/password reset tokens for this user
        EmailVerificationToken.objects.filter(user=user).delete()
        PasswordResetToken.objects.filter(user=user).delete()

        # Delete the user profile
        profile.delete()

        # Delete the user account
        user.delete()

        return {
            'status': 'success',
            'message': 'Your account has been deleted. Your content will remain published but with no author.'
        }

    except Exception:
        logger.exception('Account deletion failed for user_id=%s', user.id)
        return JsonResponse(
            {
                'status': 'error',
                'message': 'An error occurred while deleting your account. Please try again.',
            },
            status=500,
        )


@router.get("/profile/{username}")
def get_public_profile(request, username: str):
    """
    Return a user's public profile.
    Returns 404 if the user does not exist or has set their profile to private.
    """
    from ninja.errors import HttpError
    try:
        user = User.objects.select_related('profile').get(username=username)
    except User.DoesNotExist:
        raise HttpError(404, "Profile not found")

    profile = getattr(user, 'profile', None)
    if not profile or not profile.profile_public:
        raise HttpError(404, "Profile not found")

    avatar_url = _get_avatar_url(profile)
    return {
        'username': user.username,
        'display_name': profile.display_name,
        'bio': profile.bio,
        'avatar_url': avatar_url,
        'twitter_url': profile.twitter_url,
        'github_url': profile.github_url,
        'website_url': profile.website_url,
        'role': profile.role,
    }