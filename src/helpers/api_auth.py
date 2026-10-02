from ninja_jwt.authentication import JWTAuth
from ninja_jwt.exceptions import AuthenticationFailed


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


def allow_annon(request):
    if not request.user.is_authenticated:
        return True
    

api_auth_user_required = [JWTAuth()]
api_auth_user_or_annon = [JWTAuth(), allow_annon]