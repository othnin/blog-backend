"""Router for the WatsonCrick app, mounted at /api/watsoncrick/.

The molecules and advisor routers are nested under this one so that the
whole WatsonCrick feature lives behind a single URL prefix and a single
add_router() call in home/api.py. That is the entire coupling surface between
WatsonCrick and the rest of the backend: see docs/WATSONCRICK_INTEGRATION.md.
"""

from . import views
from .advisor.urls import router as advisor_router
from .advising.urls import router as advising_router
from .molecules.urls import router as molecules_router

# Export the router to be included in the main API
router = views.router
router.add_router("/molecules/", molecules_router)
router.add_router("/advisor/", advisor_router)
router.add_router("/advising/", advising_router)
