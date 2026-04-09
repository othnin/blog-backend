"""
Recipe API endpoints using Django Ninja Extra.

Django Ninja Extra registers URL patterns in an order where parameterised
paths (/{param}/) take priority over static paths (/dietary-labels/). To work
around this, the recipe endpoints are split into two controllers that are
registered in a specific order:

  1. RecipeController  — all static-prefix paths registered first
  2. RecipeDetailController — single-segment parameterised paths registered second

This ensures Django's URL resolver tries static paths before dynamic ones.
"""
from ninja.errors import HttpError
from ninja_extra import api_controller, http_get, http_post, http_put, http_delete
from ninja_extra.permissions import IsAuthenticated
from ninja_jwt.authentication import JWTAuth
from blog.permissions import IsEditorOrAdmin
from blog.models import Comment, Tag
from blog.utils import build_comment_tree, _comment_to_dict
from helpers.rate_limit import check_rate_limit
from blog.serializers import CommentIn, CommentUpdateIn, CommentOut
from django.shortcuts import get_object_or_404
from django.db.models import Avg, Count
from typing import List, Optional

from .models import Recipe, RecipeIngredient, RecipeInstruction, RecipeRating, DietaryLabel
from .serializers import (
    RecipeCreateIn,
    RecipeUpdateIn,
    RecipeListOut,
    RecipeDetailOut,
    RecipeRatingIn,
    RecipeRatingOut,
    DietaryLabelOut,
    DietaryLabelCreateIn,
)
from .utils import create_unique_recipe_slug, can_edit_recipe, get_published_recipes


def _recipe_with_ratings(recipe):
    """Annotate a single Recipe instance with avg_rating and rating_count."""
    return (
        Recipe.objects.filter(pk=recipe.pk)
        .annotate(
            avg_rating=Avg('ratings__score'),
            rating_count=Count('ratings', distinct=True),
        )
        .prefetch_related('tags', 'dietary_labels', 'ingredients', 'instructions')
        .select_related('author', 'author__profile')
        .first()
    )


# ─── Controller 1: static-prefix paths (register FIRST) ──────────────────────

@api_controller("/recipes", tags=["Recipes"])
class RecipeController:
    """
    Recipe list/create, dietary labels, my-recipes, ratings, comments.

    Contains ONLY paths that start with a static segment or no segment (/ and
    /static-prefix/…). Single-segment dynamic paths (/{slug}/ and /{id}/) live
    in RecipeDetailController which must be registered AFTER this one.
    """

    # ── Dietary Labels ────────────────────────────────────────────────────────

    @http_get(
        "/dietary-labels/",
        response=List[DietaryLabelOut],
        description="List all dietary labels",
    )
    def list_dietary_labels(self) -> List[DietaryLabelOut]:
        return list(DietaryLabel.objects.all())

    @http_post(
        "/dietary-labels/",
        response=DietaryLabelOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Create a dietary label",
    )
    def create_dietary_label(self, payload: DietaryLabelCreateIn) -> DietaryLabelOut:
        from django.utils.text import slugify
        name = payload.name.strip()
        label, _ = DietaryLabel.objects.get_or_create(
            slug=slugify(name), defaults={'name': name}
        )
        return label

    # ── My Recipes ────────────────────────────────────────────────────────────

    @http_get(
        "/my-recipes/",
        response=List[RecipeDetailOut],
        auth=JWTAuth(),
        permissions=[IsAuthenticated],
        description="Get the current user's recipes (all statuses)",
    )
    def get_my_recipes(self) -> List[RecipeDetailOut]:
        user = self.context.request.user
        return list(
            Recipe.objects.filter(author=user)
            .select_related('author', 'author__profile')
            .prefetch_related('tags', 'dietary_labels', 'ingredients', 'instructions')
            .annotate(
                avg_rating=Avg('ratings__score'),
                rating_count=Count('ratings', distinct=True),
            )
        )

    @http_get(
        "/my-recipes/{recipe_id}/",
        response=RecipeDetailOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated],
        description="Get a single recipe owned by the current user",
    )
    def get_my_recipe(self, recipe_id: int) -> RecipeDetailOut:
        user = self.context.request.user
        recipe = get_object_or_404(Recipe, id=recipe_id)
        if not can_edit_recipe(user, recipe):
            raise HttpError(403, "You do not have permission to view this recipe")
        return _recipe_with_ratings(recipe)

    # ── List / Create ─────────────────────────────────────────────────────────

    @http_get(
        "/",
        response=List[RecipeListOut],
        description="List published recipes with optional filters",
    )
    def list_recipes(
        self,
        cuisine: Optional[str] = None,
        course: Optional[str] = None,
        dietary: Optional[str] = None,
        tags: Optional[str] = None,
        search: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[RecipeListOut]:
        return list(get_published_recipes(cuisine, course, dietary, tags, search, limit))

    @http_post(
        "/",
        response=RecipeDetailOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Create a new recipe",
    )
    def create_recipe(self, payload: RecipeCreateIn) -> RecipeDetailOut:
        user = self.context.request.user
        slug = create_unique_recipe_slug(payload.title)

        recipe = Recipe.objects.create(
            title=payload.title,
            slug=slug,
            author=user,
            description=payload.description,
            images=payload.images,
            notes=payload.notes,
            prep_time_minutes=payload.prep_time_minutes,
            cook_time_minutes=payload.cook_time_minutes,
            yield_amount=payload.yield_amount,
            yield_unit=payload.yield_unit,
            cuisine_type=payload.cuisine_type,
            course=payload.course,
            status=payload.status,
            comments_disabled=payload.comments_disabled,
        )

        if payload.dietary_label_ids:
            recipe.dietary_labels.set(DietaryLabel.objects.filter(id__in=payload.dietary_label_ids))
        if payload.tag_ids:
            recipe.tags.set(Tag.objects.filter(id__in=payload.tag_ids))

        if payload.ingredients:
            RecipeIngredient.objects.bulk_create([
                RecipeIngredient(recipe=recipe, **ing.model_dump())
                for ing in payload.ingredients
            ])

        if payload.instructions:
            RecipeInstruction.objects.bulk_create([
                RecipeInstruction(recipe=recipe, **inst.model_dump())
                for inst in payload.instructions
            ])

        return _recipe_with_ratings(recipe)

    # ── Ratings (multi-segment, no static-path conflict) ──────────────────────

    @http_post(
        "/{recipe_id}/rate/",
        response=RecipeRatingOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated],
        description="Submit or update a star rating (1–5) for a recipe",
    )
    def rate_recipe(self, recipe_id: int, payload: RecipeRatingIn) -> RecipeRatingOut:
        recipe = get_object_or_404(Recipe, id=recipe_id, status='published')
        user = self.context.request.user
        RecipeRating.objects.update_or_create(
            recipe=recipe, user=user, defaults={'score': payload.score}
        )
        agg = Recipe.objects.filter(pk=recipe_id).annotate(
            avg_rating=Avg('ratings__score'),
            rating_count=Count('ratings', distinct=True),
        ).values('avg_rating', 'rating_count').first()
        return RecipeRatingOut(
            avg_rating=agg['avg_rating'],
            rating_count=agg['rating_count'],
            user_score=payload.score,
        )

    @http_get(
        "/{recipe_id}/rating/",
        response=RecipeRatingOut,
        description="Get rating summary for a recipe",
    )
    def get_rating(self, recipe_id: int) -> RecipeRatingOut:
        recipe = get_object_or_404(Recipe, id=recipe_id)
        agg = Recipe.objects.filter(pk=recipe_id).annotate(
            avg_rating=Avg('ratings__score'),
            rating_count=Count('ratings', distinct=True),
        ).values('avg_rating', 'rating_count').first()
        user_score = None
        request = self.context.request
        if request.user.is_authenticated:
            try:
                rating = RecipeRating.objects.get(recipe=recipe, user=request.user)
                user_score = rating.score
            except RecipeRating.DoesNotExist:
                pass
        return RecipeRatingOut(
            avg_rating=agg['avg_rating'],
            rating_count=agg['rating_count'],
            user_score=user_score,
        )

    # ── Comments (multi-segment, no static-path conflict) ────────────────────

    @http_get(
        "/{recipe_id}/comments/",
        response=List[CommentOut],
        description="Get all comments for a recipe as a nested tree",
    )
    def list_comments(self, recipe_id: int) -> List[CommentOut]:
        recipe = get_object_or_404(Recipe, id=recipe_id)
        return build_comment_tree(Comment.objects.filter(recipe=recipe))

    @http_post(
        "/{recipe_id}/comments/",
        response=CommentOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated],
        description="Post a comment on a recipe",
    )
    def create_comment(self, recipe_id: int, payload: CommentIn) -> CommentOut:
        # Rate limit: 5 comments per hour per user
        check_rate_limit(
            self.context.request,
            key="recipe_comment",
            max_requests=5,
            period=3600,
            identifier=str(self.context.request.user.id),
        )
        recipe = get_object_or_404(Recipe, id=recipe_id)
        if recipe.status != 'published':
            raise HttpError(403, "Comments are only allowed on published recipes")
        if recipe.comments_disabled:
            raise HttpError(403, "Comments are disabled on this recipe")
        parent = None
        if payload.parent_id is not None:
            parent = get_object_or_404(Comment, id=payload.parent_id, recipe=recipe)
        comment = Comment.objects.create(
            recipe=recipe,
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
        description="Edit a recipe comment (own comment only)",
    )
    def update_comment(self, comment_id: int, payload: CommentUpdateIn) -> CommentOut:
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
        description="Delete a recipe comment (own comment, or any for admins)",
    )
    def delete_comment(self, comment_id: int) -> dict:
        comment = get_object_or_404(Comment, id=comment_id, is_deleted=False)
        user = self.context.request.user
        is_admin = hasattr(user, 'profile') and user.profile.role == 'admin'
        if not is_admin and comment.author_id != user.id:
            raise HttpError(403, "You can only delete your own comments")
        comment.is_deleted = True
        comment.content_json = ''
        comment.save(update_fields=['is_deleted', 'content_json', 'updated_at'])
        return {"message": "Comment deleted"}


# ─── Controller 2: single-segment dynamic paths (register SECOND) ─────────────

@api_controller("/recipes", tags=["Recipes"])
class RecipeDetailController:
    """
    Recipe detail/update/delete by slug or ID.

    Contains ONLY single-segment parameterised paths (/{slug}/ and /{id}/).
    Must be registered AFTER RecipeController so Django's URL resolver tries
    the static paths from RecipeController first.
    """

    @http_get(
        "/{slug}/",
        response=RecipeDetailOut,
        description="Get a single recipe by slug",
    )
    def get_recipe(self, slug: str) -> RecipeDetailOut:
        recipe = get_object_or_404(Recipe, slug=slug, status='published')
        recipe.increment_view_count()
        return _recipe_with_ratings(recipe)

    @http_put(
        "/{slug}/",
        response=RecipeDetailOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Update a recipe (accepts slug or integer ID)",
    )
    def update_recipe(self, slug: str, payload: RecipeUpdateIn) -> RecipeDetailOut:
        user = self.context.request.user
        qs = Recipe.objects.select_related('author', 'author__profile')
        try:
            recipe = qs.get(id=int(slug))
        except (ValueError, Recipe.DoesNotExist):
            recipe = get_object_or_404(qs, slug=slug)
        if not can_edit_recipe(user, recipe):
            raise HttpError(403, "You do not have permission to edit this recipe")

        if payload.title is not None:
            recipe.title = payload.title
            recipe.slug = create_unique_recipe_slug(payload.title)
        if payload.description is not None:
            recipe.description = payload.description
        if payload.images is not None:
            recipe.images = payload.images
        if payload.notes is not None:
            recipe.notes = payload.notes
        if payload.prep_time_minutes is not None:
            recipe.prep_time_minutes = payload.prep_time_minutes
        if payload.cook_time_minutes is not None:
            recipe.cook_time_minutes = payload.cook_time_minutes
        if payload.yield_amount is not None:
            recipe.yield_amount = payload.yield_amount
        if payload.yield_unit is not None:
            recipe.yield_unit = payload.yield_unit
        if payload.cuisine_type is not None:
            recipe.cuisine_type = payload.cuisine_type
        if payload.course is not None:
            recipe.course = payload.course
        if payload.status is not None:
            recipe.status = payload.status
        if payload.comments_disabled is not None:
            recipe.comments_disabled = payload.comments_disabled

        recipe.save()

        if payload.dietary_label_ids is not None:
            recipe.dietary_labels.set(DietaryLabel.objects.filter(id__in=payload.dietary_label_ids))
        if payload.tag_ids is not None:
            recipe.tags.set(Tag.objects.filter(id__in=payload.tag_ids))

        if payload.ingredients is not None:
            recipe.ingredients.all().delete()
            RecipeIngredient.objects.bulk_create([
                RecipeIngredient(recipe=recipe, **ing.model_dump())
                for ing in payload.ingredients
            ])

        if payload.instructions is not None:
            recipe.instructions.all().delete()
            RecipeInstruction.objects.bulk_create([
                RecipeInstruction(recipe=recipe, **inst.model_dump())
                for inst in payload.instructions
            ])

        return _recipe_with_ratings(recipe)

    @http_delete(
        "/{slug}/",
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Delete a recipe (accepts slug or integer ID)",
    )
    def delete_recipe(self, slug: str) -> dict:
        user = self.context.request.user
        try:
            recipe = Recipe.objects.get(id=int(slug))
        except (ValueError, Recipe.DoesNotExist):
            recipe = get_object_or_404(Recipe, slug=slug)
        if not can_edit_recipe(user, recipe):
            raise HttpError(403, "You do not have permission to delete this recipe")
        recipe.delete()
        return {"message": "Recipe deleted successfully"}
