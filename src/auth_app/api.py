"""
API endpoints for authentication.
Includes registration, email verification, and password reset.
"""
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from ninja import Router, Schema
from ninja_jwt.authentication import JWTAuth
from pydantic import ValidationError as PydanticValidationError
from typing import Optional
import helpers
from auth_app.serializers import (
    RegisterSerializer,
    EmailVerificationSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    UserResponseSchema,
    LoginSerializer,
)
from auth_app.models import EmailVerificationToken, PasswordResetToken, UserProfile
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
    - username: Optional, auto-generated from email if not provided
    
    Response:
    - Returns new user data on success
    - Returns error message on validation failure
    """
    try:
        # Check if user with email already exists
        if User.objects.filter(email=data.email).exists():
            return {
                'status': 'error',
                'message': 'User with this email already exists',
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
