"""
Admin configuration for authentication models.
"""
from django.contrib import admin
from home.blog_admin import blog_admin_site
from auth_app.models import EmailVerificationToken, PasswordResetToken, UserProfile
from auth_app.permissions import has_watsoncrick_access


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
    list_display = ('user', 'email_verified', 'created_at', 'updated_at', 'role', 'watsoncrick_access', 'avatar')
    list_filter = ('email_verified', 'created_at', 'role')
    search_fields = ('user__email', 'user__username')
    readonly_fields = ('created_at', 'updated_at', 'watsoncrick_access_help')

    @admin.display(boolean=True, description='WatsonCrick access')
    def watsoncrick_access(self, obj):
        """Show the permission granted by the WatsonCrick group (admins bypass it)."""
        return has_watsoncrick_access(obj.user)

    def watsoncrick_access_help(self, obj=None):
        from django.utils.safestring import mark_safe
        status = '<span style="color:green">✓ Has access</span>' if obj and has_watsoncrick_access(obj.user) else '<span style="color:#999">✗ No access</span>'
        html = (
            '<div class="watsoncrick-help-card">'
            '<h3>🔬 WatsonCrick Lab Access</h3>'
            '<p><strong>Current status:</strong> %s</p>'
            '<p>Grant access by adding this user to the <strong>WatsonCrick</strong> group. '
            'Admins (superuser or role=admin) bypass the group automatically.</p>'
            '<button type="button" class="watsoncrick-help-btn" onclick="showWatsonCrickHelp()">View Step-by-Step Instructions</button>'
            '</div>'
        ) % status
        return mark_safe(html)
    watsoncrick_access_help.short_description = "WatsonCrick Access Guide"

    fieldsets = (
        (None, {
            'fields': ('user', 'email_verified', 'role', 'avatar')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('WatsonCrick Access', {
            'fields': ('watsoncrick_access_help',),
        }),
    )


# Register with custom admin site
blog_admin_site.register(UserProfile, UserProfileAdmin)
blog_admin_site.register(EmailVerificationToken, EmailVerificationTokenAdmin)
blog_admin_site.register(PasswordResetToken, PasswordResetTokenAdmin)
