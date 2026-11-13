"""Advisor-side API for the Thales lab.

An advisor is a normal lab member who also holds ``thales.advise_students``.
This router lets them inspect every learner's recorded work, maintain one
advisor-only grade per learner, and append to a feedback thread that the
learner can read. Grades never appear in a student-facing response.

The whole router sits behind the same injected API auth as the rest of
Thales; each view additionally calls :func:`_require_advisor`, so an ordinary
lab member gets a 403 rather than a partial view of the roster.
"""

from typing import Optional

from django.db.models import Count, Max
from ninja import Router
from ninja.errors import HttpError
from pydantic import BaseModel, Field

from thales.access import get_api_auth, has_advisor_access
from thales.models import (
    AdvisorFeedback,
    AssistantInteraction,
    HypothesisNote,
    ModelExperiment,
    StudentGrade,
    StudentProgress,
)

router = Router(auth=[get_api_auth()])


class FeedbackRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


class GradeRequest(BaseModel):
    grade: str = Field(default='', max_length=32)


def _require_advisor(request):
    if not has_advisor_access(request.auth):
        raise HttpError(403, 'Advisor access required')
    return request.auth


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _latest_datetime(values):
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _student_exists(user_id: int) -> bool:
    return (
        StudentProgress.objects.filter(user_id=user_id).exists()
        or HypothesisNote.objects.filter(user_id=user_id).exists()
        or StudentGrade.objects.filter(student_user_id=user_id).exists()
        or AdvisorFeedback.objects.filter(student_user_id=user_id).exists()
    )


def _serialize_progress(progress: StudentProgress) -> dict:
    return {
        'id': progress.id,
        'session_id': progress.session_id,
        'current_lesson': (
            progress.current_lesson.title if progress.current_lesson else None
        ),
        'completed_lessons': [
            {'id': lesson.id, 'title': lesson.title, 'mode': lesson.mode}
            for lesson in progress.completed_lessons.all()
        ],
        'state_json': progress.state_json,
        'created_at': _iso(progress.created_at),
        'updated_at': _iso(progress.updated_at),
    }


def _serialize_experiment(experiment: ModelExperiment) -> dict:
    return {
        'id': experiment.id,
        'session_id': experiment.progress.session_id,
        'left_base': experiment.left_base,
        'right_base': experiment.right_base,
        'model_state_json': experiment.model_state_json,
        'validity_json': experiment.validity_json,
        'timestamp': _iso(experiment.timestamp),
    }


def _serialize_interaction(interaction: AssistantInteraction) -> dict:
    return {
        'id': interaction.id,
        'session_id': interaction.progress.session_id,
        'question': interaction.question,
        'response': interaction.response,
        'response_type': interaction.response_type,
        'hint_level': interaction.hint_level,
        'simulation_year': interaction.simulation_year,
        'mode': interaction.mode,
        'timestamp': _iso(interaction.timestamp),
    }


def _serialize_feedback(entry: AdvisorFeedback) -> dict:
    return {
        'id': entry.id,
        'text': entry.text,
        'advisor_username': entry.advisor_username,
        'created_at': _iso(entry.created_at),
    }


def _serialize_grade(grade: Optional[StudentGrade]) -> Optional[dict]:
    if grade is None:
        return None
    return {
        'grade': grade.grade,
        'graded_by_username': grade.graded_by_username,
        'updated_at': _iso(grade.updated_at),
    }


def _display_name(
    user_id: int,
    progress: Optional[StudentProgress] = None,
    hypothesis: Optional[HypothesisNote] = None,
    grade: Optional[StudentGrade] = None,
    feedback: Optional[AdvisorFeedback] = None,
) -> str:
    for value in (
        progress.username if progress else '',
        hypothesis.username if hypothesis else '',
        grade.student_username if grade else '',
        feedback.student_username if feedback else '',
    ):
        if value:
            return value
    return f'user-{user_id}'


@router.get('/students/')
def list_students(request):
    """Return every learner with Thales activity, plus advisor-only state."""
    _require_advisor(request)

    latest_progress = {}
    progress_rows = (
        StudentProgress.objects.filter(user_id__isnull=False)
        .select_related('current_lesson')
        .order_by('user_id', '-updated_at')
    )
    for row in progress_rows:
        latest_progress.setdefault(row.user_id, row)

    progress_counts = dict(
        StudentProgress.objects.filter(user_id__isnull=False)
        .values_list('user_id')
        .annotate(count=Count('id'))
    )
    experiment_counts = dict(
        ModelExperiment.objects.exclude(progress__user_id=None)
        .values_list('progress__user_id')
        .annotate(count=Count('id'))
    )
    experiment_last = dict(
        ModelExperiment.objects.exclude(progress__user_id=None)
        .values_list('progress__user_id')
        .annotate(last=Max('timestamp'))
    )
    interaction_counts = dict(
        AssistantInteraction.objects.exclude(progress__user_id=None)
        .values_list('progress__user_id')
        .annotate(count=Count('id'))
    )
    interaction_last = dict(
        AssistantInteraction.objects.exclude(progress__user_id=None)
        .values_list('progress__user_id')
        .annotate(last=Max('timestamp'))
    )
    feedback_counts = dict(
        AdvisorFeedback.objects.values_list('student_user_id')
        .annotate(count=Count('id'))
    )
    feedback_last = dict(
        AdvisorFeedback.objects.values_list('student_user_id')
        .annotate(last=Max('created_at'))
    )

    hypothesis = {
        note.user_id: note for note in HypothesisNote.objects.all()
    }
    grades = {
        grade.student_user_id: grade for grade in StudentGrade.objects.all()
    }

    latest_feedback = {}
    for entry in AdvisorFeedback.objects.order_by(
        'student_user_id', '-created_at'
    ):
        latest_feedback.setdefault(entry.student_user_id, entry)

    user_ids = sorted(
        set(latest_progress)
        | set(hypothesis)
        | set(grades)
        | set(latest_feedback)
    )

    students = []
    for user_id in user_ids:
        progress = latest_progress.get(user_id)
        note = hypothesis.get(user_id)
        grade = grades.get(user_id)
        feedback = latest_feedback.get(user_id)

        students.append(
            {
                'user_id': user_id,
                'username': _display_name(
                    user_id, progress, note, grade, feedback
                ),
                'current_lesson': (
                    progress.current_lesson.title
                    if progress and progress.current_lesson
                    else None
                ),
                'progress_count': progress_counts.get(user_id, 0),
                'experiment_count': experiment_counts.get(user_id, 0),
                'question_count': interaction_counts.get(user_id, 0),
                'feedback_count': feedback_counts.get(user_id, 0),
                'grade': grade.grade if grade else None,
                'last_activity': _iso(
                    _latest_datetime(
                        (
                            progress.updated_at if progress else None,
                            experiment_last.get(user_id),
                            interaction_last.get(user_id),
                            note.updated_at if note else None,
                            grade.updated_at if grade else None,
                            feedback_last.get(user_id),
                        )
                    )
                ),
            }
        )

    return {'students': students}


@router.get('/students/{user_id}/')
def get_student(request, user_id: int):
    """Return one learner's full lab record and feedback thread."""
    _require_advisor(request)

    if not _student_exists(user_id):
        raise HttpError(404, f'Student {user_id} not found')

    progress_rows = list(
        StudentProgress.objects.filter(user_id=user_id)
        .select_related('current_lesson')
        .prefetch_related('completed_lessons')
        .order_by('created_at')
    )
    experiments = list(
        ModelExperiment.objects.filter(progress__user_id=user_id)
        .select_related('progress')
        .order_by('-timestamp')
    )
    interactions = list(
        AssistantInteraction.objects.filter(progress__user_id=user_id)
        .select_related('progress')
        .order_by('-timestamp')
    )
    hypothesis = HypothesisNote.objects.filter(user_id=user_id).first()
    grade = StudentGrade.objects.filter(student_user_id=user_id).first()
    feedback = list(
        AdvisorFeedback.objects.filter(student_user_id=user_id).order_by(
            '-created_at'
        )
    )

    return {
        'user_id': user_id,
        'username': _display_name(
            user_id,
            progress_rows[-1] if progress_rows else None,
            hypothesis,
            grade,
            feedback[0] if feedback else None,
        ),
        'progress': [_serialize_progress(row) for row in progress_rows],
        'experiments': [
            _serialize_experiment(experiment) for experiment in experiments
        ],
        'interactions': [
            _serialize_interaction(interaction)
            for interaction in interactions
        ],
        'hypothesis': (
            {
                'text': hypothesis.text,
                'updated_at': _iso(hypothesis.updated_at),
            }
            if hypothesis
            else None
        ),
        'grade': _serialize_grade(grade),
        'feedback': [_serialize_feedback(entry) for entry in feedback],
    }


@router.post('/students/{user_id}/feedback/')
def add_feedback(request, user_id: int, payload: FeedbackRequest):
    """Append an advisor note to a learner's feedback thread."""
    advisor = _require_advisor(request)

    if not _student_exists(user_id):
        raise HttpError(404, f'Student {user_id} not found')

    text = payload.text.strip()
    if not text:
        raise HttpError(400, 'Feedback text cannot be empty')

    latest_progress = (
        StudentProgress.objects.filter(user_id=user_id)
        .order_by('-updated_at')
        .first()
    )
    hypothesis = HypothesisNote.objects.filter(user_id=user_id).first()
    grade = StudentGrade.objects.filter(student_user_id=user_id).first()
    previous = (
        AdvisorFeedback.objects.filter(student_user_id=user_id)
        .order_by('-created_at')
        .first()
    )
    student_username = _display_name(
        user_id, latest_progress, hypothesis, grade, previous
    )

    entry = AdvisorFeedback.objects.create(
        student_user_id=user_id,
        student_username=student_username,
        advisor_id=advisor.id,
        advisor_username=advisor.get_username(),
        text=text,
    )
    return _serialize_feedback(entry)


@router.put('/students/{user_id}/grade/')
def set_grade(request, user_id: int, payload: GradeRequest):
    """Create, replace, or clear the one advisor-only grade for a learner."""
    advisor = _require_advisor(request)

    if not _student_exists(user_id):
        raise HttpError(404, f'Student {user_id} not found')

    grade_value = payload.grade.strip()
    if not grade_value:
        StudentGrade.objects.filter(student_user_id=user_id).delete()
        return {'student_user_id': user_id, 'grade': None}

    latest_progress = (
        StudentProgress.objects.filter(user_id=user_id)
        .order_by('-updated_at')
        .first()
    )
    hypothesis = HypothesisNote.objects.filter(user_id=user_id).first()
    previous_feedback = (
        AdvisorFeedback.objects.filter(student_user_id=user_id)
        .order_by('-created_at')
        .first()
    )
    student_username = _display_name(
        user_id, latest_progress, hypothesis, None, previous_feedback
    )

    grade, _ = StudentGrade.objects.update_or_create(
        student_user_id=user_id,
        defaults={
            'student_username': student_username,
            'grade': grade_value,
            'graded_by_id': advisor.id,
            'graded_by_username': advisor.get_username(),
        },
    )
    return {
        'student_user_id': user_id,
        'grade': grade.grade,
        'graded_by_username': grade.graded_by_username,
        'updated_at': _iso(grade.updated_at),
    }
