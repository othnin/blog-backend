"""Router for the LLM advisor API, nested under /api/watsoncrick/advisor/.

Exports the router for src/watsoncrick/urls.py to mount, mirroring the molecules
router. That keeps the advisor behind the same /api/watsoncrick prefix, auth, and
single add_router() coupling surface as the rest of the lab.
"""

from . import views

# Export the router to be included in the main API
router = views.router
