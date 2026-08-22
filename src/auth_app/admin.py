"""
Admin configuration for authentication models.
"""
from django.contrib import admin
from home.blog_admin import blog_admin_site
from auth_app.models import EmailVerificationToken, PasswordResetToken, UserProfile


class EmailVerificationTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at', 'expires_at', 'is_used', 'is_valid')
    list_filter = ('is_used', 'created_at')
    search_fields = ('user__email', 'user__username')
    readonly_fields = ('token', 'created_at', 'expires_at')

    def is_valid(self, obj):
        return obj.is_valid()
    is_valid.boolean = True


class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at', 'expires_at', 'is_used', 'is_valid')
    list_filter = ('is_used', 'created_at')
    search_fields = ('user__email', 'user__username')
    readonly_fields = ('token', 'created_at', 'expires_at')

    def is_valid(self, obj):
        return obj.is_valid()
    is_valid.boolean = True


class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'email_verified', 'created_at', 'updated_at', 'role', 'avatar')
    list_filter = ('email_verified', 'created_at', 'role')
    search_fields = ('user__email', 'user__username')
    readonly_fields = ('created_at', 'updated_at')


# Register with custom admin site
blog_admin_site.register(UserProfile, UserProfileAdmin)
blog_admin_site.register(EmailVerificationToken, EmailVerificationTokenAdmin)
blog_admin_site.register(PasswordResetToken, PasswordResetTokenAdmin)
