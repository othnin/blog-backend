"""
Serializers for location models using Pydantic and Django Ninja.
"""
from decimal import Decimal
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from helpers.storage import get_presigned_url_or_none


class LocationAuthorOut(BaseModel):
    """Author info embedded in location responses — includes resolved avatar_url."""
    id: int
    username: str
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def resolve_avatar(cls, data):
        if hasattr(data, 'id') and hasattr(data, 'username'):  # ORM User object
            try:
                avatar_url = (
                    get_presigned_url_or_none(data.profile.avatar.name)
                    if data.profile.avatar else None
                )
            except Exception:
                avatar_url = None
            return {'id': data.id, 'username': data.username, 'avatar_url': avatar_url}
        return data


def _resolve_picture_url(location) -> Optional[str]:
    try:
        picture = location.picture
        return get_presigned_url_or_none(picture.name) if picture else None
    except Exception:
        return None


class LocationOut(BaseModel):
    """Output serializer for the generic Location base."""
    id: int
    type: str
    name: str
    description: str = ''
    address: str
    phone: str = ''
    website: Optional[str] = None
    picture_url: Optional[str] = None
    latitude: Decimal
    longitude: Decimal
    is_published: bool
    created_by: Optional[LocationAuthorOut] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def resolve_picture(cls, data):
        if hasattr(data, 'id') and hasattr(data, 'type'):  # ORM Location object
            return {
                'id': data.id,
                'type': data.type,
                'name': data.name,
                'description': data.description,
                'address': data.address,
                'phone': data.phone,
                'website': data.website,
                'picture_url': _resolve_picture_url(data),
                'latitude': data.latitude,
                'longitude': data.longitude,
                'is_published': data.is_published,
                'created_by': data.created_by,
                'created_at': data.created_at,
                'updated_at': data.updated_at,
            }
        return data


class RestaurantOut(BaseModel):
    """Output serializer for a restaurant: base location fields + restaurant detail."""
    id: int
    type: str
    name: str
    description: str = ''
    address: str
    phone: str = ''
    website: Optional[str] = None
    picture_url: Optional[str] = None
    latitude: Decimal
    longitude: Decimal
    is_published: bool
    created_by: Optional[LocationAuthorOut] = None
    created_at: datetime
    updated_at: datetime
    michelin_rating: str = 'none'
    cuisine_type: str = ''
    reservations_link: Optional[str] = None
    review_link: Optional[str] = None

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def resolve_restaurant(cls, data):
        if hasattr(data, 'id') and hasattr(data, 'type'):  # ORM Location object
            restaurant = data.restaurant
            return {
                'id': data.id,
                'type': data.type,
                'name': data.name,
                'description': data.description,
                'address': data.address,
                'phone': data.phone,
                'website': data.website,
                'picture_url': _resolve_picture_url(data),
                'latitude': data.latitude,
                'longitude': data.longitude,
                'is_published': data.is_published,
                'created_by': data.created_by,
                'created_at': data.created_at,
                'updated_at': data.updated_at,
                'michelin_rating': restaurant.michelin_rating,
                'cuisine_type': restaurant.cuisine_type,
                'reservations_link': restaurant.reservations_link,
                'review_link': restaurant.review_link,
            }
        return data


class LocationIn(BaseModel):
    """Input serializer for creating/updating a generic location."""
    type: str = Field(default='restaurant')
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ''
    address: str = Field(..., min_length=1, max_length=500)
    phone: str = Field(default='', max_length=20)
    website: Optional[str] = Field(default=None, max_length=200)
    latitude: Decimal
    longitude: Decimal
    is_published: bool = True


class RestaurantIn(LocationIn):
    """Input serializer for creating/updating a restaurant."""
    michelin_rating: str = 'none'
    cuisine_type: str = Field(default='', max_length=100)
    reservations_link: Optional[str] = Field(default=None, max_length=200)
    review_link: Optional[str] = Field(default=None, max_length=200)


class RestaurantUpdateIn(BaseModel):
    """Partial update for a restaurant. All fields optional."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    address: Optional[str] = Field(default=None, min_length=1, max_length=500)
    phone: Optional[str] = Field(default=None, max_length=20)
    website: Optional[str] = Field(default=None, max_length=200)
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    is_published: Optional[bool] = None
    michelin_rating: Optional[str] = None
    cuisine_type: Optional[str] = Field(default=None, max_length=100)
    reservations_link: Optional[str] = Field(default=None, max_length=200)
    review_link: Optional[str] = Field(default=None, max_length=200)


class GeocodeIn(BaseModel):
    """Input for the address geocoding endpoint."""
    address: str = Field(..., min_length=1, max_length=500)


class GeocodeOut(BaseModel):
    """Resolved coordinates for a geocoded address."""
    latitude: Decimal
    longitude: Decimal
