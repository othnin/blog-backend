from django.contrib import admin

from .models import (
    AdvisorFeedback,
    AssistantInteraction,
    HypothesisNote,
    Lesson,
    ModelExperiment,
    StudentGrade,
    StudentProgress,
)


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'mode', 'sequence_order', 'simulation_year')
    list_filter = ('mode',)
    search_fields = ('title', 'description')


@admin.register(StudentProgress)
class StudentProgressAdmin(admin.ModelAdmin):
    list_display = ('session_id', 'username', 'user_id', 'current_lesson', 'updated_at')
    search_fields = ('session_id', 'username')
    list_filter = ('current_lesson__mode',)


@admin.register(ModelExperiment)
class ModelExperimentAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'left_base', 'right_base', 'timestamp')
    search_fields = ('username',)


@admin.register(AssistantInteraction)
class AssistantInteractionAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'response_type', 'mode', 'timestamp')
    list_filter = ('response_type', 'mode')
    search_fields = ('username', 'question', 'response')


@admin.register(HypothesisNote)
class HypothesisNoteAdmin(admin.ModelAdmin):
    list_display = ('user_id', 'username', 'updated_at')
    search_fields = ('username', 'text')


@admin.register(StudentGrade)
class StudentGradeAdmin(admin.ModelAdmin):
    list_display = (
        'student_user_id',
        'student_username',
        'grade',
        'graded_by_username',
        'updated_at',
    )
    search_fields = ('student_username', 'grade')


@admin.register(AdvisorFeedback)
class AdvisorFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'student_user_id',
        'student_username',
        'advisor_username',
        'created_at',
    )
    search_fields = ('student_username', 'advisor_username', 'text')
