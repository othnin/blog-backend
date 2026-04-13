import helpers
from helpers.rate_limit import check_rate_limit
from ninja import NinjaAPI, Schema, Router
from pydantic import ValidationError as PydanticValidationError
from typing import Optional

from ninja_extra import NinjaExtraAPI
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.tokens import RefreshToken
from ninja_jwt.settings import api_settings as jwt_settings
from auth_app.api import router as auth_router
from blog.api import BlogController, CommentController
from blog.admin_api import AdminController
from recipes.api import RecipeController, RecipeDetailController
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


class RefreshTokenIn(Schema):
    refresh: str


@token_router.post("/pair")
def obtain_token_pair(request, data: LoginSerializer):
    """
    Obtain JWT token pair (access and refresh tokens).
    Requires email verification.
    Accepts either username or email for login.
    """
    # Rate limit: 5 login attempts per 10 minutes per IP
    check_rate_limit(request, key="login", max_requests=5, period=600)

    # Try to authenticate with username first
    user = authenticate(username=data.username, password=data.password)

    # If that fails, try with email
    if user is None:
        from django.contrib.auth.models import User
        try:
            user_by_email = User.objects.get(email=data.username)
            user = authenticate(username=user_by_email.username, password=data.password)
        except User.DoesNotExist:
            pass

    if user is None:
        return JsonResponse({'detail': 'Invalid username/email or password'}, status=401)

    # Check if email is verified
    try:
        profile = user.profile
        if not getattr(settings, 'SKIP_EMAIL_VERIFICATION', False) and not profile.email_verified:
            return JsonResponse(
                {'detail': 'Email not verified. Please check your email to verify your account.'},
                status=401
            )
    except Exception:
        from auth_app.models import UserProfile
        UserProfile.objects.create(user=user, email_verified=False)
        return JsonResponse(
            {'detail': 'Email not verified. Please check your email to verify your account.'},
            status=401
        )

    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
        'username': user.username,
    }


@token_router.post("/refresh")
def refresh_token_view(request, data: RefreshTokenIn):
    """
    Refresh an access token using a valid refresh token.
    Returns a new access token. When ROTATE_REFRESH_TOKENS is enabled,
    also returns a new refresh token and blacklists the old one.
    """
    try:
        token = RefreshToken(data.refresh)
        access = str(token.access_token)
        response_data = {'access': access}

        if jwt_settings.ROTATE_REFRESH_TOKENS:
            if jwt_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    token.blacklist()
                except AttributeError:
                    pass

            token.set_jti()
            token.set_exp()
            token.set_iat()
            response_data['refresh'] = str(token)

        return JsonResponse(response_data, status=200)
    except Exception:
        return JsonResponse({'detail': 'Token is invalid or expired'}, status=401)


@token_router.post("/blacklist")
def blacklist_token_view(request, data: RefreshTokenIn):
    """
    Blacklist a refresh token, immediately invalidating it.
    Called on logout to prevent reuse of the refresh token.
    """
    try:
        token = RefreshToken(data.refresh)
        token.blacklist()
        return JsonResponse({}, status=200)
    except Exception:
        return JsonResponse({'detail': 'Token is invalid or expired'}, status=400)


api.add_router("/token/", token_router)
api.add_router("/auth/", auth_router)
api.register_controllers(BlogController)
api.register_controllers(CommentController)
api.register_controllers(AdminController)
api.register_controllers(RecipeController)   # static-prefix paths first
api.register_controllers(RecipeDetailController)  # single-segment dynamic paths second


class UserSchema(Schema):
    username: str
    is_authenticated: bool
    email: str = None
    profile: Optional[dict] = None


@api.get("/hello")
def hello(request):
    return {"message": "Hello World"}


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
    except Exception:
        pass

    return {
        'username': user.username,
        'email': user.email,
        'is_authenticated': user.is_authenticated,
        'profile': profile_data,
    }
