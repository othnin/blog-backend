"""Router for the LLM advisor API, nested under /api/thales/advisor/.

Exports the router for src/thales/urls.py to mount, mirroring the molecules
router. That keeps the advisor behind the same /api/thales prefix, auth, and
single add_router() coupling surface as the rest of the lab.
"""

from . import views

# Export the router to be included in the main API
router = views.router
