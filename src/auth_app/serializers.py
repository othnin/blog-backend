"""
Serializers for authentication endpoints.
"""
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from pydantic import BaseModel, EmailStr, field_validator, model_validator, ConfigDict
from typing import Optional
import re


class RegisterSerializer(BaseModel):
    """Serializer for user registration."""
    model_config = ConfigDict(populate_by_name=True)
    
    email: EmailStr
    password: str
    password_confirm: str
    username: str

    @field_validator('password', mode='before')
    @classmethod
    def validate_password_strength(cls, v):
        """Validate password meets minimum requirements."""
        if not isinstance(v, str):
            raise ValueError('Password must be a string')
        
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        
        has_upper = any(c.isupper() for c in v)
        has_lower = any(c.islower() for c in v)
        has_digit = any(c.isdigit() for c in v)
        
        if not (has_upper and has_lower and has_digit):
            raise ValueError('Password must contain uppercase, lowercase, and numeric characters')
        
        return v

    @field_validator('password_confirm', mode='before')
    @classmethod
    def passwords_match(cls, v, info):
        """Ensure password and password_confirm match."""
        if 'password' in info.data and v != info.data['password']:
            raise ValueError('Passwords do not match')
        return v

    @model_validator(mode='after')
    def set_username(self):
        """Generate username from email if not provided."""
        if not self.username or self.username == '':
            self.username = self.email.split('@')[0]
        
        # Ensure username is unique
        base_username = self.username
        counter = 1
        while User.objects.filter(username=self.username).exists():
            self.username = f"{base_username}{counter}"
            counter += 1
        
        return self


class EmailVerificationSerializer(BaseModel):
    """Serializer for email verification."""
    token: str


class PasswordResetRequestSerializer(BaseModel):
    """Serializer for password reset request."""
    email: EmailStr


class PasswordResetConfirmSerializer(BaseModel):
    """Serializer for password reset confirmation."""
    token: str
    new_password: str
    new_password_confirm: str

    @field_validator('new_password', mode='before')
    @classmethod
    def validate_password_strength(cls, v):
        """Validate password meets minimum requirements."""
        if not isinstance(v, str):
            raise ValueError('Password must be a string')
        
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        
        has_upper = any(c.isupper() for c in v)
        has_lower = any(c.islower() for c in v)
        has_digit = any(c.isdigit() for c in v)
        
        if not (has_upper and has_lower and has_digit):
            raise ValueError('Password must contain uppercase, lowercase, and numeric characters')
        
        return v

    @field_validator('new_password_confirm', mode='before')
    @classmethod
    def passwords_match(cls, v, info):
        """Ensure password and password_confirm match."""
        if 'new_password' in info.data and v != info.data['new_password']:
            raise ValueError('Passwords do not match')
        return v


class UserResponseSchema(BaseModel):
    """Schema for user response data."""
    id: int
    username: str
    email: str
    email_verified: bool = False
    profile: Optional[dict] = None

    class Config:
        from_attributes = True

    @staticmethod
    def resolve_email_verified(obj):
        """Resolve email_verified from user profile."""
        if hasattr(obj, 'profile'):
            return obj.profile.email_verified
        return False

class LoginSerializer(BaseModel):
    """Serializer for user login."""
    username: str
    password: str


class UserSettingsSchema(BaseModel):
    """Schema for reading user profile settings."""
    display_name: str = ''
    bio: str = ''
    email_notifications: bool = True
    twitter_url: str = ''
    github_url: str = ''
    website_url: str = ''
    profile_public: bool = True
    avatar_url: Optional[str] = None


class UserSettingsUpdateSchema(BaseModel):
    """Schema for updating user profile settings (all fields optional)."""
    display_name: Optional[str] = None
    bio: Optional[str] = None
    email_notifications: Optional[bool] = None
    twitter_url: Optional[str] = None
    github_url: Optional[str] = None
    website_url: Optional[str] = None
    profile_public: Optional[bool] = None


class ChangePasswordSchema(BaseModel):
    """Schema for changing a user's password."""
    current_password: str
    new_password: str
    new_password_confirm: str

    @field_validator('new_password', mode='before')
    @classmethod
    def validate_password_strength(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not (any(c.isupper() for c in v) and any(c.islower() for c in v) and any(c.isdigit() for c in v)):
            raise ValueError('Password must contain uppercase, lowercase, and numeric characters')
        return v

    @field_validator('new_password_confirm', mode='before')
    @classmethod
    def passwords_match(cls, v, info):
        if 'new_password' in info.data and v != info.data['new_password']:
            raise ValueError('Passwords do not match')
        return v