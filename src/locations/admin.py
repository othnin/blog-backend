"""
Admin configuration for location models.
"""
from django.contrib import admin
from home.blog_admin import blog_admin_site
from locations.models import Location, RestaurantLocation


class RestaurantLocationInline(admin.StackedInline):
    model = RestaurantLocation
    extra = 1
    max_num = 1
    can_delete = False


class LocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'michelin_rating', 'is_published', 'created_by', 'created_at')
    list_filter = ('type', 'is_published', 'restaurant__michelin_rating')
    search_fields = ('name', 'address', 'description')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [RestaurantLocationInline]

    @admin.display(description='Michelin rating')
    def michelin_rating(self, obj):
        restaurant = getattr(obj, 'restaurant', None)
        return restaurant.get_michelin_rating_display() if restaurant else '—'


class RestaurantLocationAdmin(admin.ModelAdmin):
    list_display = ('location', 'michelin_rating', 'cuisine_type')
    list_filter = ('michelin_rating',)
    search_fields = ('location__name', 'cuisine_type')


# Register with custom admin site
blog_admin_site.register(Location, LocationAdmin)
blog_admin_site.register(RestaurantLocation, RestaurantLocationAdmin)
