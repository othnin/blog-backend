"""
Serializers for recipe models using Pydantic and Django Ninja.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
from decimal import Decimal


class DietaryLabelOut(BaseModel):
    id: int
    name: str
    slug: str

    class Config:
        from_attributes = True


class DietaryLabelCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class TagOut(BaseModel):
    id: int
    name: str
    slug: str

    class Config:
        from_attributes = True


class RecipeAuthorOut(BaseModel):
    id: int
    username: str
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True


class RecipeIngredientIn(BaseModel):
    order: int = 0
    amount: Decimal = Field(..., gt=0)
    unit: str = Field(default='', max_length=30)
    name: str = Field(..., min_length=1, max_length=200)
    notes: str = Field(default='', max_length=300)


class RecipeIngredientOut(BaseModel):
    id: int
    order: int
    amount: Decimal
    unit: str
    name: str
    notes: str

    class Config:
        from_attributes = True


class RecipeInstructionIn(BaseModel):
    step_number: int = Field(..., gt=0)
    title: str = Field(default='', max_length=200)
    content: str = Field(..., min_length=1)


class RecipeInstructionOut(BaseModel):
    id: int
    step_number: int
    title: str
    content: str

    class Config:
        from_attributes = True


class RecipeCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str = ''
    images: List[str] = []
    ingredients: List[RecipeIngredientIn] = []
    instructions: List[RecipeInstructionIn] = []
    notes: str = ''
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    yield_amount: Optional[Decimal] = None
    yield_unit: str = ''
    cuisine_type: str = ''
    course: str = ''
    dietary_label_ids: List[int] = []
    tag_ids: List[int] = []
    status: str = Field(default='draft')

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid = ['draft', 'published', 'archived']
        if v not in valid:
            raise ValueError(f'Status must be one of {valid}')
        return v


class RecipeUpdateIn(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    images: Optional[List[str]] = None
    ingredients: Optional[List[RecipeIngredientIn]] = None
    instructions: Optional[List[RecipeInstructionIn]] = None
    notes: Optional[str] = None
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    yield_amount: Optional[Decimal] = None
    yield_unit: Optional[str] = None
    cuisine_type: Optional[str] = None
    course: Optional[str] = None
    dietary_label_ids: Optional[List[int]] = None
    tag_ids: Optional[List[int]] = None
    status: Optional[str] = None

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v is None:
            return v
        valid = ['draft', 'published', 'archived']
        if v not in valid:
            raise ValueError(f'Status must be one of {valid}')
        return v


class RecipeListOut(BaseModel):
    """Summary output for recipe list pages."""
    id: int
    title: str
    slug: str
    status: str
    view_count: int
    published_at: Optional[datetime] = None
    created_at: datetime
    author: RecipeAuthorOut
    description: str = ''
    images: List[str] = []
    cuisine_type: str = ''
    course: str = ''
    dietary_labels: List[DietaryLabelOut] = []
    tags: List[TagOut] = []
    avg_rating: Optional[float] = None
    rating_count: int = 0
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    yield_amount: Optional[Decimal] = None
    yield_unit: str = ''

    class Config:
        from_attributes = True

    @field_validator('dietary_labels', mode='before')
    @classmethod
    def coerce_dietary_labels(cls, v):
        if hasattr(v, 'all'):
            return list(v.all())
        return v

    @field_validator('tags', mode='before')
    @classmethod
    def coerce_tags(cls, v):
        if hasattr(v, 'all'):
            return list(v.all())
        return v


class RecipeDetailOut(RecipeListOut):
    """Full output for recipe detail pages."""
    ingredients: List[RecipeIngredientOut] = []
    instructions: List[RecipeInstructionOut] = []
    notes: str = ''
    updated_at: datetime

    @field_validator('ingredients', mode='before')
    @classmethod
    def coerce_ingredients(cls, v):
        if hasattr(v, 'all'):
            return list(v.all())
        return v

    @field_validator('instructions', mode='before')
    @classmethod
    def coerce_instructions(cls, v):
        if hasattr(v, 'all'):
            return list(v.all())
        return v


class RecipeRatingIn(BaseModel):
    score: int = Field(..., ge=1, le=5)


class RecipeRatingOut(BaseModel):
    avg_rating: Optional[float]
    rating_count: int
    user_score: Optional[int] = None
