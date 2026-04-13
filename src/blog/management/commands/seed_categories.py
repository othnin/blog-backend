"""
Management command to seed the 5 hardcoded blog categories.

Usage:
    python manage.py seed_categories

Safe to run multiple times — uses get_or_create by slug.
"""
from django.core.management.base import BaseCommand
from blog.models import Category

CATEGORIES = [
    ("Food & Cooking", "food-cooking"),
    ("Technology",     "technology"),
    ("Science",        "science"),
    ("Politics",       "politics"),
    ("Philosophy",     "philosophy"),
]


class Command(BaseCommand):
    help = "Seed the database with the 5 hardcoded blog categories."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Seeding categories ===\n"))
        for name, slug in CATEGORIES:
            cat, created = Category.objects.get_or_create(
                slug=slug,
                defaults={"name": name},
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created: {name}"))
            else:
                self.stdout.write(f"  - Skipped: {name} [already exists]")
        self.stdout.write(self.style.SUCCESS("\n=== Done! ===\n"))
