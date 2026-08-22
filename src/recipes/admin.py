from django.contrib import admin
from home.blog_admin import blog_admin_site
from .models import Recipe, RecipeIngredient, RecipeInstruction, RecipeRating, DietaryLabel


class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 1


class RecipeInstructionInline(admin.TabularInline):
    model = RecipeInstruction
    extra = 1


class RecipeAdmin(admin.ModelAdmin):
    list_display = ['title', 'author', 'status', 'cuisine_type', 'course', 'created_at']
    list_filter = ['status', 'cuisine_type', 'course', 'dietary_labels']
    search_fields = ['title', 'description_text', 'author__username']
    prepopulated_fields = {'slug': ('title',)}
    inlines = [RecipeIngredientInline, RecipeInstructionInline]


class DietaryLabelAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


class RecipeRatingAdmin(admin.ModelAdmin):
    list_display = ['recipe', 'user', 'score']
    list_filter = ['score']


# Register with custom admin site
blog_admin_site.register(Recipe, RecipeAdmin)
blog_admin_site.register(DietaryLabel, DietaryLabelAdmin)
blog_admin_site.register(RecipeRating, RecipeRatingAdmin)
