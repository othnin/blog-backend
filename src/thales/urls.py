"""Router for the Thales app, mounted at /api/thales/.

The molecules router is nested under this one so that the whole Thales
feature lives behind a single URL prefix and a single add_router() call in
home/api.py. That is the entire coupling surface between Thales and the
rest of the backend: see docs/THALES_INTEGRATION.md.
"""

from . import views
from .molecules.urls import router as molecules_router

# Export the router to be included in the main API
router = views.router
router.add_router("/molecules/", molecules_router)
