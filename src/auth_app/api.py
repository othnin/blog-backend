"""
API endpoints for authentication.
Includes registration, email verification, and password reset.
"""
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from ninja import Router, Schema, File
from ninja.files import UploadedFile
from ninja_jwt.authentication import JWTAuth
from pydantic import ValidationError as PydanticValidationError
from typing import Optional
import helpers
import io
import os
import uuid
from PIL import Image
from django.conf import settings
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
from auth_app.utils import (
    create_email_verification_token,
    create_password_reset_token,
    send_verification_email,
    send_password_reset_email,
)

router = Router()


class AuthResponseSchema(Schema):
    """Response schema for auth endpoints."""
    status: str
    message: str
    user: Optional[UserResponseSchema] = None


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
        send_verification_email(user, token)
        
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
    except Exception as e:
        return {
            'status': 'error',
            'message': f'Registration failed: {str(e)}',
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
    
    except Exception as e:
        return {
            'status': 'error',
            'message': f'Login failed: {str(e)}',
            'user': None
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
    except Exception as e:
        return {
            'status': 'error',
            'message': f'Email verification failed: {str(e)}',
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
    try:
        try:
            user = User.objects.get(email=data.email)
            
            # Create password reset token
            token = create_password_reset_token(user)
            
            # Send password reset email
            send_password_reset_email(user, token)
            
        except User.DoesNotExist:
            # Don't reveal if user exists (security best practice)
            pass
        
        return {
            'status': 'success',
            'message': 'If a user with that email exists, a password reset link has been sent to their email address.',
        }
    
    except Exception as e:
        return {
            'status': 'error',
            'message': f'Password reset request failed: {str(e)}',
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
    except Exception as e:
        return {
            'status': 'error',
            'message': f'Password reset failed: {str(e)}',
        }

@router.get("/me", response=UserResponseSchema, auth=JWTAuth())
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
        avatar_url = request.build_absolute_uri(profile.avatar.url) if profile.avatar else None
    except UserProfile.DoesNotExist:
        role = 'reader'
        avatar_url = None
        profile = None

    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'profile': {
            'role': role,
            'avatar': avatar_url,
            'display_name': profile.display_name if profile else '',
            'bio': profile.bio if profile else '',
            'email_notifications': profile.email_notifications if profile else True,
            'twitter_url': profile.twitter_url if profile else '',
            'github_url': profile.github_url if profile else '',
            'website_url': profile.website_url if profile else '',
            'profile_public': profile.profile_public if profile else True,
        }
    }


@router.get("/settings", response=UserSettingsSchema, auth=JWTAuth())
def get_settings(request):
    """Get the current user's profile settings."""
    user = request.user
    profile = user.profile
    avatar_url = request.build_absolute_uri(profile.avatar.url) if profile.avatar else None
    return {
        'display_name': profile.display_name,
        'bio': profile.bio,
        'email_notifications': profile.email_notifications,
        'twitter_url': profile.twitter_url,
        'github_url': profile.github_url,
        'website_url': profile.website_url,
        'profile_public': profile.profile_public,
        'avatar_url': avatar_url,
    }


@router.patch("/settings", response=UserSettingsSchema, auth=JWTAuth())
def update_settings(request, data: UserSettingsUpdateSchema):
    """Update the current user's profile settings."""
    user = request.user
    profile = user.profile
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    profile.save()
    avatar_url = request.build_absolute_uri(profile.avatar.url) if profile.avatar else None
    return {
        'display_name': profile.display_name,
        'bio': profile.bio,
        'email_notifications': profile.email_notifications,
        'twitter_url': profile.twitter_url,
        'github_url': profile.github_url,
        'website_url': profile.website_url,
        'profile_public': profile.profile_public,
        'avatar_url': avatar_url,
    }


@router.post("/avatar", auth=JWTAuth())
def upload_avatar(request, file: UploadedFile = File(...)):
    """
    Upload and resize a user avatar image.
    Accepts JPEG, PNG, WebP. Resizes to max 400x400 before saving.
    """
    allowed = {'image/jpeg', 'image/png', 'image/webp'}
    if file.content_type not in allowed:
        from ninja.errors import HttpError
        raise HttpError(400, "Only JPEG, PNG, and WebP images are allowed.")
    if file.size > 10 * 1024 * 1024:
        from ninja.errors import HttpError
        raise HttpError(400, "Image must be under 10 MB.")

    img = Image.open(file)
    img = img.convert('RGB')
    img.thumbnail((400, 400), Image.LANCZOS)

    ext = 'jpg'
    filename = f"{uuid.uuid4().hex}.{ext}"
    save_dir = settings.MEDIA_ROOT / 'avatars'
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / filename

    img.save(save_path, format='JPEG', quality=85)

    profile = request.user.profile
    if profile.avatar:
        old_path = settings.MEDIA_ROOT / profile.avatar.name
        if old_path.exists():
            old_path.unlink()
    profile.avatar = f'avatars/{filename}'
    profile.save(update_fields=['avatar'])

    avatar_url = request.build_absolute_uri(profile.avatar.url)
    return {'avatar_url': avatar_url}


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

    avatar_url = request.build_absolute_uri(profile.avatar.url) if profile.avatar else None
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