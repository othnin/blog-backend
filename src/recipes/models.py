"""
Recipe models for creating and managing recipes.
Separate from blog posts — recipes have structured ingredients,
instructions, timing, ratings, and dietary classification.
"""
from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.utils import timezone


class DietaryLabel(models.Model):
    """Dietary classification labels (Vegan, Gluten-Free, etc.)."""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Recipe(models.Model):
    """
    Recipe model with structured ingredients, instructions, timing,
    and dietary/cuisine/course classification.
    """
    CUISINE_CHOICES = [
        ('italian', 'Italian'),
        ('mexican', 'Mexican'),
        ('asian', 'Asian'),
        ('american', 'American'),
        ('mediterranean', 'Mediterranean'),
        ('french', 'French'),
        ('indian', 'Indian'),
        ('middle_eastern', 'Middle Eastern'),
        ('greek', 'Greek'),
        ('japanese', 'Japanese'),
        ('thai', 'Thai'),
        ('chinese', 'Chinese'),
        ('korean', 'Korean'),
        ('other', 'Other'),
    ]

    COURSE_CHOICES = [
        ('breakfast', 'Breakfast'),
        ('lunch', 'Lunch'),
        ('dinner', 'Dinner'),
        ('dessert', 'Dessert'),
        ('appetizer', 'Appetizer'),
        ('snack', 'Snack'),
        ('drink', 'Drink'),
        ('sauce', 'Sauce/Condiment'),
        ('side', 'Side Dish'),
        ('soup', 'Soup'),
        ('salad', 'Salad'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]

    # Core fields
    title = models.CharField(max_length=500, db_index=True)
    slug = models.SlugField(max_length=500, unique=True, db_index=True)
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='recipes',
    )
    description = models.TextField(blank=True, default='')

    # Images stored as JSON list of URL strings; images[0] is the hero image
    images = models.JSONField(default=list, blank=True)

    notes = models.TextField(blank=True, default='')

    # Timing
    prep_time_minutes = models.PositiveIntegerField(null=True, blank=True)
    cook_time_minutes = models.PositiveIntegerField(null=True, blank=True)

    # Yield
    yield_amount = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    yield_unit = models.CharField(max_length=50, blank=True, default='')

    # Classification
    cuisine_type = models.CharField(max_length=30, choices=CUISINE_CHOICES, blank=True, default='')
    course = models.CharField(max_length=30, choices=COURSE_CHOICES, blank=True, default='')
    dietary_labels = models.ManyToManyField(DietaryLabel, blank=True, related_name='recipes')
    tags = models.ManyToManyField('blog.Tag', blank=True, related_name='recipes')

    # Status & Publishing
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        db_index=True,
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # Analytics
    view_count = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-created_at']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['author', 'status']),
            models.Index(fields=['status', '-published_at']),
        ]

    def __str__(self):
        return self.title

    @property
    def total_time_minutes(self):
        return (self.prep_time_minutes or 0) + (self.cook_time_minutes or 0)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        if self.status == 'published' and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def increment_view_count(self):
        self.view_count += 1
        self.save(update_fields=['view_count', 'updated_at'])


class RecipeIngredient(models.Model):
    """
    A single ingredient line in a recipe.
    Structured to support scaling (amount is a decimal field).
    """
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='ingredients')
    order = models.PositiveSmallIntegerField(default=0)
    amount = models.DecimalField(max_digits=8, decimal_places=3)
    unit = models.CharField(max_length=30, blank=True, default='')
    name = models.CharField(max_length=200)
    notes = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.amount} {self.unit} {self.name}".strip()


class RecipeInstruction(models.Model):
    """An ordered step in a recipe."""
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='instructions')
    step_number = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=200, blank=True, default='')
    content = models.TextField()

    class Meta:
        ordering = ['step_number']
        unique_together = [('recipe', 'step_number')]

    def __str__(self):
        return f"Step {self.step_number}: {self.title or self.content[:50]}"


class RecipeRating(models.Model):
    """One rating (1–5 stars) per user per recipe. Upsertable."""
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='ratings')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recipe_ratings')
    score = models.PositiveSmallIntegerField()  # 1–5, validated in serializer

    class Meta:
        unique_together = [('recipe', 'user')]

    def __str__(self):
        return f"{self.user.username} rated {self.recipe.title}: {self.score}"
