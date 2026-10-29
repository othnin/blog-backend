from django.db import models


class Lesson(models.Model):
    """Represents a lesson in Classroom or Mystery Mode."""
    CLASSROOM = 'classroom'
    MYSTERY = 'mystery'
    MODE_CHOICES = [
        (CLASSROOM, 'Classroom Mode'),
        (MYSTERY, 'Watson & Crick Mystery Mode'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField()
    mode = models.CharField(max_length=10, choices=MODE_CHOICES)
    sequence_order = models.IntegerField(help_text="Order within the mode")
    content_json = models.JSONField(default=dict, help_text="Lesson content: title, objectives, evidence, challenges")
    simulation_year = models.IntegerField(default=1952, help_text="Historical year for this lesson")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['mode', 'sequence_order']
        unique_together = ('mode', 'sequence_order')
        # Thales access is one capability for the whole lab, not a per-lesson
        # grant. Django needs a model to attach a permission to, so it lives
        # here; membership in the Thales group is what actually grants it.
        permissions = [
            ('access_thales', 'Can access the Thales lab'),
        ]

    def __str__(self):
        return f"{self.get_mode_display()} - {self.title}"


class StudentProgress(models.Model):
    """Tracks a student's progress through lessons and challenges."""
    session_id = models.CharField(max_length=100, unique=True)
    # The authenticated learner this session belongs to. Deliberately a plain
    # integer, not a foreign key: the lab can be removed without touching the
    # site's auth tables. Kept nullable so older session-only rows remain valid.
    user_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    # Snapshot of the username at the time of activity, so classroom records
    # stay readable even if the account is later renamed or deleted.
    username = models.CharField(max_length=150, blank=True, default='')
    current_lesson = models.ForeignKey(Lesson, null=True, on_delete=models.SET_NULL)
    completed_lessons = models.ManyToManyField(Lesson, related_name='completed_by', blank=True)
    state_json = models.JSONField(default=dict, help_text="Challenge state, unlocked evidence, etc.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Progress: {self.session_id} @ Lesson {self.current_lesson}"


class AssistantInteraction(models.Model):
    """Logs LLM interactions for analytics and context."""
    RESPONSE_TYPES = [
        ('explanation', 'Explanation'),
        ('hint', 'Hint'),
        ('feedback', 'Feedback'),
        ('question', 'Question'),
        ('refusal_historical', 'Refusal: Historical Limit'),
        ('refusal_spoiler', 'Refusal: Spoiler Limit'),
    ]

    progress = models.ForeignKey(StudentProgress, on_delete=models.CASCADE, related_name='interactions')
    username = models.CharField(max_length=150, blank=True, default='')
    question = models.TextField()
    response = models.TextField()
    response_type = models.CharField(max_length=20, choices=RESPONSE_TYPES)
    hint_level = models.IntegerField(default=0)
    historical_safe = models.BooleanField(default=True)
    spoiler_safe = models.BooleanField(default=True)
    simulation_year = models.IntegerField()
    mode = models.CharField(max_length=10, choices=Lesson.MODE_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.progress.session_id}: {self.response_type}"


class ModelExperiment(models.Model):
    """Records each molecular model a student constructs and tests."""
    progress = models.ForeignKey(StudentProgress, on_delete=models.CASCADE, related_name='experiments')
    username = models.CharField(max_length=150, blank=True, default='')
    left_base = models.CharField(max_length=2)
    right_base = models.CharField(max_length=2)
    model_state_json = models.JSONField(default=dict, help_text="Positions, rotations, etc.")
    validity_json = models.JSONField(default=dict, help_text="Validation results: valid, reasons, observations")
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.progress.session_id}: {self.left_base}-{self.right_base} @ {self.timestamp}"


class HypothesisNote(models.Model):
    """One reflective hypothesis per learner. Free text, never graded."""
    user_id = models.PositiveIntegerField(unique=True, db_index=True)
    username = models.CharField(max_length=150, blank=True, default='')
    text = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Hypothesis: user {self.user_id}"
