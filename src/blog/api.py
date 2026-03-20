"""
Blog API endpoints using Django Ninja.
Handles creation, reading, updating, and deletion of blog posts.
"""
from ninja.errors import HttpError
from ninja_extra import api_controller, http_get, http_post, http_put, http_delete
from ninja_extra.permissions import IsAuthenticated
from ninja_jwt.authentication import JWTAuth
from .permissions import IsEditorOrAdmin
from django.shortcuts import get_object_or_404
from django.utils import timezone
from typing import List, Optional
from .models import BlogPost, Category
from .serializers import (
    BlogPostCreateIn,
    BlogPostUpdateIn,
    BlogPostOut,
    BlogPostListOut,
    CategoryOut,
    CategoryCreateIn,
)
from .utils import (
    create_unique_slug,
    can_edit_post,
    can_delete_post,
    get_published_posts,
    get_user_posts,
)


@api_controller("/blog", tags=["Blog"])
class BlogController:
    """
    Blog API controller for managing blog posts and categories.
    """

    # ============= Category Endpoints =============

    @http_get(
        "/categories/",
        response=List[CategoryOut],
        description="Get all blog categories"
    )
    def list_categories(self) -> List[CategoryOut]:
        """Retrieve all blog categories."""
        categories = Category.objects.all().order_by('name')
        return categories

    @http_post(
        "/categories/",
        response=CategoryOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Create a new category"
    )
    def create_category(self, payload: CategoryCreateIn) -> CategoryOut:
        """
        Create a new blog category.
        - Requires editor or admin role
        - If a category with the same name already exists, returns the existing one
        """
        from django.utils.text import slugify
        name = payload.name.strip()
        slug = slugify(name)
        category, _ = Category.objects.get_or_create(slug=slug, defaults={'name': name})
        return category

    # ============= Blog Post Endpoints =============

    @http_get(
        "/posts/",
        response=List[BlogPostListOut],
        description="Get published blog posts with optional filtering"
    )
    def list_published_posts(self, limit: Optional[int] = None) -> List[BlogPostListOut]:
        """
        Retrieve published blog posts.
        - Public endpoint (no auth required)
        - Returns published posts only
        - Optional limit parameter
        """
        queryset = get_published_posts(limit=limit)
        return queryset

    @http_get(
        "/posts/{slug}/",
        response=BlogPostOut,
        description="Get a single blog post by slug"
    )
    def get_post_by_slug(self, slug: str) -> BlogPostOut:
        """
        Retrieve a single blog post by slug.
        - Public endpoint for published posts
        - Increments view count when accessed
        """
        blog_post = get_object_or_404(BlogPost, slug=slug, status='published')
        
        # Increment view count asynchronously
        blog_post.increment_view_count()
        
        return blog_post

    @http_post(
        "/posts/",
        response=BlogPostOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Create a new blog post"
    )
    def create_post(self, payload: BlogPostCreateIn) -> BlogPostOut:
        """
        Create a new blog post.
        - Requires authentication
        - Only editors and admins can create posts
        - Author is automatically set to the authenticated user
        """
        request = self.context.request
        user = request.user

        # Create unique slug
        slug = create_unique_slug(payload.title)

        # Create blog post
        blog_post = BlogPost.objects.create(
            title=payload.title,
            slug=slug,
            content_json=payload.content_json,
            featured_image_url=payload.featured_image_url,
            status=payload.status,
            author=user,
        )

        # Add categories
        if payload.category_ids:
            categories = Category.objects.filter(id__in=payload.category_ids)
            blog_post.categories.set(categories)

        return blog_post

    @http_put(
        "/posts/{slug}/",
        response=BlogPostOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Update a blog post"
    )
    def update_post(self, slug: str, payload: BlogPostUpdateIn) -> BlogPostOut:
        """
        Update a blog post. Accepts the post ID or slug as the path parameter.
        - Requires authentication
        - Editors can only update their own posts
        - Admins can update any post
        """
        request = self.context.request
        user = request.user
        try:
            blog_post = BlogPost.objects.get(id=int(slug))
        except (ValueError, BlogPost.DoesNotExist):
            blog_post = get_object_or_404(BlogPost, slug=slug)

        if not can_edit_post(user, blog_post):
            raise HttpError(403, "You do not have permission to edit this blog post")

        # Update fields if provided
        if payload.title:
            blog_post.title = payload.title
            blog_post.slug = create_unique_slug(payload.title)

        if payload.content_json:
            blog_post.content_json = payload.content_json

        if payload.featured_image_url is not None:
            blog_post.featured_image_url = payload.featured_image_url

        if payload.status:
            blog_post.status = payload.status

        # Update categories if provided
        if payload.category_ids is not None:
            categories = Category.objects.filter(id__in=payload.category_ids)
            blog_post.categories.set(categories)

        blog_post.save()
        return blog_post

    @http_delete(
        "/posts/{slug}/",
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Delete a blog post"
    )
    def delete_post(self, slug: str) -> dict:
        """
        Delete a blog post. Accepts the post ID or slug as the path parameter.
        - Requires authentication
        - Editors can only delete their own posts
        - Admins can delete any post
        """
        request = self.context.request
        user = request.user
        try:
            blog_post = BlogPost.objects.get(id=int(slug))
        except (ValueError, BlogPost.DoesNotExist):
            blog_post = get_object_or_404(BlogPost, slug=slug)

        if not can_delete_post(user, blog_post):
            raise HttpError(403, "You do not have permission to delete this blog post")

        blog_post.delete()
        return {"message": "Blog post deleted successfully"}

    @http_get(
        "/my-posts/",
        response=List[BlogPostListOut],
        auth=JWTAuth(),
        permissions=[IsAuthenticated],
        description="Get current user's blog posts"
    )
    def get_my_posts(self) -> List[BlogPostListOut]:
        """
        Retrieve the current user's blog posts.
        - Requires authentication
        - Returns all posts (drafts included)
        """
        request = self.context.request
        user = request.user

        posts = get_user_posts(user, include_drafts=True)
        return posts
