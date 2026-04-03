"""
Utility functions for recipe operations.
"""
from django.db.models import Q, Avg, Count
from django.utils.text import slugify
from typing import Optional
from .models import Recipe


def create_unique_recipe_slug(title: str) -> str:
    """Generate a unique slug for a recipe from its title."""
    base_slug = slugify(title)
    slug = base_slug
    counter = 1
    existing = set(Recipe.objects.values_list('slug', flat=True))
    while slug in existing:
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def can_edit_recipe(user, recipe) -> bool:
    """Check if user has permission to edit a recipe."""
    if not hasattr(user, 'profile'):
        return False
    role = user.profile.role
    if role == 'admin':
        return True
    if role == 'editor':
        return recipe.author_id == user.id
    return False


def get_published_recipes(
    cuisine: Optional[str] = None,
    course: Optional[str] = None,
    dietary: Optional[str] = None,
    tags: Optional[str] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
):
    """Get published recipes with optional filters and rating annotations."""
    qs = (
        Recipe.objects.filter(status='published')
        .select_related('author', 'author__profile')
        .prefetch_related('tags', 'dietary_labels', 'ingredients', 'instructions')
        .annotate(
            avg_rating=Avg('ratings__score'),
            rating_count=Count('ratings', distinct=True),
        )
    )

    if cuisine:
        qs = qs.filter(cuisine_type=cuisine)

    if course:
        qs = qs.filter(course=course)

    if dietary:
        for slug in [s.strip() for s in dietary.split(',') if s.strip()]:
            qs = qs.filter(dietary_labels__slug=slug)
        qs = qs.distinct()

    if tags:
        for slug in [s.strip() for s in tags.split(',') if s.strip()]:
            qs = qs.filter(tags__slug=slug)
        qs = qs.distinct()

    if search:
        qs = qs.filter(
            Q(title__icontains=search) |
            Q(description__icontains=search) |
            Q(author__username__icontains=search)
        )

    if limit:
        qs = qs[:limit]

    return qs
