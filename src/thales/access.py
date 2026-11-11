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

This blog injects its own policy (JWT cookies plus the Thales group check)
via home/settings.py; see docs/THALES_INTEGRATION.md, "Portability seams".
"""

import importlib

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
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


def get_api_auth():
    """Return the auth instance guarding every Thales router."""
    dotted = getattr(settings, "THALES_API_AUTH", "thales.access.JWTAuth")
    return _resolve(dotted)()


def page_gate(request):
    """Return the injected page gate's response for this request (None = allowed)."""
    dotted = getattr(settings, "THALES_PAGE_GATE", "thales.access.default_page_gate")
    return _resolve(dotted)(request)
