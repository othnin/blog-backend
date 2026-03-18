from django.contrib import admin
from .models import Category, BlogPost


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'created_at')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'status', 'view_count', 'published_at', 'created_at')
    list_filter = ('status', 'created_at', 'published_at')
    search_fields = ('title', 'slug', 'author__username')
    filter_horizontal = ('categories',)
    readonly_fields = ('view_count', 'created_at', 'updated_at')
    prepopulated_fields = {'slug': ('title',)}
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'slug', 'author', 'featured_image_url')
        }),
        ('Content', {
            'fields': ('content_json',)
        }),
        ('Metadata', {
            'fields': ('categories', 'status', 'view_count')
        }),
        ('Publishing', {
            'fields': ('published_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
