"""
Utility functions for blog operations.
"""
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify
from .models import BlogPost, Category
from typing import Optional


def create_unique_slug(title: str, existing_slugs=None) -> str:
    """
    Generate a unique slug from title.
    If slug already exists, append a number to make it unique.
    """
    base_slug = slugify(title)
    slug = base_slug
    counter = 1

    if existing_slugs is None:
        existing_slugs = set(BlogPost.objects.values_list('slug', flat=True))
    else:
        existing_slugs = set(existing_slugs)

    while slug in existing_slugs:
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug


def can_edit_post(user, blog_post) -> bool:
    """
    Check if user has permission to edit blog post based on role.
    - Admin: can edit any post
    - Editor: can only edit their own posts
    - Reader: cannot edit posts
    """
    if not hasattr(user, 'profile'):
        return False

    role = user.profile.role
    
    if role == 'admin':
        return True
    elif role == 'editor':
        return blog_post.author.id == user.id
    
    return False


def can_publish_post(user, blog_post) -> bool:
    """
    Check if user can publish/unpublish blog post.
    - Admin: can publish any post
    - Editor: can publish only their own posts
    - Reader: cannot publish
    """
    if not hasattr(user, 'profile'):
        return False

    role = user.profile.role
    
    if role == 'admin':
        return True
    elif role == 'editor':
        return blog_post.author.id == user.id
    
    return False


def can_delete_post(user, blog_post) -> bool:
    """
    Check if user can delete blog post.
    - Admin: can delete any post
    - Editor: can delete only their own posts
    - Reader: cannot delete
    """
    return can_edit_post(user, blog_post)


def get_published_posts(limit: Optional[int] = None, category: Optional[str] = None, search: Optional[str] = None):
    """Get all published blog posts, optionally filtered by category slug, search query, and limited."""
    queryset = BlogPost.objects.filter(
        status='published'
    ).select_related('author', 'author__profile', 'category')

    if category:
        queryset = queryset.filter(category__slug=category)

    if search:
        queryset = queryset.filter(
            Q(title__icontains=search) |
            Q(author__username__icontains=search) |
            Q(content_text__icontains=search)
        )

    if limit:
        queryset = queryset[:limit]

    return queryset


def get_user_posts(user, include_drafts=True):
    """Get blog posts for a specific user."""
    queryset = BlogPost.objects.filter(author=user).select_related(
        'author', 'author__profile', 'category'
    )

    if not include_drafts:
        queryset = queryset.exclude(status='draft')

    return queryset
