from django.db import models


class AdvisorSession(models.Model):
    """Tracks a client's literature-advisor session for MAX_Q enforcement.

    Replaces the old in-memory `sessions = {}` dict from
    thales_old/server/api/views.py with a DB-backed model so state survives
    process restarts and works correctly under multiple workers.
    """
    session_id = models.CharField(max_length=64, primary_key=True)
    question_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.session_id} ({self.question_count} question(s))"
