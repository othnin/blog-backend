"""Router for the molecules API, included under /api/molecules/."""

from . import views

# Export the router to be included in the main API
router = views.router
