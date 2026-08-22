"""
Custom Django AdminSite for organized admin interface.
Groups models by function rather than by app name.
"""
from django.contrib.admin import AdminSite
from django.contrib.auth.models import User, Group

class BlogAdminSite(AdminSite):
    site_header = "Blog Administration"
    site_title = "Blog Admin"
    index_title = "Administration Dashboard"

    def index(self, request, extra_context=None):
        """Custom index with helpful information."""
        extra_context = extra_context or {}
        extra_context['title'] = 'Site Administration'
        return super().index(request, extra_context)


# Create the custom admin site instance
blog_admin_site = BlogAdminSite(name='blog_admin')

# Register Django's built-in models
blog_admin_site.register(User)
blog_admin_site.register(Group)
