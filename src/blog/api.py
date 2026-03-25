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
from django.conf import settings
from typing import List, Optional
from .models import BlogPost, Category, Comment
from ninja import File
from ninja.files import UploadedFile
import uuid, os
from .serializers import (
    BlogPostCreateIn,
    BlogPostUpdateIn,
    BlogPostOut,
    BlogPostListOut,
    CategoryOut,
    CategoryCreateIn,
    CommentIn,
    CommentUpdateIn,
    CommentOut,
    LikeOut,
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
    def list_published_posts(self, limit: Optional[int] = None, category: Optional[str] = None, search: Optional[str] = None) -> List[BlogPostListOut]:
        """
        Retrieve published blog posts.
        - Public endpoint (no auth required)
        - Returns published posts only
        - Optional limit parameter
        - Optional category slug to filter by
        - Optional search query to filter by title or author
        """
        queryset = get_published_posts(limit=limit, category=category, search=search)
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
        blog_post = get_object_or_404(
            BlogPost.objects.select_related('author', 'author__profile').prefetch_related('categories'),
            slug=slug, status='published'
        )
        
        # Increment view count asynchronously
        blog_post.increment_view_count()

        return blog_post

    @http_post(
        "/posts/{slug}/like/",
        response=LikeOut,
        description="Like a blog post"
    )
    def like_post(self, slug: str) -> LikeOut:
        """Increment the like count for a published blog post."""
        blog_post = get_object_or_404(BlogPost, slug=slug, status='published')
        blog_post.increment_like_count()
        return LikeOut(like_count=blog_post.like_count)

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
        qs = BlogPost.objects.select_related('author', 'author__profile').prefetch_related('categories')
        try:
            blog_post = qs.get(id=int(slug))
        except (ValueError, BlogPost.DoesNotExist):
            blog_post = get_object_or_404(qs, slug=slug)

        if not can_edit_post(user, blog_post):
            raise HttpError(403, "You do not have permission to edit this blog post")

        # Update fields if provided
        if payload.title:
            blog_post.title = payload.title
            blog_post.slug = create_unique_slug(payload.title)

        if payload.content_json:
            blog_post.content_json = payload.content_json

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

    @http_post(
        "/upload-image/",
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Upload an image for use in blog posts"
    )
    def upload_image(self, request, file: UploadedFile = File(...)):
        """
        Upload an image file and return its URL.
        - Requires editor or admin role
        - Accepts JPEG, PNG, GIF, WebP
        - Max size: 10 MB
        """
        allowed = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
        if file.content_type not in allowed:
            raise HttpError(400, "Only JPEG, PNG, GIF, and WebP images are allowed.")
        if file.size > 10 * 1024 * 1024:
            raise HttpError(400, "Image must be under 10 MB.")

        ext = os.path.splitext(file.name)[1].lower()
        filename = f"{uuid.uuid4().hex}{ext}"
        save_path = settings.MEDIA_ROOT / 'blog_images' / filename
        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, 'wb') as f:
            for chunk in file.chunks():
                f.write(chunk)

        return {"url": f"{settings.MEDIA_URL}blog_images/{filename}"}


# ─── Comment helpers ──────────────────────────────────────────────────────────

def _author_dict(user):
    """Build a comment author dict including avatar_url."""
    try:
        avatar_url = f"{settings.MEDIA_URL}{user.profile.avatar.name}" if user.profile.avatar else None
    except Exception:
        avatar_url = None
    return {'id': user.id, 'username': user.username, 'avatar_url': avatar_url}


def _build_comment_tree(post):
    """
    Fetch all comments for a post in a single query and build a nested tree.
    Returns a list of dicts matching the CommentOut schema.
    """
    all_comments = (
        Comment.objects
        .filter(post=post)
        .select_related('author', 'author__profile')
        .order_by('created_at')
    )
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


# ─── Comment Controller ───────────────────────────────────────────────────────

@api_controller("/blog", tags=["Comments"])
class CommentController:
    """API controller for blog post comments."""

    @http_get(
        "/posts/{post_id}/comments/",
        response=List[CommentOut],
        description="Get all comments for a blog post as a nested tree"
    )
    def list_comments(self, post_id: int) -> List[CommentOut]:
        """Public endpoint — returns all comments as a nested tree."""
        post = get_object_or_404(BlogPost, id=post_id, status='published')
        return _build_comment_tree(post)

    @http_post(
        "/posts/{post_id}/comments/",
        response=CommentOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated],
        description="Post a comment on a blog post"
    )
    def create_comment(self, post_id: int, payload: CommentIn) -> CommentOut:
        """Create a top-level comment or a reply. Any authenticated user can comment."""
        post = get_object_or_404(BlogPost, id=post_id, status='published')
        parent = None
        if payload.parent_id is not None:
            parent = get_object_or_404(Comment, id=payload.parent_id, post=post)
        comment = Comment.objects.create(
            post=post,
            author=self.context.request.user,
            parent=parent,
            content_json=payload.content_json,
        )
        comment.refresh_from_db()
        return _comment_to_dict(comment)

    @http_put(
        "/comments/{comment_id}/",
        response=CommentOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated],
        description="Edit a comment (own comment only)"
    )
    def update_comment(self, comment_id: int, payload: CommentUpdateIn) -> CommentOut:
        """Edit own comment content. Only the comment's author may edit it."""
        comment = get_object_or_404(Comment, id=comment_id, is_deleted=False)
        user = self.context.request.user
        if comment.author_id != user.id:
            raise HttpError(403, "You can only edit your own comments")
        comment.content_json = payload.content_json
        comment.save(update_fields=['content_json', 'updated_at'])
        return _comment_to_dict(comment)

    @http_delete(
        "/comments/{comment_id}/",
        auth=JWTAuth(),
        permissions=[IsAuthenticated],
        description="Delete a comment (own comment, or any comment for admins)"
    )
    def delete_comment(self, comment_id: int) -> dict:
        """
        Soft-delete a comment. The row is kept so child replies remain intact.
        Author content is cleared; the deleted tombstone is shown in the UI.
        """
        comment = get_object_or_404(Comment, id=comment_id, is_deleted=False)
        user = self.context.request.user
        is_admin = hasattr(user, 'profile') and user.profile.role == 'admin'
        if not is_admin and comment.author_id != user.id:
            raise HttpError(403, "You can only delete your own comments")
        comment.is_deleted = True
        comment.content_json = ''
        comment.save(update_fields=['is_deleted', 'content_json', 'updated_at'])
        return {"message": "Comment deleted"}
