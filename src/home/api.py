import helpers
from ninja import NinjaAPI, Schema, Router
from pydantic import ValidationError as PydanticValidationError
from typing import Optional

from ninja_extra import NinjaExtraAPI
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.tokens import RefreshToken
from auth_app.api import router as auth_router
from blog.api import BlogController
from auth_app.serializers import LoginSerializer
from django.http import JsonResponse
from django.contrib.auth import authenticate
from django.conf import settings

api = NinjaExtraAPI()

# Override validation error response
original_on_exception = api.on_exception

def custom_on_exception(request, exc):
    """Handle validation and other errors with consistent JSON response."""
    if hasattr(exc, 'detail'):
        # Ninja validation error
        if isinstance(exc.detail, list) and len(exc.detail) > 0:
            # Extract validation error messages
            errors = exc.detail
            error_messages = '; '.join([f"{err['loc'][-1]}: {err['msg']}" for err in errors if isinstance(err, dict)])
            return JsonResponse(
                {
                    'status': 'error',
                    'message': f'Validation error: {error_messages}',
                    'user': None
                },
                status=400
            )
    return original_on_exception(request, exc)

api.on_exception = custom_on_exception


# Create custom JWT token router
token_router = Router()

@token_router.post("/pair")
def obtain_token_pair(request, data: LoginSerializer):
    """
    Obtain JWT token pair (access and refresh tokens).
    Requires email verification.
    Accepts either username or email for login.
    """
    try:
        print(f"\n=== LOGIN ATTEMPT ===")
        print(f"Login identifier provided: {data.username}")
        print(f"Password provided: {'*' * len(data.password)}")
        
        # Try to authenticate with username first
        user = authenticate(username=data.username, password=data.password)
        
        # If that fails, try with email
        if user is None:
            print(f"✗ Authentication failed with username: {data.username}")
            print(f"Trying with email...")
            from django.contrib.auth.models import User
            try:
                user_by_email = User.objects.get(email=data.username)
                print(f"✓ Found user by email: {user_by_email.username} (email: {user_by_email.email})")
                # Try authenticating with the actual username
                user = authenticate(username=user_by_email.username, password=data.password)
            except User.DoesNotExist:
                print(f"✗ No user with email: {data.username}")
                print(f"Available users: {[(u.username, u.email) for u in User.objects.all()]}")
        
        if user is None:
            print(f"✗ Authentication failed - invalid credentials")
            return JsonResponse({
                'detail': 'Invalid username/email or password'
            }, status=401)
        
        print(f"✓ User authenticated: {user.username} ({user.email})")
        
        # Check if email is verified
        try:
            profile = user.profile
            print(f"✓ Profile exists. Email verified: {profile.email_verified}")
            
            # Skip email verification check if SKIP_EMAIL_VERIFICATION is enabled (dev mode)
            if getattr(settings, 'SKIP_EMAIL_VERIFICATION', False):
                print(f"ℹ Email verification skipped (dev mode)")
            elif not profile.email_verified:
                print(f"✗ Email not verified for user: {user.username}")
                return JsonResponse({
                    'detail': 'Email not verified. Please check your email to verify your account.'
                }, status=401)
        except Exception as profile_error:
            print(f"⚠ Profile error: {profile_error}")
            # Profile doesn't exist, create it
            from auth_app.models import UserProfile
            profile = UserProfile.objects.create(user=user, email_verified=False)
            print(f"✓ Created new profile for user: {user.username}")
            return JsonResponse({
                'detail': 'Email not verified. Please check your email to verify your account.'
            }, status=401)
        
        print(f"✓ User verified and email confirmed. Creating tokens for: {user.username}")
        refresh = RefreshToken.for_user(user)
        print(f"✓ Tokens created successfully")
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'username': user.username,
        }
    except Exception as e:
        import traceback
        print(f"\n✗ ERROR in obtain_token_pair: {str(e)}")
        traceback.print_exc()
        return JsonResponse({
            'detail': f'Login failed: {str(e)}'
        }, status=500)


api.add_router("/token/", token_router)
api.add_router("/auth/", auth_router)
api.register_controllers(BlogController)

class UserSchema(Schema):
    username: str
    is_authenticated: bool
    # is not requst.user.is_authenticated
    email: str = None
    profile: Optional[dict] = None

@api.get("/hello")
def hello(request):
    # print(request)
    return {"message":"Hello World"}

@api.get("/me", 
    response=UserSchema, 
    auth=helpers.api_auth_user_required)
def me(request):
    user = request.user
    profile_data = None
    try:
        profile = user.profile
        profile_data = {
            'role': profile.role,
            'avatar': profile.avatar,
            'email_verified': profile.email_verified,
        }
    except:
        pass
    
    return {
        'username': user.username,
        'email': user.email,
        'is_authenticated': user.is_authenticated,
        'profile': profile_data,
    }