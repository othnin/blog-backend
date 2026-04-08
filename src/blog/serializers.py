"""
Serializers for blog models using Pydantic and Django Ninja.
Handles validation and serialization for API endpoints.
"""
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List
from datetime import datetime
import json


class CategoryOut(BaseModel):
    """Category output serializer."""
    id: int
    name: str
    slug: str
    created_at: datetime

    class Config:
        from_attributes = True


class UserBasicOut(BaseModel):
    """Basic user information for blog context."""
    id: int
    username: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    class Config:
        from_attributes = True


class UserWithProfileOut(UserBasicOut):
    """User information with profile details."""
    avatar: Optional[str] = None
    role: Optional[str] = None

    class Config:
        from_attributes = True

    @staticmethod
    def resolve_avatar(obj):
        """Resolve avatar URL from user.profile.avatar ImageField."""
        try:
            if obj.profile.avatar:
                from django.conf import settings
                return f"{settings.MEDIA_URL}{obj.profile.avatar.name}"
            return None
        except Exception:
            return None

    @staticmethod
    def resolve_role(obj):
        """Resolve role from user.profile.role"""
        try:
            return obj.profile.role
        except:
            return None


class TagOut(BaseModel):
    """Tag output serializer."""
    id: int
    name: str
    slug: str
    meta_description: str = ''
    created_at: datetime

    class Config:
        from_attributes = True


class TagCreateIn(BaseModel):
    """Input serializer for creating a tag."""
    name: str = Field(..., min_length=1, max_length=100)


class TagUpdateIn(BaseModel):
    """Input serializer for updating a tag."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    meta_description: Optional[str] = None


class CategoryCreateIn(BaseModel):
    """Input serializer for creating a category."""
    name: str = Field(..., min_length=1, max_length=100)


class BlogPostCreateIn(BaseModel):
    """Input serializer for creating a blog post."""
    title: str = Field(..., min_length=1, max_length=500)
    content_json: str = Field(..., description="Lexical editor JSON format")
    category_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None
    status: str = Field(default='draft')
    comments_disabled: bool = False

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid_statuses = ['draft', 'published', 'scheduled', 'archived']
        if v not in valid_statuses:
            raise ValueError(f'Status must be one of {valid_statuses}')
        return v

    @field_validator('content_json')
    @classmethod
    def validate_json(cls, v):
        try:
            json.loads(v)
        except json.JSONDecodeError:
            raise ValueError('content_json must be valid JSON')
        return v


class BlogPostUpdateIn(BaseModel):
    """Input serializer for updating a blog post."""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    content_json: Optional[str] = None
    category_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None
    status: Optional[str] = None
    comments_disabled: Optional[bool] = None

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v is None:
            return v
        valid_statuses = ['draft', 'published', 'scheduled', 'archived']
        if v not in valid_statuses:
            raise ValueError(f'Status must be one of {valid_statuses}')
        return v

    @field_validator('content_json')
    @classmethod
    def validate_json(cls, v):
        if v is None:
            return v
        try:
            json.loads(v)
        except json.JSONDecodeError:
            raise ValueError('content_json must be valid JSON')
        return v


class BlogPostAuthorOut(BaseModel):
    """Author info embedded in blog post responses — includes resolved avatar_url."""
    id: int
    username: str
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def resolve_avatar(cls, data):
        if hasattr(data, 'id'):  # ORM User object
            try:
                from django.conf import settings
                avatar_url = (
                    f"{settings.MEDIA_URL}{data.profile.avatar.name}"
                    if data.profile.avatar else None
                )
            except Exception:
                avatar_url = None
            return {'id': data.id, 'username': data.username, 'avatar_url': avatar_url}
        return data


class BlogPostOut(BaseModel):
    """Output serializer for blog posts (full details)."""
    id: int
    title: str
    slug: str
    content_json: str
    status: str
    view_count: int
    like_count: int
    comments_disabled: bool = False
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    author: BlogPostAuthorOut
    category: Optional[CategoryOut] = None
    tags: List[TagOut] = []

    class Config:
        from_attributes = True

    @field_validator('tags', mode='before')
    @classmethod
    def coerce_tags(cls, v):
        if hasattr(v, 'all'):
            return list(v.all())
        return v


class CommentAuthorOut(BaseModel):
    """Basic author info for comment output."""
    id: int
    username: str
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True


class CommentIn(BaseModel):
    """Input serializer for creating a comment."""
    content_json: str = Field(..., description="Lexical editor JSON format")
    parent_id: Optional[int] = None

    @field_validator('content_json')
    @classmethod
    def validate_json(cls, v):
        try:
            json.loads(v)
        except json.JSONDecodeError:
            raise ValueError('content_json must be valid JSON')
        return v


class CommentUpdateIn(BaseModel):
    """Input serializer for editing a comment."""
    content_json: str = Field(..., description="Lexical editor JSON format")

    @field_validator('content_json')
    @classmethod
    def validate_json(cls, v):
        try:
            json.loads(v)
        except json.JSONDecodeError:
            raise ValueError('content_json must be valid JSON')
        return v


class CommentOut(BaseModel):
    """Output serializer for a comment (recursive for nested replies)."""
    id: int
    author: Optional[CommentAuthorOut] = None
    content_json: Optional[str] = None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    replies: List['CommentOut'] = Field(default_factory=list)

    class Config:
        from_attributes = True


# Resolve the forward reference for recursive type
CommentOut.model_rebuild()


class BlogPostListOut(BaseModel):
    """Output serializer for blog post lists (summary)."""
    id: int
    title: str
    slug: str
    status: str
    view_count: int
    like_count: int
    published_at: Optional[datetime] = None
    created_at: datetime
    author: UserBasicOut
    category: Optional[CategoryOut] = None
    tags: List[TagOut] = []
    content_text: str = ''

    class Config:
        from_attributes = True

    @field_validator('tags', mode='before')
    @classmethod
    def coerce_tags(cls, v):
        if hasattr(v, 'all'):
            return list(v.all())
        return v


class LikeOut(BaseModel):
    """Response for a like action."""
    like_count: int

