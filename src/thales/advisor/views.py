"""
Views for the genetics lab literature advisor API.

Connects the lab to a local Ollama instance, with period-correctness
enforcement (pre-April 1953 knowledge only), ANSWER_GUARD filtering, and
MAX_Q session limits.

Ported from thales2/llm_advisor/views.py (originally thales_old/server/
api/views.py), with in-memory session storage replaced by the AdvisorSession
model. Lives as a subpackage of the thales app (like molecules/), mounted
under /api/thales/advisor/ behind the lab's injected access auth, so only
lab users can spend questions against the model.
"""

import re
import uuid
import logging
import requests
from datetime import timedelta
from typing import Optional
from pydantic import BaseModel
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from thales.access import get_api_auth
from thales.models import AdvisorSession
from . import config

logger = logging.getLogger(__name__)
debug_llm = logging.getLogger('thales.advisor.debug')

router = Router(auth=[get_api_auth()])

# Request/Response models
class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    reply: str
    session_id: str
    questions_remaining: int
    answer_guard_fired: bool

class ResetRequest(BaseModel):
    session_id: Optional[str] = None

class ResetResponse(BaseModel):
    session_id: str
    questions_remaining: int

class HealthResponse(BaseModel):
    status: str

ANSWER_GUARD_REGEX = r"(double helix|two strands|two chains|antiparallel|base pair geometry|hydrogen bond.*(specific|pair)|final structure|the answer|what is the structure|solve(d)? the structure|what does dna look like|spiral structure|strands wound|two helical|helical.*pair|paired.*helix)"

SYSTEM_PROMPT = """You are a 1952 literature advisor to a researcher studying DNA structure.
You have access only to facts and concepts known before April 25, 1953.

KNOWN FACTS (publicly available in 1952):
- Chargaff's ratios: A ≈ T, G ≈ C in all organisms tested. No mechanism known yet.
- Photo 51 (Franklin/Wilkins): X-shaped diffraction pattern consistent with a helical structure.
  Spacing suggests a helix of diameter ~2 nm and turn repeat ~3.4 nm.
- Sugar-phosphate backbone: Established to be on the outside via chemical reasoning.
- DNA = genetic material: Avery, Hershey, Chase experiments (1944-1952).
- Pauling's triple-helix (1953): Published but widely believed to be incorrect.

ABSOLUTELY FORBIDDEN CONCEPTS (post-April-1953 discovery):
- Double helix structure
- Antiparallel strands
- Specific base-pair geometry (A-T/G-C molecular complementarity)
- Hydrogen bonding between bases (specific)
- The replication mechanism (semi-conservative, template-strand copy)
- ANY implication of "two strands wound around each other"

YOUR JOB:
You are a peer scientist from 1952. When asked about DNA's structure:
1. Redirect to the evidence: "Here's what the data shows..."
2. Flag what's unknown: "We don't yet have a mechanism for..."
3. REFUSE to speculate on the final structure or confirm/deny any proposed answer.
4. If directly asked for the structure, use this deflection: "That's not something anyone here can hand you outright — it's still unsolved, far as the published record goes. Tell me what evidence is pointing you that way, and I'll tell you whether it holds up against what we actually know."

IMPORTANT — AVOID FALSE OVERREACH:
- When describing experimental results (Avery, Hershey-Chase, Chargaff, etc.),
  do not generalize beyond what was established for the organisms/systems
  actually tested. Say "shown for [organism/system] here" rather than
  universal claims like "of all life" or "in every organism."
- Do not use absolute/conclusory phrasing like "this proves," "confirmed the
  final answer," "solved the mystery," or "the answer is" when describing a
  specific experimental result — describe it as evidence, not a settled
  conclusion.
- Never phrase things as "the answer" when discussing what an experiment
  showed; say "the evidence" or "what the experiment showed" instead.

Stay period-correct and Socratic. Help the student reason from evidence, not toward a predetermined answer."""

ANSWER_GUARD_FALLBACK = "That's not something anyone here can hand you outright — it's still unsolved, far as the published record goes. Tell me what evidence is pointing you that way, and I'll tell you whether it holds up against what we actually know."


def cleanup_old_sessions():
    """Remove sessions older than SESSION_TIMEOUT_HOURS."""
    cutoff = timezone.now() - timedelta(hours=config.SESSION_TIMEOUT_HOURS)
    deleted, _ = AdvisorSession.objects.filter(created_at__lt=cutoff).delete()
    if deleted:
        logger.info(f"Cleaned up {deleted} expired session(s)")


def filter_reply(model_reply):
    """
    Filter the model's reply through ANSWER_GUARD.

    Returns:
        (filtered_reply, guard_fired)
    """
    if re.search(ANSWER_GUARD_REGEX, model_reply, re.IGNORECASE):
        return ANSWER_GUARD_FALLBACK, True
    return model_reply, False


def query_ollama(model, question):
    """
    Query the Ollama instance for a response.

    Returns the reply text, or None if the request failed.
    """
    try:
        payload = {
            'model': model,
            'prompt': question,
            'system': SYSTEM_PROMPT,
            'stream': False,
            'temperature': 0.7,
        }
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        return result.get('response', '').strip()
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama query failed: {e}")
        return None


@router.get('/health/', response=HealthResponse)
def health(request):
    """Health check endpoint for client availability detection."""
    return {'status': 'ok'}


@router.post('/chat/', response=ChatResponse)
def chat(request, payload: ChatRequest):
    """
    Literature advisor chat endpoint.

    Expected request body:
        {
            "question": "...",
            "session_id": "..." (optional; generated if missing)
        }

    Response:
        {
            "reply": "...",
            "session_id": "...",
            "questions_remaining": N,
            "answer_guard_fired": bool
        }

    Returns 429 if question limit reached, 503 if Ollama is unreachable.
    """
    question = payload.question.strip()

    if not question:
        session_id = payload.session_id or 'unknown'
        debug_llm.debug(
            'question=""',
            extra={'session_id': session_id, 'reason_code': 'MALFORMED_REQUEST'}
        )
        raise HttpError(400, 'question is required')

    session_id = payload.session_id or str(uuid.uuid4())
    cleanup_old_sessions()

    session, _ = AdvisorSession.objects.get_or_create(session_id=session_id)

    if session.question_count >= config.MAX_Q:
        raise HttpError(429, 'question_limit_reached')

    session.question_count += 1
    session.save(update_fields=['question_count'])
    questions_remaining = config.MAX_Q - session.question_count

    model = config.MODEL_CONFIG.get('model', 'phi4-mini')

    logger.info(
        f"[{session_id}] Question {session.question_count}/{config.MAX_Q}: "
        f"{question[:60]}..."
    )

    reply = query_ollama(model, question)

    if reply is None:
        debug_llm.debug(
            f'question="{question[:100]}..."',
            extra={'session_id': session_id, 'reason_code': 'OLLAMA_UNREACHABLE'}
        )
        raise HttpError(
            503,
            'Ollama server is not responding. Is it running? (ollama serve)'
        )

    filtered_reply, guard_fired = filter_reply(reply)

    if guard_fired:
        logger.info(f"[{session_id}] ANSWER_GUARD deflected response")
        debug_llm.debug(
            f'question="{question[:100]}..." | caught="{reply[:100]}..."',
            extra={'session_id': session_id, 'reason_code': 'ANSWER_GUARD_FIRED'}
        )

    return {
        'reply': filtered_reply,
        'session_id': session_id,
        'questions_remaining': questions_remaining,
        'answer_guard_fired': guard_fired,
    }


@router.post('/reset/', response=ResetResponse)
def reset_session(request, payload: ResetRequest):
    """
    Reset the session (clears the session ID and question count).

    Optional request body:
        { "session_id": "..." }

    If session_id is provided, that session is cleared. Otherwise, a new session_id is returned.
    """
    session_id = payload.session_id

    if session_id:
        deleted, _ = AdvisorSession.objects.filter(session_id=session_id).delete()
        if deleted:
            logger.info(f"[{session_id}] Session reset")

    new_session_id = str(uuid.uuid4())
    AdvisorSession.objects.create(session_id=new_session_id, question_count=0)

    return {
        'session_id': new_session_id,
        'questions_remaining': config.MAX_Q,
    }
