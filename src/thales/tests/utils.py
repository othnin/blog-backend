"""Shared helpers for Thales access-control tests."""

from django.contrib.auth.models import Group, User
from ninja_jwt.tokens import RefreshToken

# Same literals as thales/signals.py and auth_app/permissions.py; inlined so
# even the lab's test suite imports nothing from the blog apps.
THALES_GROUP = "Thales"
THALES_PERMISSION_CODENAME = "access_thales"

THALES_ADVISOR_GROUP = "Thales Advisors"
THALES_ADVISOR_PERMISSION_CODENAME = "advise_students"

TEST_PASSWORD = "ValidPass123"


def make_thales_user(
    username="thales-user",
    *,
    role="reader",
    thales=True,
    advisor=False,
    superuser=False,
    suspended=False,
):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password=TEST_PASSWORD,
        is_staff=superuser,
        is_superuser=superuser,
    )
    profile = user.profile
    profile.role = "admin" if superuser else role
    profile.email_verified = True
    profile.is_suspended = suspended
    profile.save()

    if thales:
        group, _ = Group.objects.get_or_create(name=THALES_GROUP)
        user.groups.add(group)
    if advisor:
        group, _ = Group.objects.get_or_create(name=THALES_ADVISOR_GROUP)
        user.groups.add(group)
    return user


def access_token_for(user):
    return str(RefreshToken.for_user(user).access_token)


def refresh_token_for(user):
    return str(RefreshToken.for_user(user))


def authenticate(client, user):
    """Attach the blog's HttpOnly access-token cookie to a test client."""
    client.cookies["auth-token"] = access_token_for(user)


def thales_group_has_permission():
    group = Group.objects.get(name=THALES_GROUP)
    return group.permissions.filter(codename=THALES_PERMISSION_CODENAME).exists()


def advisor_group_has_permission():
    group = Group.objects.get(name=THALES_ADVISOR_GROUP)
    return group.permissions.filter(
        codename=THALES_ADVISOR_PERMISSION_CODENAME
    ).exists()
