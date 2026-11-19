"""Create the WatsonCrick access group after migrations.

This has to be a ``post_migrate`` receiver rather than a data migration: Django
creates content types and model permissions during ``post_migrate``, so a
migration that ran earlier could not reliably look up the
``watsoncrick.access_watsoncrick`` permission. The receiver is idempotent: it creates the
permission and group if they are missing and attaches the permission on every
run.
"""

from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_migrate
from django.dispatch import receiver

# WatsonCrick-domain constants. The permission attaches to watsoncrick.Lesson, so the
# app owns the definition. The blog's policy layer (auth_app/permissions.py)
# keeps its own matching literals — they are two stable strings, and keeping
# them duplicated means this app imports nothing from its host. See
# docs/WATSONCRICK_INTEGRATION.md.
WATSONCRICK_GROUP = "WatsonCrick"
WATSONCRICK_PERMISSION_CODENAME = "access_watsoncrick"
WATSONCRICK_PERMISSION_NAME = "Can access the WatsonCrick lab"

WATSONCRICK_ADVISOR_GROUP = "WatsonCrick Advisors"
WATSONCRICK_ADVISOR_PERMISSION_CODENAME = "advise_students"
WATSONCRICK_ADVISOR_PERMISSION_NAME = "Can advise WatsonCrick students"

# The app used to be named ``thales``. Existing databases still have these
# groups and permissions; the migration below folds them into the new names so
# nobody loses lab access when the app label changes.
LEGACY_GROUP = "Thales"
LEGACY_ADVISOR_GROUP = "Thales Advisors"
LEGACY_APP_LABEL = "thales"


def _migrate_legacy_access(permission, advisor_permission):
    """Rename (or merge) the old groups, then drop the stale permissions."""
    for old_name, new_name, perms in (
        (LEGACY_GROUP, WATSONCRICK_GROUP, (permission,)),
        (LEGACY_ADVISOR_GROUP, WATSONCRICK_ADVISOR_GROUP, (permission, advisor_permission)),
    ):
        legacy = Group.objects.filter(name=old_name).first()
        if legacy is None:
            continue
        current = Group.objects.filter(name=new_name).exclude(pk=legacy.pk).first()
        if current is None:
            # Renaming the row in place keeps every user's membership intact.
            legacy.name = new_name
            legacy.save(update_fields=["name"])
            target = legacy
        else:
            # Both groups already exist: merge users into the new one.
            target = current
            target.user_set.add(*legacy.user_set.all())
            legacy.delete()
        target.permissions.add(*perms)

    Permission.objects.filter(content_type__app_label=LEGACY_APP_LABEL).delete()
    ContentType.objects.filter(app_label=LEGACY_APP_LABEL).delete()


@receiver(post_migrate)
def ensure_watsoncrick_group(sender, **kwargs):
    if getattr(sender, "label", None) != "watsoncrick":
        return

    lesson_model = apps.get_model("watsoncrick", "Lesson")
    content_type = ContentType.objects.get_for_model(lesson_model)
    permission, _ = Permission.objects.update_or_create(
        content_type=content_type,
        codename=WATSONCRICK_PERMISSION_CODENAME,
        defaults={"name": WATSONCRICK_PERMISSION_NAME},
    )
    advisor_permission, _ = Permission.objects.update_or_create(
        content_type=content_type,
        codename=WATSONCRICK_ADVISOR_PERMISSION_CODENAME,
        defaults={"name": WATSONCRICK_ADVISOR_PERMISSION_NAME},
    )

    group, _ = Group.objects.get_or_create(name=WATSONCRICK_GROUP)
    group.permissions.add(permission)

    # Advisors also use the lab, so the advisor group carries normal WatsonCrick
    # access as well as the advising capability.
    advisor_group, _ = Group.objects.get_or_create(name=WATSONCRICK_ADVISOR_GROUP)
    advisor_group.permissions.add(permission, advisor_permission)

    _migrate_legacy_access(permission, advisor_permission)
