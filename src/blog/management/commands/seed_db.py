"""
Management command to seed the development database with sample data.

Usage:
    python manage.py seed_db           # Create seed data (skips existing records)
    python manage.py seed_db --reset   # Delete seed data and recreate from scratch
"""

import json

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand

from blog.models import BlogPost, Category, Comment, Tag
from recipes.models import (
    DietaryLabel,
    Recipe,
    RecipeIngredient,
    RecipeInstruction,
    RecipeRating,
)

# ---------------------------------------------------------------------------
# Lexical JSON helpers
# ---------------------------------------------------------------------------

def _lexical(text):
    """Build a minimal single-paragraph Lexical JSON string."""
    return json.dumps({
        "root": {
            "children": [{
                "children": [{"detail": 0, "format": 0, "mode": "normal", "style": "",
                               "text": text, "type": "text", "version": 1}],
                "direction": "ltr", "format": "", "indent": 0,
                "type": "paragraph", "version": 1,
            }],
            "direction": "ltr", "format": "", "indent": 0,
            "type": "root", "version": 1,
        }
    })


def _lexical_multi(*paragraphs):
    """Build a Lexical JSON string with multiple paragraphs."""
    children = []
    for text in paragraphs:
        children.append({
            "children": [{"detail": 0, "format": 0, "mode": "normal", "style": "",
                           "text": text, "type": "text", "version": 1}],
            "direction": "ltr", "format": "", "indent": 0,
            "type": "paragraph", "version": 1,
        })
    return json.dumps({
        "root": {
            "children": children,
            "direction": "ltr", "format": "", "indent": 0,
            "type": "root", "version": 1,
        }
    })


def _image_node(src, alt_text=""):
    """Build a Lexical image node dict (top-level child of root)."""
    return {"type": "image", "version": 1, "src": src, "altText": alt_text}


def _paragraph_node(text):
    """Build a Lexical paragraph node dict."""
    return {
        "children": [{"detail": 0, "format": 0, "mode": "normal", "style": "",
                       "text": text, "type": "text", "version": 1}],
        "direction": "ltr", "format": "", "indent": 0,
        "type": "paragraph", "version": 1,
    }


def _lexical_with_image(src, alt_text, *paragraphs):
    """Build Lexical JSON: image first, then paragraphs."""
    children = [_image_node(src, alt_text)]
    children += [_paragraph_node(t) for t in paragraphs]
    return json.dumps({
        "root": {
            "children": children,
            "direction": "ltr", "format": "", "indent": 0,
            "type": "root", "version": 1,
        }
    })


# ---------------------------------------------------------------------------
# Seed data definitions
# ---------------------------------------------------------------------------

SEED_USERS = [
    {"username": "admin",  "email": "admin@example.com",  "password": "Admin1234!",  "role": "admin"},
    {"username": "editor", "email": "editor@example.com", "password": "Editor1234!", "role": "editor"},
    {"username": "reader", "email": "reader@example.com", "password": "Reader1234!", "role": "reader"},
]

SEED_TAGS = ["python", "django", "nextjs", "recipe", "tutorial"]

SEED_DIETARY_LABELS = ["Vegetarian", "Vegan", "Gluten-Free", "Dairy-Free"]

SEED_POSTS = [
    {
        "title": "Getting Started with Django Ninja",
        "slug": "getting-started-with-django-ninja",
        "status": "published",
        "category": "Technology",
        "tags": ["python", "django", "tutorial"],
        "content": _lexical_with_image(
            "https://picsum.photos/seed/django-ninja/800/450",
            "Django Ninja API framework",
            "Django Ninja is a modern, fast web framework for building APIs with Django and Python type hints.",
            "In this post, we'll walk through setting up your first Django Ninja project, defining schemas with Pydantic, and building type-safe REST endpoints.",
            "By the end, you'll have a fully functional API with automatic OpenAPI documentation — all with minimal boilerplate.",
        ),
    },
    {
        "title": "Building a Blog with Next.js 14",
        "slug": "building-a-blog-with-nextjs-14",
        "status": "published",
        "category": "Technology",
        "tags": ["nextjs", "tutorial"],
        "content": _lexical_with_image(
            "https://picsum.photos/seed/nextjs-blog/800/450",
            "Next.js 14 App Router",
            "Next.js 14 introduces the App Router, a new paradigm for building React applications with server components, streaming, and nested layouts.",
            "This guide covers creating a personal blog from scratch: setting up the App Router, fetching data from a Django backend, and deploying to production.",
            "We'll also look at how to implement dark mode with next-themes and style components using Tailwind CSS.",
        ),
    },
    {
        "title": "My Favorite Pasta Recipe",
        "slug": "my-favorite-pasta-recipe",
        "status": "published",
        "category": "Food & Cooking",
        "tags": ["recipe"],
        "content": _lexical_with_image(
            "https://picsum.photos/seed/pasta-dish/800/450",
            "A bowl of fresh pasta",
            "After years of experimenting in the kitchen, I've landed on what I consider the perfect weeknight pasta.",
            "The secret is using good quality pasta (bronze-die extruded if you can find it) and finishing the pasta in the sauce for the last two minutes of cooking.",
            "Check out my full Spaghetti Carbonara recipe in the Recipes section for all the details.",
        ),
    },
    {
        "title": "Draft: Ideas for Next Week",
        "slug": "draft-ideas-for-next-week",
        "status": "draft",
        "category": None,
        "tags": [],
        "content": _lexical("Work in progress — just a placeholder draft post for testing the dashboard."),
    },
    {
        "title": "Archived: Hello World",
        "slug": "archived-hello-world",
        "status": "archived",
        "category": "Technology",
        "tags": ["python"],
        "content": _lexical("This was the very first post on the blog. It has since been archived."),
    },
]

SEED_RECIPES = [
    {
        "title": "Classic Spaghetti Carbonara",
        "slug": "classic-spaghetti-carbonara",
        "status": "published",
        "cuisine_type": "italian",
        "course": "main_course",
        "prep_time_minutes": 10,
        "cook_time_minutes": 20,
        "yield_amount": "2",
        "yield_unit": "servings",
        "description": "A rich, creamy Roman pasta made with eggs, Pecorino Romano, guanciale, and black pepper. No cream required.",
        "images": [
            "https://picsum.photos/seed/carbonara/800/600",
            "https://picsum.photos/seed/carbonara-2/800/600",
        ],
        "tags": ["recipe"],
        "dietary_labels": [],
        "ingredients": [
            {"order": 1, "amount": "200", "unit": "g",    "name": "spaghetti"},
            {"order": 2, "amount": "100", "unit": "g",    "name": "guanciale or pancetta", "notes": "cut into small cubes"},
            {"order": 3, "amount": "2",   "unit": "",     "name": "large eggs"},
            {"order": 4, "amount": "50",  "unit": "g",    "name": "Pecorino Romano", "notes": "finely grated"},
            {"order": 5, "amount": "1",   "unit": "tsp",  "name": "freshly ground black pepper"},
            {"order": 6, "amount": "1",   "unit": "tsp",  "name": "salt", "notes": "for pasta water"},
        ],
        "instructions": [
            {"step_number": 1, "title": "Cook the pasta", "content": "Bring a large pot of salted water to a boil. Cook spaghetti according to package directions until al dente. Reserve 1 cup of pasta water before draining."},
            {"step_number": 2, "title": "Render the guanciale", "content": "While pasta cooks, fry guanciale in a large skillet over medium heat until crispy and golden, about 5–7 minutes. Remove pan from heat."},
            {"step_number": 3, "title": "Make the sauce", "content": "Whisk eggs and Pecorino Romano together in a bowl until smooth. Season generously with black pepper."},
            {"step_number": 4, "title": "Combine", "content": "Add hot drained pasta to the skillet with guanciale. Off the heat, pour the egg mixture over the pasta and toss vigorously, adding pasta water a splash at a time until a creamy sauce forms."},
            {"step_number": 5, "title": "Serve", "content": "Plate immediately with extra grated Pecorino and black pepper on top."},
        ],
    },
    {
        "title": "Simple Chocolate Chip Cookies",
        "slug": "simple-chocolate-chip-cookies",
        "status": "published",
        "cuisine_type": "american",
        "course": "dessert",
        "prep_time_minutes": 15,
        "cook_time_minutes": 12,
        "yield_amount": "24",
        "yield_unit": "cookies",
        "description": "Classic chewy chocolate chip cookies with crisp edges — ready in under 30 minutes.",
        "images": [
            "https://picsum.photos/seed/cookies/800/600",
        ],
        "tags": ["recipe"],
        "dietary_labels": ["Vegetarian"],
        "ingredients": [
            {"order": 1, "amount": "2.25", "unit": "cups", "name": "all-purpose flour"},
            {"order": 2, "amount": "1",    "unit": "tsp",  "name": "baking soda"},
            {"order": 3, "amount": "1",    "unit": "tsp",  "name": "salt"},
            {"order": 4, "amount": "1",    "unit": "cup",  "name": "unsalted butter", "notes": "softened"},
            {"order": 5, "amount": "0.75", "unit": "cup",  "name": "granulated sugar"},
            {"order": 6, "amount": "0.75", "unit": "cup",  "name": "packed brown sugar"},
            {"order": 7, "amount": "2",    "unit": "",     "name": "large eggs"},
            {"order": 8, "amount": "2",    "unit": "tsp",  "name": "vanilla extract"},
            {"order": 9, "amount": "2",    "unit": "cups", "name": "chocolate chips"},
        ],
        "instructions": [
            {"step_number": 1, "title": "Preheat oven", "content": "Preheat oven to 375°F (190°C). Line baking sheets with parchment paper."},
            {"step_number": 2, "title": "Mix dry ingredients", "content": "Whisk together flour, baking soda, and salt in a bowl. Set aside."},
            {"step_number": 3, "title": "Cream butter and sugars", "content": "Beat butter, granulated sugar, and brown sugar in a large bowl until light and fluffy, about 3 minutes. Beat in eggs one at a time, then add vanilla."},
            {"step_number": 4, "title": "Combine and add chips", "content": "Gradually mix in the flour mixture until just combined. Stir in chocolate chips."},
            {"step_number": 5, "title": "Bake", "content": "Drop rounded tablespoons of dough onto prepared baking sheets, spacing 2 inches apart. Bake 9–11 minutes until edges are golden. Cool on pan for 5 minutes before transferring."},
        ],
    },
    {
        "title": "Draft: Homemade Ramen",
        "slug": "draft-homemade-ramen",
        "status": "draft",
        "cuisine_type": "japanese",
        "course": "main_course",
        "prep_time_minutes": 30,
        "cook_time_minutes": 180,
        "yield_amount": "4",
        "yield_unit": "servings",
        "description": "A rich tonkotsu-style ramen broth — still working on perfecting this one.",
        "images": [
            "https://picsum.photos/seed/ramen-bowl/800/600",
        ],
        "tags": ["recipe"],
        "dietary_labels": [],
        "ingredients": [
            {"order": 1, "amount": "1",   "unit": "kg",   "name": "pork bones"},
            {"order": 2, "amount": "4",   "unit": "cups", "name": "chicken stock"},
            {"order": 3, "amount": "4",   "unit": "",     "name": "ramen noodle portions"},
            {"order": 4, "amount": "4",   "unit": "",     "name": "soft boiled eggs", "notes": "marinated in soy sauce"},
        ],
        "instructions": [
            {"step_number": 1, "title": "Blanch bones", "content": "Cover pork bones with cold water, bring to a boil, drain and rinse."},
            {"step_number": 2, "title": "Simmer broth", "content": "Return bones to pot with fresh water and chicken stock. Simmer for 3–4 hours until milky and rich."},
            {"step_number": 3, "title": "Cook noodles and assemble", "content": "Cook noodles per package directions. Ladle broth into bowls, add noodles, and top with egg and desired toppings."},
        ],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(self, msg):
    self.stdout.write(self.style.SUCCESS(f"  ✓ {msg}"))

def _skip(self, msg):
    self.stdout.write(f"  - {msg} [skipped]")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Seed the database with sample users, blog posts, and recipes for development."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing seed data before recreating it.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Seeding database ===\n"))

        users   = self._seed_users()
        cats    = self._seed_categories()
        tags    = self._seed_tags()
        dlabels = self._seed_dietary_labels()
        editor  = users["editor"]
        reader  = users["reader"]
        posts   = self._seed_posts(editor, cats, tags)
        recipes = self._seed_recipes(editor, tags, dlabels)
        self._seed_comments(reader, posts, recipes)
        self._seed_ratings(reader, recipes)

        self.stdout.write(self.style.SUCCESS("\n=== Done! ===\n"))
        self.stdout.write("Credentials:")
        for u in SEED_USERS:
            self.stdout.write(f"  {u['role']:8s}  {u['email']:30s}  {u['password']}")
        self.stdout.write("")

    # -----------------------------------------------------------------------

    def _reset(self):
        self.stdout.write(self.style.WARNING("\n--- Resetting seed data ---"))
        usernames = [u["username"] for u in SEED_USERS]
        post_slugs   = [p["slug"] for p in SEED_POSTS]
        recipe_slugs = [r["slug"] for r in SEED_RECIPES]

        Comment.objects.filter(author__username__in=usernames).delete()
        RecipeRating.objects.filter(user__username__in=usernames).delete()
        BlogPost.objects.filter(slug__in=post_slugs).delete()
        Recipe.objects.filter(slug__in=recipe_slugs).delete()
        User.objects.filter(username__in=usernames).delete()
        self.stdout.write(self.style.WARNING("--- Reset complete ---\n"))

    # -----------------------------------------------------------------------

    def _seed_users(self):
        self.stdout.write(self.style.MIGRATE_HEADING("Users"))
        result = {}
        for data in SEED_USERS:
            user, created = User.objects.get_or_create(
                username=data["username"],
                defaults={"email": data["email"]},
            )
            if created:
                user.set_password(data["password"])
                user.save()
                user.profile.role = data["role"]
                user.profile.email_verified = True
                user.profile.save()
                _ok(self, f"{data['username']} ({data['role']})")
            else:
                _skip(self, f"{data['username']} ({data['role']})")
            result[data["username"]] = user
        return result

    def _seed_categories(self):
        call_command('seed_categories', stdout=self.stdout, stderr=self.stderr)
        return {cat.name: cat for cat in Category.objects.all()}

    def _seed_tags(self):
        self.stdout.write(self.style.MIGRATE_HEADING("Tags"))
        result = {}
        for name in SEED_TAGS:
            tag, created = Tag.objects.get_or_create(name=name)
            if created:
                _ok(self, name)
            else:
                _skip(self, name)
            result[name] = tag
        return result

    def _seed_dietary_labels(self):
        self.stdout.write(self.style.MIGRATE_HEADING("Dietary Labels"))
        result = {}
        for name in SEED_DIETARY_LABELS:
            label, created = DietaryLabel.objects.get_or_create(name=name)
            if created:
                _ok(self, name)
            else:
                _skip(self, name)
            result[name] = label
        return result

    def _seed_posts(self, editor, cats, tags):
        self.stdout.write(self.style.MIGRATE_HEADING("Blog Posts"))
        result = {}
        for data in SEED_POSTS:
            post, created = BlogPost.objects.get_or_create(
                slug=data["slug"],
                defaults={
                    "title":        data["title"],
                    "author":       editor,
                    "content_json": data["content"],
                    "status":       data["status"],
                    "category":     cats.get(data["category"]),
                },
            )
            if created:
                for tag_name in data.get("tags", []):
                    if tag_name in tags:
                        post.tags.add(tags[tag_name])
                _ok(self, f"{data['title']} [{data['status']}]")
            else:
                _skip(self, f"{data['title']} [{data['status']}]")
            result[data["slug"]] = post
        return result

    def _seed_recipes(self, editor, tags, dlabels):
        self.stdout.write(self.style.MIGRATE_HEADING("Recipes"))
        result = {}
        for data in SEED_RECIPES:
            recipe, created = Recipe.objects.get_or_create(
                slug=data["slug"],
                defaults={
                    "title":             data["title"],
                    "author":            editor,
                    "status":            data["status"],
                    "cuisine_type":      data.get("cuisine_type", ""),
                    "course":            data.get("course", ""),
                    "prep_time_minutes": data.get("prep_time_minutes"),
                    "cook_time_minutes": data.get("cook_time_minutes"),
                    "yield_amount":      data.get("yield_amount"),
                    "yield_unit":        data.get("yield_unit", ""),
                    "description":       data.get("description", ""),
                    "images":            data.get("images", []),
                },
            )
            if created:
                for tag_name in data.get("tags", []):
                    if tag_name in tags:
                        recipe.tags.add(tags[tag_name])
                for label_name in data.get("dietary_labels", []):
                    if label_name in dlabels:
                        recipe.dietary_labels.add(dlabels[label_name])
                for ing in data.get("ingredients", []):
                    RecipeIngredient.objects.create(
                        recipe=recipe,
                        order=ing.get("order", 0),
                        amount=ing["amount"],
                        unit=ing.get("unit", ""),
                        name=ing["name"],
                        notes=ing.get("notes", ""),
                    )
                for ins in data.get("instructions", []):
                    RecipeInstruction.objects.create(
                        recipe=recipe,
                        step_number=ins["step_number"],
                        title=ins.get("title", ""),
                        content=ins["content"],
                    )
                _ok(self, f"{data['title']} [{data['status']}]")
            else:
                _skip(self, f"{data['title']} [{data['status']}]")
            result[data["slug"]] = recipe
        return result

    def _seed_comments(self, reader, posts, recipes):
        self.stdout.write(self.style.MIGRATE_HEADING("Comments"))
        # Comment on the first published blog post
        first_post = posts.get("getting-started-with-django-ninja")
        if first_post:
            _, created = Comment.objects.get_or_create(
                author=reader,
                post=first_post,
                parent=None,
                defaults={"content_json": _lexical("Great introduction! The type hint support makes this so much cleaner than DRF.")},
            )
            if created:
                _ok(self, f"Comment on '{first_post.title}'")
            else:
                _skip(self, f"Comment on '{first_post.title}'")

        # Comment on the first published recipe
        first_recipe = recipes.get("classic-spaghetti-carbonara")
        if first_recipe:
            _, created = Comment.objects.get_or_create(
                author=reader,
                recipe=first_recipe,
                parent=None,
                defaults={"content_json": _lexical("Made this last night — absolutely delicious. The key tip about finishing in the pan really makes a difference!")},
            )
            if created:
                _ok(self, f"Comment on '{first_recipe.title}'")
            else:
                _skip(self, f"Comment on '{first_recipe.title}'")

    def _seed_ratings(self, reader, recipes):
        self.stdout.write(self.style.MIGRATE_HEADING("Ratings"))
        ratings = [
            ("classic-spaghetti-carbonara", 5),
            ("simple-chocolate-chip-cookies", 4),
        ]
        for slug, score in ratings:
            recipe = recipes.get(slug)
            if not recipe:
                continue
            _, created = RecipeRating.objects.get_or_create(
                recipe=recipe,
                user=reader,
                defaults={"score": score},
            )
            if created:
                _ok(self, f"{recipe.title}: {score}/5")
            else:
                _skip(self, f"{recipe.title}: {score}/5")
