"""Capability checks that sit alongside the blog role.

``UserProfile.role`` answers "what may this person do on the blog?" and is
deliberately single-valued. Thales access is a separate axis: a blog reader or
editor may also be a lab member, and an admin may use the lab without being
added to its group. Keeping the two independent avoids a role for every
combination (thales-reader, thales-editor, ...).
"""

THALES_ACCESS_PERMISSION = "thales.access_thales"
THALES_ADVISOR_PERMISSION = "thales.advise_students"

THALES_GROUP = "Thales"
THALES_PERMISSION_CODENAME = "access_thales"
THALES_PERMISSION_NAME = "Can access the Thales lab"

THALES_ADVISOR_GROUP = "Thales Advisors"
THALES_ADVISOR_PERMISSION_CODENAME = "advise_students"
THALES_ADVISOR_PERMISSION_NAME = "Can advise Thales students"


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
    Advisors also get the normal lab capability.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if is_admin(user):
        return True
    return bool(
        user.has_perm(THALES_ACCESS_PERMISSION)
        or user.has_perm(THALES_ADVISOR_PERMISSION)
    )


def has_advisor_access(user):
    """Whether ``user`` may inspect students and leave advisor feedback.

    This is a separate capability from ordinary lab access. An advisor is a
    member of the ``Thales Advisors`` group; admins bypass the group for the
    same lockout reason as above.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if is_admin(user):
        return True
    return bool(user.has_perm(THALES_ADVISOR_PERMISSION))
