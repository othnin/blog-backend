import uuid
from typing import Optional, Dict, Any
from pydantic import BaseModel
from ninja import Router
from ninja.errors import HttpError
from thales.models import Lesson, StudentProgress, ModelExperiment
from thales.molecular_data import get_all_bases
from thales.validation import MolecularValidator

router = Router()


class ValidateBaseRequest(BaseModel):
    left_base: str
    right_base: str


class ProgressRequest(BaseModel):
    session_id: Optional[str] = None
    current_lesson: Optional[int] = None
    state_json: Optional[Dict[str, Any]] = None


class ModelExperimentRequest(BaseModel):
    session_id: str
    left_base: str
    right_base: str
    model_state_json: Optional[Dict[str, Any]] = None
    validity_json: Optional[Dict[str, Any]] = None


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
    if not session_id:
        session_id = str(uuid.uuid4())

    progress, _ = StudentProgress.objects.get_or_create(session_id=session_id)
    return {
        'id': progress.id,
        'session_id': progress.session_id,
        'current_lesson': progress.current_lesson_id,
        'completed_lessons': list(progress.completed_lessons.values_list('id', flat=True)),
        'state_json': progress.state_json,
        'updated_at': progress.updated_at.isoformat(),
    }


@router.post('/progress/')
def update_progress(request, payload: ProgressRequest):
    """Update student progress."""
    if not payload.session_id:
        raise HttpError(400, 'session_id required')

    progress, _ = StudentProgress.objects.get_or_create(session_id=payload.session_id)

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
        'current_lesson': progress.current_lesson_id,
        'state_json': progress.state_json,
    }


@router.post('/model/save/')
def save_model_experiment(request, payload: ModelExperimentRequest):
    """Save a model experiment."""
    try:
        progress = StudentProgress.objects.get(session_id=payload.session_id)
    except StudentProgress.DoesNotExist:
        progress = StudentProgress.objects.create(session_id=payload.session_id)

    experiment = ModelExperiment.objects.create(
        progress=progress,
        left_base=payload.left_base,
        right_base=payload.right_base,
        model_state_json=payload.model_state_json or {},
        validity_json=payload.validity_json or {}
    )

    return {
        'id': experiment.id,
        'progress_id': experiment.progress_id,
        'left_base': experiment.left_base,
        'right_base': experiment.right_base,
        'timestamp': experiment.timestamp.isoformat(),
    }
