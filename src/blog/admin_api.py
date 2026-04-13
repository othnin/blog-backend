"""
Admin API endpoints for user management, post moderation, category CRUD, and recipe moderation.
All endpoints require admin role.
"""
import logging
import uuid
import os
from ninja.errors import HttpError
from ninja_extra import api_controller, http_get, http_post, http_put, http_patch, http_delete
from ninja_extra.permissions import IsAuthenticated
from ninja_jwt.authentication import JWTAuth
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.conf import settings
from django.db.models import Sum
from typing import List, Optional
from .permissions import IsAdmin
from .models import BlogPost, Category, Comment, Tag
from recipes.models import Recipe
from ninja import File
from ninja.files import UploadedFile
from .serializers import (
    AdminDashboardOut,
    AdminUserOut,
    AdminUserProfileOut,
    AdminUserRoleIn,
    AdminUserSuspendIn,
    AdminPostListOut,
    AdminPostStatusIn,
    AdminCategoryOut,
    AdminCategoryCreateIn,
    AdminCategoryUpdateIn,
    AdminRecipeListOut,
    AdminRecipeStatusIn,
    AdminTagOut,
    AdminTagCreateIn,
    AdminTagUpdateIn,
)

logger = logging.getLogger('blog')


def _build_user_out(user) -> AdminUserOut:
    profile_out = None
    try:
        p = user.profile
        avatar_url = None
        if p.avatar:
            avatar_url = f"{settings.MEDIA_URL}{p.avatar.name}"
        profile_out = AdminUserProfileOut(
            role=p.role,
            email_verified=p.email_verified,
            is_suspended=p.is_suspended,
            suspend_reason=p.suspend_reason or '',
            avatar_url=avatar_url,
        )
    except Exception:
        pass
    return AdminUserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        first_name=user.first_name or '',
        last_name=user.last_name or '',
        is_active=user.is_active,
        date_joined=user.date_joined,
        profile=profile_out,
    )


def _build_post_out(post) -> AdminPostListOut:
    return AdminPostListOut(
        id=post.id,
        title=post.title,
        slug=post.slug,
        status=post.status,
        author_username=post.author.username if post.author_id else '',
        category_name=post.category.name if post.category_id else None,
        view_count=post.view_count,
        like_count=post.like_count,
        created_at=post.created_at,
        published_at=post.published_at,
    )


def _build_category_out(category) -> AdminCategoryOut:
    return AdminCategoryOut(
        id=category.id,
        name=category.name,
        slug=category.slug,
        image_url=category.image_url or '',
        post_count=category.blog_posts.count(),
        created_at=category.created_at,
    )


@api_controller("/admin", tags=["Admin"], auth=JWTAuth(), permissions=[IsAuthenticated, IsAdmin])
class AdminController:
    """
    Admin-only API controller for managing users, posts, and categories.
    All endpoints require admin role.
    """

    # ── Dashboard ──────────────────────────────────────────────────────────────

    @http_get("/dashboard/", response=AdminDashboardOut)
    def get_dashboard(self) -> AdminDashboardOut:
        """Return aggregate site metrics."""
        total_likes = BlogPost.objects.aggregate(total=Sum('like_count'))['total'] or 0
        total_views = BlogPost.objects.aggregate(total=Sum('view_count'))['total'] or 0
        return AdminDashboardOut(
            total_users=User.objects.count(),
            total_posts=BlogPost.objects.count(),
            published_posts=BlogPost.objects.filter(status='published').count(),
            draft_posts=BlogPost.objects.filter(status='draft').count(),
            total_likes=total_likes,
            total_views=total_views,
            total_categories=Category.objects.count(),
            total_comments=Comment.objects.filter(is_deleted=False).count(),
        )

    # ── User Management ────────────────────────────────────────────────────────

    @http_get("/users/", response=List[AdminUserOut])
    def list_users(self, search: Optional[str] = None, role: Optional[str] = None) -> List[AdminUserOut]:
        """List all users with optional search and role filter."""
        qs = User.objects.select_related('profile').order_by('-date_joined')
        if search:
            qs = qs.filter(username__icontains=search) | User.objects.select_related('profile').filter(email__icontains=search)
            qs = qs.order_by('-date_joined')
        if role:
            qs = qs.filter(profile__role=role)
        return [_build_user_out(u) for u in qs]

    @http_get("/users/{user_id}/", response=AdminUserOut)
    def get_user(self, user_id: int) -> AdminUserOut:
        """Get a single user by ID."""
        user = get_object_or_404(User.objects.select_related('profile'), id=user_id)
        return _build_user_out(user)

    @http_patch("/users/{user_id}/role/", response=AdminUserOut)
    def update_user_role(self, user_id: int, payload: AdminUserRoleIn) -> AdminUserOut:
        """Change a user's role."""
        user = get_object_or_404(User.objects.select_related('profile'), id=user_id)
        request = self.context.request
        if user.id == request.user.id:
            raise HttpError(400, "You cannot change your own role")
        user.profile.role = payload.role
        user.profile.save(update_fields=['role'])
        return _build_user_out(user)

    @http_patch("/users/{user_id}/suspend/", response=AdminUserOut)
    def suspend_user(self, user_id: int, payload: AdminUserSuspendIn) -> AdminUserOut:
        """Suspend or unsuspend a user."""
        user = get_object_or_404(User.objects.select_related('profile'), id=user_id)
        request = self.context.request
        if user.id == request.user.id:
            raise HttpError(400, "You cannot suspend yourself")
        user.profile.is_suspended = payload.is_suspended
        user.profile.suspend_reason = payload.suspend_reason or ''
        user.profile.save(update_fields=['is_suspended', 'suspend_reason'])
        return _build_user_out(user)

    @http_delete("/users/{user_id}/")
    def delete_user(self, user_id: int) -> dict:
        """Permanently delete a user account."""
        user = get_object_or_404(User, id=user_id)
        request = self.context.request
        if user.id == request.user.id:
            raise HttpError(400, "You cannot delete your own account")
        user.delete()
        return {"message": "User deleted successfully"}

    # ── Post Moderation ────────────────────────────────────────────────────────

    @http_get("/posts/", response=List[AdminPostListOut])
    def list_all_posts(
        self,
        status: Optional[str] = None,
        search: Optional[str] = None,
        author: Optional[str] = None,
    ) -> List[AdminPostListOut]:
        """List all posts regardless of status, with optional filters."""
        qs = BlogPost.objects.select_related('author', 'category').order_by('-created_at')
        if status:
            qs = qs.filter(status=status)
        if search:
            qs = qs.filter(title__icontains=search)
        if author:
            qs = qs.filter(author__username__icontains=author)
        return [_build_post_out(p) for p in qs]

    @http_patch("/posts/{post_id}/status/", response=AdminPostListOut)
    def update_post_status(self, post_id: int, payload: AdminPostStatusIn) -> AdminPostListOut:
        """Change a post's publication status."""
        post = get_object_or_404(
            BlogPost.objects.select_related('author', 'category'), id=post_id
        )
        post.status = payload.status
        post.save(update_fields=['status', 'updated_at'])
        return _build_post_out(post)

    @http_delete("/posts/{post_id}/")
    def delete_post(self, post_id: int) -> dict:
        """Permanently delete any post."""
        post = get_object_or_404(BlogPost, id=post_id)
        post.delete()
        return {"message": "Post deleted successfully"}

    # ── Category Management ────────────────────────────────────────────────────

    @http_get("/categories/", response=List[AdminCategoryOut])
    def list_categories(self) -> List[AdminCategoryOut]:
        """List all categories with post counts."""
        return [_build_category_out(c) for c in Category.objects.prefetch_related('blog_posts').order_by('name')]

    @http_post("/categories/", response=AdminCategoryOut)
    def create_category(self, payload: AdminCategoryCreateIn) -> AdminCategoryOut:
        """Create a new category."""
        name = payload.name.strip()
        slug = slugify(name)
        if Category.objects.filter(slug=slug).exists():
            raise HttpError(400, f"Category '{name}' already exists")
        category = Category.objects.create(name=name, slug=slug)
        return _build_category_out(category)

    @http_put("/categories/{category_id}/", response=AdminCategoryOut)
    def update_category(self, category_id: int, payload: AdminCategoryUpdateIn) -> AdminCategoryOut:
        """Update a category's name."""
        category = get_object_or_404(Category, id=category_id)
        if payload.name is not None:
            name = payload.name.strip()
            new_slug = slugify(name)
            if Category.objects.filter(slug=new_slug).exclude(id=category_id).exists():
                raise HttpError(400, f"Category '{name}' already exists")
            category.name = name
            category.slug = new_slug
        category.save()
        return _build_category_out(category)

    @http_post("/categories/{category_id}/image/", response=AdminCategoryOut)
    def upload_category_image(self, category_id: int, file: UploadedFile = File(...)) -> AdminCategoryOut:
        """Upload an image for a category."""
        category = get_object_or_404(Category, id=category_id)
        allowed = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
        if file.content_type not in allowed:
            raise HttpError(400, "Only JPEG, PNG, GIF, and WebP images are allowed.")
        if file.size > 5 * 1024 * 1024:
            raise HttpError(400, "Image must be under 5 MB.")

        ext = os.path.splitext(file.name)[1].lower()
        filename = f"{uuid.uuid4().hex}{ext}"
        save_dir = settings.MEDIA_ROOT / 'category_images'
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / filename

        with open(save_path, 'wb') as f:
            for chunk in file.chunks():
                f.write(chunk)

        category.image_url = f"{settings.MEDIA_URL}category_images/{filename}"
        category.save(update_fields=['image_url', 'updated_at'])
        return _build_category_out(category)

    @http_delete("/categories/{category_id}/")
    def delete_category(self, category_id: int) -> dict:
        """Delete a category. Posts in this category will have their category cleared."""
        category = get_object_or_404(Category, id=category_id)
        category.delete()
        return {"message": "Category deleted successfully"}

    # ── Recipe Moderation ──────────────────────────────────────────────────────

    @http_get("/recipes/", response=List[AdminRecipeListOut])
    def list_all_recipes(
        self,
        status: Optional[str] = None,
        search: Optional[str] = None,
        author: Optional[str] = None,
    ) -> List[AdminRecipeListOut]:
        """List all recipes regardless of status, with optional filters."""
        qs = Recipe.objects.select_related('author').order_by('-created_at')
        if status:
            qs = qs.filter(status=status)
        if search:
            qs = qs.filter(title__icontains=search)
        if author:
            qs = qs.filter(author__username__icontains=author)
        return [
            AdminRecipeListOut(
                id=r.id,
                title=r.title,
                slug=r.slug,
                status=r.status,
                author_username=r.author.username if r.author_id else '',
                cuisine_type=r.cuisine_type or '',
                view_count=r.view_count,
                created_at=r.created_at,
                published_at=r.published_at,
            )
            for r in qs
        ]

    @http_patch("/recipes/{recipe_id}/status/", response=AdminRecipeListOut)
    def update_recipe_status(self, recipe_id: int, payload: AdminRecipeStatusIn) -> AdminRecipeListOut:
        """Change a recipe's publication status."""
        recipe = get_object_or_404(Recipe.objects.select_related('author'), id=recipe_id)
        recipe.status = payload.status
        recipe.save(update_fields=['status', 'updated_at'])
        logger.info("Admin changed recipe %d status to %s", recipe_id, payload.status)
        return AdminRecipeListOut(
            id=recipe.id,
            title=recipe.title,
            slug=recipe.slug,
            status=recipe.status,
            author_username=recipe.author.username if recipe.author_id else '',
            cuisine_type=recipe.cuisine_type or '',
            view_count=recipe.view_count,
            created_at=recipe.created_at,
            published_at=recipe.published_at,
        )

    @http_delete("/recipes/{recipe_id}/")
    def delete_recipe(self, recipe_id: int) -> dict:
        """Permanently delete any recipe."""
        recipe = get_object_or_404(Recipe, id=recipe_id)
        logger.info("Admin deleted recipe %d (%s)", recipe_id, recipe.title)
        recipe.delete()
        return {"message": "Recipe deleted successfully"}

    # ── Tag Management ─────────────────────────────────────────────────────────

    @http_get("/tags/", response=List[AdminTagOut])
    def list_tags(self) -> List[AdminTagOut]:
        """List all tags with post counts."""
        tags = Tag.objects.prefetch_related('blog_posts').order_by('name')
        return [
            AdminTagOut(
                id=t.id,
                name=t.name,
                slug=t.slug,
                meta_description=t.meta_description or '',
                post_count=t.blog_posts.count(),
                created_at=t.created_at,
            )
            for t in tags
        ]

    @http_post("/tags/", response=AdminTagOut)
    def create_tag(self, payload: AdminTagCreateIn) -> AdminTagOut:
        """Create a new tag."""
        name = payload.name.strip()
        slug = slugify(name)
        if Tag.objects.filter(slug=slug).exists():
            raise HttpError(400, f"Tag '{name}' already exists")
        tag = Tag.objects.create(
            name=name,
            slug=slug,
            meta_description=payload.meta_description or '',
        )
        return AdminTagOut(
            id=tag.id, name=tag.name, slug=tag.slug,
            meta_description=tag.meta_description, post_count=0,
            created_at=tag.created_at,
        )

    @http_put("/tags/{tag_id}/", response=AdminTagOut)
    def update_tag(self, tag_id: int, payload: AdminTagUpdateIn) -> AdminTagOut:
        """Update a tag's name and/or meta description."""
        tag = get_object_or_404(Tag, id=tag_id)
        if payload.name is not None:
            name = payload.name.strip()
            new_slug = slugify(name)
            if Tag.objects.filter(slug=new_slug).exclude(id=tag_id).exists():
                raise HttpError(400, f"Tag '{name}' already exists")
            tag.name = name
            tag.slug = new_slug
        if payload.meta_description is not None:
            tag.meta_description = payload.meta_description
        tag.save()
        return AdminTagOut(
            id=tag.id, name=tag.name, slug=tag.slug,
            meta_description=tag.meta_description,
            post_count=tag.blog_posts.count(),
            created_at=tag.created_at,
        )

    @http_delete("/tags/{tag_id}/")
    def delete_tag_admin(self, tag_id: int) -> dict:
        """Delete a tag. Posts with this tag will have it removed."""
        tag = get_object_or_404(Tag, id=tag_id)
        tag.delete()
        return {"message": "Tag deleted successfully"}
