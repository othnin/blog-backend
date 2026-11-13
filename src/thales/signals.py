"""Create the Thales access group after migrations.

This has to be a ``post_migrate`` receiver rather than a data migration: Django
creates content types and model permissions during ``post_migrate``, so a
migration that ran earlier could not reliably look up the
``thales.access_thales`` permission. The receiver is idempotent: it creates the
permission and group if they are missing and attaches the permission on every
run.
"""

from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_migrate
from django.dispatch import receiver

# Thales-domain constants. The permission attaches to thales.Lesson, so the
# app owns the definition. The blog's policy layer (auth_app/permissions.py)
# keeps its own matching literals — they are two stable strings, and keeping
# them duplicated means this app imports nothing from its host. See
# docs/THALES_INTEGRATION.md.
THALES_GROUP = "Thales"
THALES_PERMISSION_CODENAME = "access_thales"
THALES_PERMISSION_NAME = "Can access the Thales lab"

THALES_ADVISOR_GROUP = "Thales Advisors"
THALES_ADVISOR_PERMISSION_CODENAME = "advise_students"
THALES_ADVISOR_PERMISSION_NAME = "Can advise Thales students"


@receiver(post_migrate)
def ensure_thales_group(sender, **kwargs):
    if getattr(sender, "label", None) != "thales":
        return

    lesson_model = apps.get_model("thales", "Lesson")
    content_type = ContentType.objects.get_for_model(lesson_model)
    permission, _ = Permission.objects.update_or_create(
        content_type=content_type,
        codename=THALES_PERMISSION_CODENAME,
        defaults={"name": THALES_PERMISSION_NAME},
    )
    advisor_permission, _ = Permission.objects.update_or_create(
        content_type=content_type,
        codename=THALES_ADVISOR_PERMISSION_CODENAME,
        defaults={"name": THALES_ADVISOR_PERMISSION_NAME},
    )

    group, _ = Group.objects.get_or_create(name=THALES_GROUP)
    group.permissions.add(permission)

    # Advisors also use the lab, so the advisor group carries normal Thales
    # access as well as the advising capability.
    advisor_group, _ = Group.objects.get_or_create(name=THALES_ADVISOR_GROUP)
    advisor_group.permissions.add(permission, advisor_permission)
