"""
Bootstrap a superuser at deploy time — create-if-missing, never reset.

This replaces the old entrypoint block that ran
``set_password($DJANGO_SUPERUSER_PASSWORD)`` on every container boot. That
pattern pinned the account's password to a credential stored in Railway (and
mirrored in a committed file) forever: every restart silently undid any
password the admin had chosen. Deploy scripts should create state, not
enforce it.

This command:
  * does nothing unless ``DJANGO_SUPERUSER_USERNAME`` is set;
  * does nothing at all if that user already exists — password, role and
    email_verified are left exactly as they are;
  * otherwise creates the account with an *unusable* password, so no secret
    ever lives in the environment.

The real password is then chosen by the admin through the app's own
forgot-password flow (``POST /api/auth/password-reset-request``), which looks
accounts up by email and does not check ``has_usable_password()`` — unlike
Django's built-in ``PasswordResetForm``, which would refuse to mail a user
with an unusable password. That is why ``DJANGO_SUPERUSER_EMAIL`` matters:
without an address on the account, the reset email has nowhere to go.

Usage:
    python manage.py ensure_superuser
"""

import os

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.validators import validate_email
from django.db import IntegrityError, transaction


class Command(BaseCommand):
    help = (
        "Create the bootstrap superuser if it does not already exist. "
        "Never modifies an existing account."
    )

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()

        if not username:
            self.stdout.write(
                "DJANGO_SUPERUSER_USERNAME is not set; skipping superuser bootstrap."
            )
            return

        # Existing account: stop here. Reaching for set_password() or a role
        # patch on the next line is exactly the bug this command replaces.
        if User.objects.filter(username=username).exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Superuser '{username}' already exists — left untouched."
                )
            )
            return

        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
        if email:
            try:
                validate_email(email)
            except ValidationError:
                self.stdout.write(
                    self.style.WARNING(
                        f"DJANGO_SUPERUSER_EMAIL '{email}' is not a valid address; "
                        "creating the account without it."
                    )
                )
                email = ""

        try:
            # Savepoint so a lost race leaves the outer transaction usable —
            # otherwise the retry query below runs on a broken transaction.
            with transaction.atomic():
                user = User.objects.create(
                    username=username,
                    email=email,
                    is_superuser=True,
                    is_staff=True,
                )
        except IntegrityError:
            # Two replicas booting at once both pass the exists() check above
            # and race to insert. The loser must not fail the deploy: the
            # winner has already created the account we wanted.
            if User.objects.filter(username=username).exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"Superuser '{username}' was created concurrently — "
                        "left untouched."
                    )
                )
                return
            raise

        user.set_unusable_password()
        user.save(update_fields=["password"])

        # The post_save signal has already created the profile; promote it.
        profile = user.profile
        profile.role = "admin"
        profile.email_verified = True
        profile.save(update_fields=["role", "email_verified", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Created superuser '{username}' with an unusable password."
            )
        )
        if email:
            self.stdout.write(
                f"Choose a real password via the forgot-password flow using {email}."
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "DJANGO_SUPERUSER_EMAIL is not set, so this account has no "
                    "email address and the forgot-password flow cannot reach it. "
                    "Set an email on the account before you need to reset its "
                    "password."
                )
            )
