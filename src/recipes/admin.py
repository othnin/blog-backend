from django.contrib import admin
from .models import Recipe, RecipeIngredient, RecipeInstruction, RecipeRating, DietaryLabel


class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 1


class RecipeInstructionInline(admin.TabularInline):
    model = RecipeInstruction
    extra = 1


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ['title', 'author', 'status', 'cuisine_type', 'course', 'created_at']
    list_filter = ['status', 'cuisine_type', 'course', 'dietary_labels']
    search_fields = ['title', 'description', 'author__username']
    prepopulated_fields = {'slug': ('title',)}
    inlines = [RecipeIngredientInline, RecipeInstructionInline]


@admin.register(DietaryLabel)
class DietaryLabelAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(RecipeRating)
class RecipeRatingAdmin(admin.ModelAdmin):
    list_display = ['recipe', 'user', 'score']
    list_filter = ['score']
