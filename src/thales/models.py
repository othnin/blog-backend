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

    def __str__(self):
        return f"{self.get_mode_display()} - {self.title}"


class StudentProgress(models.Model):
    """Tracks a student's progress through lessons and challenges."""
    session_id = models.CharField(max_length=100, unique=True)
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
    left_base = models.CharField(max_length=2)
    right_base = models.CharField(max_length=2)
    model_state_json = models.JSONField(default=dict, help_text="Positions, rotations, etc.")
    validity_json = models.JSONField(default=dict, help_text="Validation results: valid, reasons, observations")
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.progress.session_id}: {self.left_base}-{self.right_base} @ {self.timestamp}"
