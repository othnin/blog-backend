"""App-local settings for the literature advisor.

The advisor deliberately owns its own configuration instead of requiring
entries in the host project's settings: this whole app must stay movable to
another Django project without touching that project's settings file.

Resolution order for every value: a ``THALES_ADVISOR_*`` Django setting
(the host's override), then the environment variable, then the hardcoded
default below.
"""

import json
from pathlib import Path

from django.conf import settings
from decouple import config

# Questions a learner may spend per session.
MAX_Q = getattr(
    settings, "THALES_ADVISOR_MAX_Q", 5
)

# Sessions older than this are deleted on the next chat request.
SESSION_TIMEOUT_HOURS = getattr(
    settings, "THALES_ADVISOR_SESSION_TIMEOUT_HOURS", 1
)

# The advisor queries a local Ollama instance (phi4-mini by default). When
# Ollama is unreachable the frontend silently falls back to its offline
# keyword advisor, so this default is safe on every host — including Railway,
# where no Ollama exists until OLLAMA_BASE_URL points at one.
OLLAMA_BASE_URL = getattr(
    settings,
    "THALES_ADVISOR_OLLAMA_BASE_URL",
    config("OLLAMA_BASE_URL", cast=str, default="http://localhost:11434"),
)


def get_model_config():
    """Resolve the active Ollama model name.

    Resolution order (first match wins):
    1. ADVISOR_MODEL environment variable
    2. thales/advisor/config.json (shipped next to this module)
    3. fallback default: 'phi4-mini'
    """
    model = config("ADVISOR_MODEL", cast=str, default="")
    if model:
        return {"model": model}

    config_path = Path(__file__).resolve().parent / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)

    return {"model": "phi4-mini"}


MODEL_CONFIG = get_model_config()
