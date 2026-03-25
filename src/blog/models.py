"""
Blog models for creating and managing blog posts.
Uses Lexical editor format for content storage.
"""
from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
import json


def _lexical_to_text(content_json: str) -> str:
    """Extract plain text from Lexical JSON content by walking the node tree."""
    try:
        data = json.loads(content_json)
    except (json.JSONDecodeError, TypeError):
        return ''

    parts = []

    def walk(node):
        if isinstance(node, dict):
            if node.get('type') == 'text':
                text = node.get('text', '')
                if text:
                    parts.append(text)
            else:
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return ' '.join(parts)


class Category(models.Model):
    """
    Category model for organizing blog posts.
    Supports M2M relationship with BlogPost.
    """
    name = models.CharField(max_length=100, unique=True, db_index=True)
    slug = models.SlugField(max_length=100, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Category'
        verbose_name_plural = 'Categories'
        indexes = [
            models.Index(fields=['slug']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class BlogPost(models.Model):
    """
    Blog post model with Lexical editor support.
    
    Supports:
    - Multiple categories (M2M)
    - Author ownership and role-based access
    - Status management (draft, published, scheduled, archived)
    - View count tracking
    - Lexical JSON content storage
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('scheduled', 'Scheduled'),
        ('archived', 'Archived'),
    ]

    # Core fields
    title = models.CharField(max_length=500, db_index=True)
    slug = models.SlugField(max_length=500, unique=True, db_index=True)
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='blog_posts',
        help_text='The author/editor of the blog post'
    )

    # Content
    content_json = models.TextField(
        help_text='Lexical editor JSON format for rich content'
    )
    content_text = models.TextField(
        blank=True,
        default='',
        help_text='Plain-text extract of content_json, kept in sync on save, used for full-text search'
    )

    # Metadata
    categories = models.ManyToManyField(
        Category,
        related_name='blog_posts',
        blank=True,
        help_text='Categories for organizing blog posts'
    )

    # Status & Publishing
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        db_index=True,
        help_text='Publication status of the blog post'
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text='When the blog post was published (auto-set when status changes to published)'
    )

    # Analytics
    view_count = models.PositiveIntegerField(
        default=0,
        help_text='Number of times this blog post has been viewed'
    )
    like_count = models.PositiveIntegerField(
        default=0,
        help_text='Number of likes this blog post has received'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-created_at']
        verbose_name = 'Blog Post'
        verbose_name_plural = 'Blog Posts'
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['author', 'status']),
            models.Index(fields=['status', '-published_at']),
        ]
        permissions = [
            ('can_publish_post', 'Can publish blog posts'),
            ('can_archive_post', 'Can archive blog posts'),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)

        # Auto-set published_at when status changes to published
        if self.status == 'published' and not self.published_at:
            from django.utils import timezone
            self.published_at = timezone.now()

        # Keep plain-text copy of content in sync for full-text search
        self.content_text = _lexical_to_text(self.content_json)

        super().save(*args, **kwargs)

    def get_content_dict(self):
        """
        Parse and return the JSON content as a dictionary.
        Returns empty dict if content_json is invalid.
        """
        try:
            return json.loads(self.content_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    def increment_view_count(self):
        """Increment the view count by 1."""
        self.view_count += 1
        self.save(update_fields=['view_count', 'updated_at'])

    def increment_like_count(self):
        """Increment the like count by 1."""
        self.like_count += 1
        self.save(update_fields=['like_count', 'updated_at'])


class Comment(models.Model):
    """
    Threaded comment on a blog post.
    Uses a self-referential FK for unlimited nesting depth.
    Soft-deleted to preserve reply thread structure.
    """
    post = models.ForeignKey(
        BlogPost,
        on_delete=models.CASCADE,
        related_name='comments',
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='comments',
    )
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='replies',
    )
    content_json = models.TextField(
        help_text='Lexical editor JSON format for rich content'
    )
    is_deleted = models.BooleanField(
        default=False,
        help_text='Soft-delete flag — preserves row so child replies remain intact'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['post', 'parent', 'created_at']),
        ]

    def __str__(self):
        return f'Comment {self.id} by {self.author_id} on post {self.post_id}'
