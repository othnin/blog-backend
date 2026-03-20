"""
Custom permission classes for blog API endpoints.
"""
from ninja_extra.permissions import BasePermission


class IsEditorOrAdmin(BasePermission):
    """
    Allow access only to users with 'editor' or 'admin' role.
    Use on any endpoint that requires write access to blog content.
    """
    message = "Only editors and admins can perform this action."

    def has_permission(self, request, controller) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if not hasattr(request.user, 'profile'):
            return False
        return request.user.profile.role in ('editor', 'admin')
