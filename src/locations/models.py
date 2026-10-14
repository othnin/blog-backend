"""
Location models for the mapping system.

A generic ``Location`` base stores data common to every point of interest
(restaurants, hotels, attractions). Type-specific detail lives in a submodel
that shares the base row's primary key via a ``OneToOneField(primary_key=True)``.

The initial use case is restaurants in Austin, so ``RestaurantLocation`` is the
first (and currently only) submodel.
"""
from django.db import models
from django.contrib.auth.models import User


class Location(models.Model):
    """
    Common data for any mapped point of interest.

    Coordinates are stored as ``DecimalField`` (not floats) so exact geocoded
    values round-trip without binary-float drift. Public list endpoints only
    expose rows where ``is_published`` is True; unpublished rows are visible
    only to editors/admins through the dashboard endpoints.
    """

    TYPE_CHOICES = [
        ('restaurant', 'Restaurant'),
        ('hotel', 'Hotel'),
        ('attraction', 'Attraction'),
    ]

    type = models.CharField(max_length=50, choices=TYPE_CHOICES, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    address = models.CharField(max_length=500)
    phone = models.CharField(max_length=20, blank=True, default='')
    website = models.URLField(max_length=200, blank=True, null=True)
    picture = models.ImageField(upload_to='locations/', blank=True, null=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)

    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='locations',
        help_text='The editor/admin who created the location. Null after account deletion.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_published = models.BooleanField(
        default=True,
        help_text='Controls public visibility; allows soft-archive of a location.',
    )

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['type', 'is_published']),
            models.Index(fields=['latitude', 'longitude']),
        ]

    def __str__(self):
        return f'{self.name} ({self.type})'


class RestaurantLocation(models.Model):
    """
    Restaurant-specific metadata attached to a ``Location``.

    The shared primary key means one location has exactly one restaurant
    detail row; deleting the base location cascades to this row.
    """

    MICHELIN_RATING_CHOICES = [
        ('one_star', 'One Star'),
        ('two_star', 'Two Stars'),
        ('three_star', 'Three Stars'),
        ('bib_gourmand', 'Bib Gourmand'),
        ('selected', 'Selected'),
        ('green_star', 'Green Star'),
        ('none', 'None'),
    ]

    location = models.OneToOneField(
        Location,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='restaurant',
    )
    michelin_rating = models.CharField(
        max_length=50,
        choices=MICHELIN_RATING_CHOICES,
        default='none',
        db_index=True,
    )
    cuisine_type = models.CharField(max_length=100, blank=True, default='')
    reservations_link = models.URLField(max_length=200, blank=True, null=True)
    review_link = models.URLField(
        max_length=200,
        blank=True,
        null=True,
        help_text='Manual link to the authoring blog post review, if any.',
    )

    class Meta:
        ordering = ['location__name']

    def __str__(self):
        return f'Restaurant: {self.location.name} ({self.get_michelin_rating_display()})'
