"""Serves the built Thales single-page app.

The Thales frontend is a Vite app that builds into this app's static/
directory (see thales-frontend/vite.config.ts, build.outDir). Django serves
the built bundle at /thales/ so the lab is reachable from the same origin as
the API - no CORS, no second deploy, no build-time coupling to the Next.js
site.

Two routes are registered in home/urls.py:

    /thales/                    -> thales_index   (the built index.html)
    /thales/assets/<path>       -> thales_asset   (hashed JS/CSS bundles)

The asset route is explicit rather than relying on Django's staticfiles
handling, because the Vite build emits absolute /thales/assets/... URLs (see
the `base` option in vite.config.ts). Keeping both routes under one prefix
means the whole lab is one URL namespace, and removing it is a matter of
deleting this app plus two lines in home/urls.py.
"""

import mimetypes
from pathlib import Path

from django.http import FileResponse, HttpResponse

# The built bundle lives inside the app, so it ships with the image and is
# never collected into STATIC_ROOT.
STATIC_DIR = Path(__file__).resolve().parent / "static"
ASSETS_DIR = STATIC_DIR / "assets"
INDEX_FILE = STATIC_DIR / "index.html"

NOT_BUILT_MESSAGE = (
    "The Thales frontend has not been built yet.\n"
    "\n"
    "Run:\n"
    "    cd thales-frontend && npm install && npm run build\n"
    "\n"
    "or use the helper script:\n"
    "    thales-frontend/scripts/build.sh\n"
)


def thales_index(request):
    """Serve the built SPA entrypoint."""
    if not INDEX_FILE.exists():
        return HttpResponse(NOT_BUILT_MESSAGE, status=503, content_type="text/plain")

    return FileResponse(INDEX_FILE.open("rb"), content_type="text/html")


def thales_asset(request, filename):
    """Serve a hashed asset from the built bundle.

    `filename` is resolved against ASSETS_DIR and then checked to still be
    inside it, so a request for "../../home/settings.py" cannot walk out of
    the directory and read arbitrary files off disk.
    """
    candidate = (ASSETS_DIR / filename).resolve()

    try:
        candidate.relative_to(ASSETS_DIR.resolve())
    except ValueError:
        return HttpResponse("Not found", status=404, content_type="text/plain")

    if not candidate.is_file():
        return HttpResponse("Not found", status=404, content_type="text/plain")

    content_type, _ = mimetypes.guess_type(candidate.name)
    return FileResponse(
        candidate.open("rb"),
        content_type=content_type or "application/octet-stream",
    )
