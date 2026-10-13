"""
URL configuration for home project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from .api import api
from .blog_admin import blog_admin_site
from .views import health_check

urlpatterns = [
    path("django-admin/", blog_admin_site.urls),
    # Register both spellings. Railway's healthcheck and the frontend proxy both
    # request the no-slash form, and Django's APPEND_SLASH would otherwise 301 to
    # the slash form - which the Next.js /api/:path* rewrite strips again,
    # producing an infinite redirect loop. An explicit match means no redirect.
    path("api/health", health_check),
    path("api/health/", health_check),
    path("api/", api.urls)
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
