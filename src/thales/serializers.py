from rest_framework import serializers
from thales.models import Lesson, StudentProgress, AssistantInteraction, ModelExperiment


class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ['id', 'title', 'description', 'mode', 'sequence_order', 'content_json', 'simulation_year']


class StudentProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentProgress
        fields = ['id', 'session_id', 'current_lesson', 'completed_lessons', 'state_json', 'updated_at']


class AssistantInteractionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssistantInteraction
        fields = ['id', 'progress', 'question', 'response', 'response_type', 'hint_level', 'timestamp']


class ModelExperimentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModelExperiment
        fields = ['id', 'progress', 'left_base', 'right_base', 'model_state_json', 'validity_json', 'timestamp']
