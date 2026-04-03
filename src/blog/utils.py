"""
Utility functions for blog operations.
"""
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify
from django.conf import settings
from .models import BlogPost, Category, Comment
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


def get_published_posts(limit: Optional[int] = None, category: Optional[str] = None, search: Optional[str] = None, tags: Optional[str] = None):
    """Get all published blog posts, optionally filtered by category slug, tag slugs, search query, and limited."""
    queryset = BlogPost.objects.filter(
        status='published'
    ).select_related('author', 'author__profile', 'category').prefetch_related('tags')

    if category:
        queryset = queryset.filter(category__slug=category)

    if tags:
        for tag_slug in [s.strip() for s in tags.split(',') if s.strip()]:
            queryset = queryset.filter(tags__slug=tag_slug)
        queryset = queryset.distinct()

    if search:
        queryset = queryset.filter(
            Q(title__icontains=search) |
            Q(author__username__icontains=search) |
            Q(content_text__icontains=search)
        )

    if limit:
        queryset = queryset[:limit]

    return queryset


def _author_dict(user):
    """Build a comment author dict including avatar_url."""
    try:
        avatar_url = f"{settings.MEDIA_URL}{user.profile.avatar.name}" if user.profile.avatar else None
    except Exception:
        avatar_url = None
    return {'id': user.id, 'username': user.username, 'avatar_url': avatar_url}


def _comment_to_dict(c):
    """Serialize a single Comment instance (no replies) to a dict."""
    return {
        'id': c.id,
        'author': _author_dict(c.author) if not c.is_deleted else None,
        'content_json': c.content_json if not c.is_deleted else None,
        'is_deleted': c.is_deleted,
        'created_at': c.created_at,
        'updated_at': c.updated_at,
        'replies': [],
    }


def build_comment_tree(queryset):
    """
    Build a nested comment tree from a pre-filtered queryset.
    Returns a list of dicts matching the CommentOut schema.
    """
    all_comments = queryset.select_related('author', 'author__profile').order_by('created_at')
    comment_map = {}
    roots = []
    for c in all_comments:
        node = {
            'id': c.id,
            'author': _author_dict(c.author) if not c.is_deleted else None,
            'content_json': c.content_json if not c.is_deleted else None,
            'is_deleted': c.is_deleted,
            'created_at': c.created_at,
            'updated_at': c.updated_at,
            'replies': [],
        }
        comment_map[c.id] = node
        if c.parent_id is None:
            roots.append(node)
        else:
            parent_node = comment_map.get(c.parent_id)
            if parent_node:
                parent_node['replies'].append(node)
    return roots


def get_user_posts(user, include_drafts=True):
    """Get blog posts for a specific user."""
    queryset = BlogPost.objects.filter(author=user).select_related(
        'author', 'author__profile', 'category'
    ).prefetch_related('tags')

    if not include_drafts:
        queryset = queryset.exclude(status='draft')

    return queryset
