"""
Location API endpoints using Django Ninja Extra.

Django Ninja Extra registers URL patterns such that parameterised paths
(/{id}/) take priority over static paths (/geocode/). To keep static paths
reachable, endpoints are split across controllers registered in a specific
order (mirrors ``recipes/api.py``):

  1. LocationController        — static + multi-segment paths (register FIRST)
  2. LocationDetailController  — single-segment /{id}/ paths (register SECOND)
  3. RestaurantController      — static + no-segment paths
  4. RestaurantDetailController— single-segment /{id}/ paths
"""
import io
import uuid

from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404
from ninja import File
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja_extra import api_controller, http_get, http_post, http_put, http_delete
from ninja_extra.permissions import IsAuthenticated
from typing import List, Optional

from helpers.api_auth import SuspendAwareJWTAuth as JWTAuth
from helpers.rate_limit import check_rate_limit
from blog.models import Comment
from blog.permissions import IsEditorOrAdmin
from blog.serializers import CommentIn, CommentUpdateIn, CommentOut
from blog.utils import build_comment_tree, _comment_to_dict

from .models import Location, RestaurantLocation
from .serializers import (
    LocationIn,
    LocationOut,
    RestaurantIn,
    RestaurantUpdateIn,
    RestaurantOut,
    GeocodeIn,
    GeocodeOut,
)
from .services import LocationService, GeocodingError

ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _location_queryset():
    return Location.objects.select_related('created_by', 'created_by__profile')


def _restaurant_queryset():
    return (
        Location.objects.filter(type='restaurant')
        .select_related('restaurant', 'created_by', 'created_by__profile')
    )


def _save_picture(request, location, file):
    """Validate, resize, and store an uploaded location picture."""
    from PIL import Image

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HttpError(400, "Only JPEG, PNG, and WebP images are allowed.")
    if file.size > MAX_IMAGE_BYTES:
        raise HttpError(400, "Image must be under 10 MB.")

    try:
        img = Image.open(file)
        img = img.convert('RGB')
        img.thumbnail((1200, 1200), Image.LANCZOS)
    except Exception:
        raise HttpError(400, "Could not read the uploaded image.")

    filename = f"{uuid.uuid4().hex}.jpg"
    filepath = f'locations/{filename}'
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=85)
    buffer.seek(0)

    try:
        default_storage.save(filepath, buffer)
    except Exception as exc:
        from blog.security_utils import log_security_event
        log_security_event(
            'storage_failed',
            request=request,
            user=request.user,
            message=f"Failed to upload location picture: {exc}",
            details={'filename': filename},
            severity='warning',
        )
        raise HttpError(500, "Failed to upload picture. Please try again.")

    old = location.picture.name if location.picture else None
    location.picture = filepath
    location.save(update_fields=['picture', 'updated_at'])

    if old and old != filepath and default_storage.exists(old):
        try:
            default_storage.delete(old)
        except Exception:
            pass

    return location


# ─── Controller 1: static + multi-segment paths (register FIRST) ─────────────

@api_controller("/locations", tags=["Locations"])
class LocationController:
    """Generic location list/create, geocoding, comments, and picture upload."""

    @http_get(
        "/",
        response=List[LocationOut],
        description="List published locations, optionally filtered by type",
    )
    def list_locations(self, type: Optional[str] = None) -> List[LocationOut]:
        qs = _location_queryset().filter(is_published=True)
        if type:
            qs = qs.filter(type=type)
        return list(qs)

    @http_get(
        "/manage/",
        response=List[LocationOut],
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="List all locations including unpublished (admin/editor only)",
    )
    def list_manage_locations(self, type: Optional[str] = None) -> List[LocationOut]:
        qs = _location_queryset()
        if type:
            qs = qs.filter(type=type)
        return list(qs)

    @http_post(
        "/",
        response=LocationOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Create a generic location (admin/editor only)",
    )
    def create_location(self, payload: LocationIn) -> LocationOut:
        location = Location.objects.create(
            type=payload.type,
            name=payload.name,
            description=payload.description,
            address=payload.address,
            phone=payload.phone,
            website=payload.website,
            latitude=payload.latitude,
            longitude=payload.longitude,
            is_published=payload.is_published,
            created_by=self.context.request.user,
        )
        return location

    @http_post(
        "/geocode/",
        response=GeocodeOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Resolve an address to latitude/longitude (admin/editor only)",
    )
    def geocode(self, payload: GeocodeIn) -> GeocodeOut:
        check_rate_limit(self.context.request, key="geocode", max_requests=60, period=3600)
        try:
            lat, lng = LocationService.geocode_address(payload.address)
        except GeocodingError as exc:
            raise HttpError(400, str(exc))
        return GeocodeOut(latitude=lat, longitude=lng)

    @http_post(
        "/{location_id}/picture/",
        response=LocationOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Upload or replace a location picture (admin/editor only)",
    )
    def upload_picture(self, location_id: int, file: UploadedFile = File(...)) -> LocationOut:
        location = get_object_or_404(_location_queryset(), id=location_id)
        return _save_picture(self.context.request, location, file)

    # ── Comments ────────────────────────────────────────────────────────────

    @http_get(
        "/{location_id}/comments/",
        response=List[CommentOut],
        description="Get all comments for a location as a nested tree",
    )
    def list_comments(self, location_id: int) -> List[CommentOut]:
        location = get_object_or_404(Location, id=location_id, is_published=True)
        return build_comment_tree(Comment.objects.filter(location=location))

    @http_post(
        "/{location_id}/comments/",
        response=CommentOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated],
        description="Post a comment on a location",
    )
    def create_comment(self, location_id: int, payload: CommentIn) -> CommentOut:
        check_rate_limit(
            self.context.request,
            key="location_comment",
            max_requests=5,
            period=3600,
            identifier=str(self.context.request.user.id),
        )
        location = get_object_or_404(Location, id=location_id, is_published=True)
        parent = None
        if payload.parent_id is not None:
            parent = get_object_or_404(Comment, id=payload.parent_id, location=location)
        comment = Comment.objects.create(
            location=location,
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
        description="Edit a location comment (own comment only)",
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
        description="Delete a location comment (own comment, or any for admins)",
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


# ─── Controller 2: single-segment /{id}/ paths (register SECOND) ─────────────

@api_controller("/locations", tags=["Locations"])
class LocationDetailController:
    """Generic location detail/update/delete by id."""

    @http_get("/{location_id}/", response=LocationOut, description="Get a single location")
    def get_location(self, location_id: int) -> LocationOut:
        return get_object_or_404(_location_queryset(), id=location_id)

    @http_put(
        "/{location_id}/",
        response=LocationOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Update a generic location (admin/editor only)",
    )
    def update_location(self, location_id: int, payload: LocationIn) -> LocationOut:
        location = get_object_or_404(_location_queryset(), id=location_id)
        location.type = payload.type
        location.name = payload.name
        location.description = payload.description
        location.address = payload.address
        location.phone = payload.phone
        location.website = payload.website
        location.latitude = payload.latitude
        location.longitude = payload.longitude
        location.is_published = payload.is_published
        location.save()
        return location

    @http_delete(
        "/{location_id}/",
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Delete a location (admin/editor only)",
    )
    def delete_location(self, location_id: int) -> dict:
        location = get_object_or_404(Location, id=location_id)
        location.delete()
        return {"message": "Location deleted successfully"}


# ─── Controller 3: restaurant static + no-segment paths (register THIRD) ─────

@api_controller("/restaurants", tags=["Locations"])
class RestaurantController:
    """Restaurant list/create (public read, admin/editor write)."""

    @http_get(
        "/",
        response=List[RestaurantOut],
        description="List published restaurants with optional filters",
    )
    def list_restaurants(
        self,
        rating: Optional[str] = None,
        cuisine: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[RestaurantOut]:
        qs = _restaurant_queryset().filter(is_published=True)
        if rating:
            qs = qs.filter(restaurant__michelin_rating=rating)
        if cuisine:
            qs = qs.filter(restaurant__cuisine_type__icontains=cuisine)
        if search:
            qs = qs.filter(name__icontains=search)
        return list(qs)

    @http_post(
        "/",
        response=RestaurantOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Create a restaurant (admin/editor only)",
    )
    def create_restaurant(self, payload: RestaurantIn) -> RestaurantOut:
        location = Location.objects.create(
            type='restaurant',
            name=payload.name,
            description=payload.description,
            address=payload.address,
            phone=payload.phone,
            website=payload.website,
            latitude=payload.latitude,
            longitude=payload.longitude,
            is_published=payload.is_published,
            created_by=self.context.request.user,
        )
        RestaurantLocation.objects.create(
            location=location,
            michelin_rating=payload.michelin_rating,
            cuisine_type=payload.cuisine_type,
            reservations_link=payload.reservations_link,
            review_link=payload.review_link,
        )
        return get_object_or_404(_restaurant_queryset(), id=location.id)


# ─── Controller 4: restaurant /{id}/ paths (register FOURTH) ─────────────────

@api_controller("/restaurants", tags=["Locations"])
class RestaurantDetailController:
    """Restaurant detail/update/delete by id."""

    @http_get("/{location_id}/", response=RestaurantOut, description="Get a single restaurant")
    def get_restaurant(self, location_id: int) -> RestaurantOut:
        return get_object_or_404(_restaurant_queryset(), id=location_id)

    @http_put(
        "/{location_id}/",
        response=RestaurantOut,
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Update a restaurant (admin/editor only)",
    )
    def update_restaurant(self, location_id: int, payload: RestaurantUpdateIn) -> RestaurantOut:
        location = get_object_or_404(_restaurant_queryset(), id=location_id)
        restaurant = location.restaurant

        base_fields = [
            'name', 'description', 'address', 'phone', 'website',
            'latitude', 'longitude', 'is_published',
        ]
        for field in base_fields:
            value = getattr(payload, field)
            if value is not None:
                setattr(location, field, value)

        detail_fields = [
            'michelin_rating', 'cuisine_type', 'reservations_link', 'review_link',
        ]
        for field in detail_fields:
            value = getattr(payload, field)
            if value is not None:
                setattr(restaurant, field, value)

        location.save()
        restaurant.save()
        return get_object_or_404(_restaurant_queryset(), id=location_id)

    @http_delete(
        "/{location_id}/",
        auth=JWTAuth(),
        permissions=[IsAuthenticated, IsEditorOrAdmin],
        description="Delete a restaurant (admin/editor only)",
    )
    def delete_restaurant(self, location_id: int) -> dict:
        location = get_object_or_404(_restaurant_queryset(), id=location_id)
        location.delete()
        return {"message": "Restaurant deleted successfully"}
