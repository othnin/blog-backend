"""Capability checks that sit alongside the blog role.

``UserProfile.role`` answers "what may this person do on the blog?" and is
deliberately single-valued. Thales access is a separate axis: a blog reader or
editor may also be a lab member, and an admin may use the lab without being
added to its group. Keeping the two independent avoids a role for every
combination (thales-reader, thales-editor, ...).
"""

THALES_ACCESS_PERMISSION = "thales.access_thales"

THALES_GROUP = "Thales"
THALES_PERMISSION_CODENAME = "access_thales"
THALES_PERMISSION_NAME = "Can access the Thales lab"


def is_admin(user):
    """Whether ``user`` has application-level admin rights."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == "admin")


def has_thales_access(user):
    """Whether ``user`` may use the Thales lab.

    Access is granted by the ``Thales`` group's permission. Admins bypass the
    group so a lab membership cannot lock an administrator out of the app.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if is_admin(user):
        return True
    return bool(user.has_perm(THALES_ACCESS_PERMISSION))
