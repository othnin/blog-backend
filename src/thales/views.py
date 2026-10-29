from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from ninja import Router
from ninja.errors import HttpError
from helpers.api_auth import ThalesAccessJWTAuth
from thales.models import (
    AssistantInteraction,
    HypothesisNote,
    Lesson,
    ModelExperiment,
    StudentProgress,
)
from thales.molecular_data import get_all_bases
from thales.validation import MolecularValidator

router = Router(auth=[ThalesAccessJWTAuth()])


class ValidateBaseRequest(BaseModel):
    left_base: str
    right_base: str


class ProgressRequest(BaseModel):
    session_id: Optional[str] = None
    current_lesson: Optional[int] = None
    state_json: Optional[Dict[str, Any]] = None


class ModelExperimentRequest(BaseModel):
    session_id: Optional[str] = None
    left_base: str = Field(..., min_length=1, max_length=2)
    right_base: str = Field(..., min_length=1, max_length=2)
    model_state_json: Optional[Dict[str, Any]] = None
    validity_json: Optional[Dict[str, Any]] = None


class AssistantInteractionRequest(BaseModel):
    session_id: Optional[str] = None
    question: str = Field(..., min_length=1, max_length=20000)
    response: str = Field(..., min_length=1, max_length=20000)
    response_type: str = 'explanation'
    hint_level: int = Field(0, ge=0)
    simulation_year: int = 1952
    mode: str = Lesson.MYSTERY


class HypothesisRequest(BaseModel):
    text: str = Field(..., max_length=20000)


def _user_progress(request, session_id: Optional[str] = None) -> StudentProgress:
    """Return the caller's progress row, creating it on first activity.

    A supplied ``session_id`` still works for the older session API, but it
    cannot be used to read or write another learner's row. When it is omitted,
    each authenticated user gets one stable session of their own.
    """
    user = request.auth
    session_id = session_id or f'user-{user.pk}'
    username = user.get_username()

    progress, _ = StudentProgress.objects.get_or_create(
        session_id=session_id,
        defaults={'user_id': user.pk, 'username': username},
    )

    if progress.user_id is not None and progress.user_id != user.pk:
        raise HttpError(403, 'This session belongs to another user')

    changed = []
    if progress.user_id != user.pk:
        progress.user_id = user.pk
        changed.append('user_id')
    if progress.username != username:
        progress.username = username
        changed.append('username')
    if changed:
        progress.save(update_fields=changed + ['updated_at'])

    return progress


@router.get('/lessons/')
def list_lessons(request):
    """List all lessons."""
    lessons = Lesson.objects.all().values()
    return list(lessons)


@router.get('/lessons/{lesson_id}/')
def get_lesson(request, lesson_id: int):
    """Get a specific lesson."""
    try:
        lesson = Lesson.objects.get(id=lesson_id)
        return {
            'id': lesson.id,
            'title': lesson.title,
            'description': lesson.description,
            'mode': lesson.mode,
            'sequence_order': lesson.sequence_order,
            'content_json': lesson.content_json,
            'simulation_year': lesson.simulation_year,
        }
    except Lesson.DoesNotExist:
        raise HttpError(404, f'Lesson {lesson_id} not found')


@router.get('/molecular-data/')
def get_molecular_data(request):
    """Return molecular data for all bases."""
    return {'bases': get_all_bases()}


@router.post('/model/validate/')
def validate_model(request, payload: ValidateBaseRequest):
    """Validate a proposed base pair."""
    result = MolecularValidator.validate_base_pair(payload.left_base, payload.right_base)
    return result


@router.get('/progress/')
def get_progress(request, session_id: Optional[str] = None):
    """Get student progress."""
    progress = _user_progress(request, session_id)
    return {
        'id': progress.id,
        'session_id': progress.session_id,
        'user_id': progress.user_id,
        'username': progress.username,
        'current_lesson': progress.current_lesson_id,
        'completed_lessons': list(progress.completed_lessons.values_list('id', flat=True)),
        'state_json': progress.state_json,
        'updated_at': progress.updated_at.isoformat(),
    }


@router.post('/progress/')
def update_progress(request, payload: ProgressRequest):
    """Update student progress."""
    progress = _user_progress(request, payload.session_id)

    if payload.current_lesson:
        try:
            progress.current_lesson = Lesson.objects.get(id=payload.current_lesson)
        except Lesson.DoesNotExist:
            raise HttpError(404, f'Lesson {payload.current_lesson} not found')

    if payload.state_json is not None:
        progress.state_json = payload.state_json

    progress.save()

    return {
        'id': progress.id,
        'session_id': progress.session_id,
        'user_id': progress.user_id,
        'username': progress.username,
        'current_lesson': progress.current_lesson_id,
        'state_json': progress.state_json,
    }


@router.post('/model/save/')
def save_model_experiment(request, payload: ModelExperimentRequest):
    """Save a model experiment submitted from the build bench."""
    progress = _user_progress(request, payload.session_id)

    experiment = ModelExperiment.objects.create(
        progress=progress,
        username=progress.username,
        left_base=payload.left_base,
        right_base=payload.right_base,
        model_state_json=payload.model_state_json or {},
        validity_json=payload.validity_json or {}
    )

    return {
        'id': experiment.id,
        'progress_id': experiment.progress_id,
        'username': experiment.username,
        'left_base': experiment.left_base,
        'right_base': experiment.right_base,
        'timestamp': experiment.timestamp.isoformat(),
    }


@router.post('/assistant/save/')
def save_assistant_interaction(request, payload: AssistantInteractionRequest):
    """Save one advisor question and its answer."""
    response_types = {value for value, _ in AssistantInteraction.RESPONSE_TYPES}
    if payload.response_type not in response_types:
        raise HttpError(400, f'Unknown response_type: {payload.response_type}')

    modes = {value for value, _ in Lesson.MODE_CHOICES}
    if payload.mode not in modes:
        raise HttpError(400, f'Unknown mode: {payload.mode}')

    progress = _user_progress(request, payload.session_id)

    interaction = AssistantInteraction.objects.create(
        progress=progress,
        username=progress.username,
        question=payload.question,
        response=payload.response,
        response_type=payload.response_type,
        hint_level=payload.hint_level,
        simulation_year=payload.simulation_year,
        mode=payload.mode,
    )

    return {
        'id': interaction.id,
        'progress_id': interaction.progress_id,
        'username': interaction.username,
        'question': interaction.question,
        'response': interaction.response,
        'response_type': interaction.response_type,
        'timestamp': interaction.timestamp.isoformat(),
    }


@router.get('/hypothesis/')
def get_hypothesis(request):
    """Return the calling user's hypothesis note, or an empty one."""
    note = HypothesisNote.objects.filter(user_id=request.auth.id).first()
    if note is None:
        return {'text': '', 'username': request.auth.get_username(), 'updated_at': None}
    return {
        'text': note.text,
        'username': note.username,
        'updated_at': note.updated_at.isoformat(),
    }


@router.put('/hypothesis/')
def put_hypothesis(request, payload: HypothesisRequest):
    """Create or replace the calling user's hypothesis note."""
    note, _ = HypothesisNote.objects.update_or_create(
        user_id=request.auth.id,
        defaults={
            'text': payload.text,
            'username': request.auth.get_username(),
        },
    )
    return {
        'text': note.text,
        'username': note.username,
        'updated_at': note.updated_at.isoformat(),
    }
