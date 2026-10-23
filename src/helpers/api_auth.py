from django.contrib.auth.models import User
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.exceptions import AuthenticationFailed
from ninja_jwt.settings import api_settings
from ninja_jwt.tokens import AccessToken, RefreshToken

from auth_app.permissions import has_thales_access

# The blog stores its JWTs in these HttpOnly cookies. The names are defined in
# blog-frontend/src/lib/auth.jsx; keep them in step.
AUTH_TOKEN_COOKIE = "auth-token"
AUTH_REFRESH_COOKIE = "auth-refresh-token"


def is_suspended(user):
    """
    Whether a user's account is suspended.

    Suspension never applies to admins - an admin cannot be suspended by another
    admin, so mutual lockout is not possible.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    profile = getattr(user, 'profile', None)
    if profile is None:
        return False
    if profile.role == 'admin':
        return False
    return bool(profile.is_suspended)


class SuspendAwareJWTAuth(JWTAuth):
    """
    JWTAuth that rejects suspended users on every request.

    Revoking the refresh token alone is not enough: an access token is a
    self-contained signed JWT that stays valid for its full lifetime (60 min by
    default) no matter what happens in the database. Blacklisting stops new
    tokens being issued, but only a per-request check revokes the token the user
    is currently holding.
    """

    def authenticate(self, request, token):
        user = super().authenticate(request, token)
        if is_suspended(user):
            raise AuthenticationFailed(
                "Your account has been suspended. Contact an administrator."
            )
        return user


def _user_from_token(token):
    """Resolve the User behind a validated JWT, or None if they are gone."""
    user_id = token.get(api_settings.USER_ID_CLAIM)
    if user_id is None:
        return None
    return (
        User.objects.select_related("profile")
        .filter(**{api_settings.USER_ID_FIELD: user_id})
        .first()
    )


def user_from_session_cookies(request):
    """Resolve the user from the blog's HttpOnly JWT cookies.

    The access token is preferred. Falling back to the refresh token lets a
    top-level page load survive the 60-minute access-token lifetime without
    bouncing the user through the login page; API calls still require a live
    access token and are refreshed by the Thales client's 401 interceptor.

    Returns None for anonymous, inactive, deleted, or suspended users.
    """
    for cookie_name, token_class in (
        (AUTH_TOKEN_COOKIE, AccessToken),
        (AUTH_REFRESH_COOKIE, RefreshToken),
    ):
        raw = request.COOKIES.get(cookie_name)
        if not raw:
            continue
        try:
            token = token_class(raw)
        except Exception:
            continue

        user = _user_from_token(token)
        if user is None or not user.is_active:
            continue
        if is_suspended(user):
            return None
        return user
    return None


class ThalesAccessJWTAuth(SuspendAwareJWTAuth):
    """JWT authentication for the Thales API.

    Accepts either the normal ``Authorization: Bearer`` header or the
    ``auth-token`` cookie forwarded by the Next.js proxy. Authentication is not
    enough on its own: the user must also hold the Thales permission, so the
    API cannot be used by every logged-in blog account.
    """

    def __call__(self, request):
        auth_value = request.headers.get(self.header)
        if auth_value:
            user = super().__call__(request)
        else:
            raw = request.COOKIES.get(AUTH_TOKEN_COOKIE)
            if not raw:
                return None
            user = self.authenticate(request, raw)

        if user and not has_thales_access(user):
            raise HttpError(403, "Thales access required")
        return user


def allow_annon(request):
    if not request.user.is_authenticated:
        return True
    

api_auth_user_required = [JWTAuth()]
api_auth_user_or_annon = [JWTAuth(), allow_annon]