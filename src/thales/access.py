"""The seam between the Thales lab and its host project.

The lab is written to be movable: ``src/thales/`` must drop into another
Django project without editing its imports. So the app never imports host
code — instead, the host injects its policy through two Django settings,
each holding a dotted import path:

    THALES_API_AUTH
        Class whose instances guard every /api/thales/* router. Instantiated
        once at router import time and passed to ninja's ``Router(auth=...)``.
        The default (:class:`JWTAuth`) accepts any valid django-ninja-jwt
        token for an active user.

    THALES_PAGE_GATE
        Function gating the SPA index page. Called as ``gate(request)``; it
        returns ``None`` when the request may see the lab, or an HttpResponse
        to return instead (login redirect, 403, ...). The default
        (:func:`default_page_gate`) uses Django session auth and the standard
        ``redirect_to_login`` helper.

    THALES_ADVISOR_CHECK
        Function deciding whether a user may advise students. The default
        (:func:`default_has_advisor_access`) accepts active users holding the
        ``thales.advise_students`` permission.

    THALES_ADVISOR_PAGE_GATE
        Function gating the advisor SPA index. It has the same contract as
        ``THALES_PAGE_GATE`` but also requires the advising capability. The
        default (:func:`default_advisor_page_gate`) uses session auth plus
        :func:`has_advisor_access`.

This blog injects its own policy (JWT cookies plus the Thales group check)
via home/settings.py; see docs/THALES_INTEGRATION.md, "Portability seams".
"""

import importlib

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from ninja_jwt.authentication import JWTAuth


def _resolve(dotted):
    """Import one name from a dotted path, e.g. 'helpers.api_auth.ThalesAccessJWTAuth'."""
    module_name, _, attr = dotted.rpartition(".")
    return getattr(importlib.import_module(module_name), attr)


class JWTAuth(JWTAuth):  # noqa: N801 - keeps the exported name intuitive
    """Default /api/thales auth: any valid ninja_jwt token for an active user.

    Deliberately permissive: it is a placeholder so the app imports and runs
    in any Django project with django-ninja-jwt installed. Hosts that need a
    real policy — as this blog does — override it via settings.THALES_API_AUTH.
    """


def default_page_gate(request):
    """Default page gate: Django session auth, else the standard login redirect.

    Returns None when ``request.user`` is an authenticated active user, and a
    redirect to settings.LOGIN_URL (with ``next``) otherwise.
    """
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_active:
        return None
    return redirect_to_login(request.get_full_path())


def default_has_advisor_access(user):
    """Default advising policy: active user with ``thales.advise_students``."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "is_active", True):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return bool(user.has_perm("thales.advise_students"))


def has_advisor_access(user):
    """Return whether ``user`` may use the advisor dashboard/API."""
    dotted = getattr(
        settings,
        "THALES_ADVISOR_CHECK",
        "thales.access.default_has_advisor_access",
    )
    return _resolve(dotted)(user)


def default_advisor_page_gate(request):
    """Default advisor page gate: session auth plus the advising capability."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_active:
        return redirect_to_login(request.get_full_path())
    if not has_advisor_access(user):
        return HttpResponseForbidden("Advisor access required.")
    return None


def get_api_auth():
    """Return the auth instance guarding every Thales router."""
    dotted = getattr(settings, "THALES_API_AUTH", "thales.access.JWTAuth")
    return _resolve(dotted)()


def page_gate(request):
    """Return the injected page gate's response for this request (None = allowed)."""
    dotted = getattr(settings, "THALES_PAGE_GATE", "thales.access.default_page_gate")
    return _resolve(dotted)(request)


def advisor_page_gate(request):
    """Return the injected advisor page gate's response (None = allowed)."""
    dotted = getattr(
        settings,
        "THALES_ADVISOR_PAGE_GATE",
        "thales.access.default_advisor_page_gate",
    )
    return _resolve(dotted)(request)
