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
from urllib.parse import urlsplit, urlunsplit

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

# Seconds the advisor waits for the model runtime to answer before giving up
# (the desk then falls back to its offline advisor). 60 is comfortable for a
# local Ollama; a serverless runtime can need longer on a cold start, so a
# deploying host may raise this.
OLLAMA_TIMEOUT = getattr(
    settings,
    "THALES_ADVISOR_OLLAMA_TIMEOUT",
    config("OLLAMA_TIMEOUT", cast=int, default=60),
)

# Seconds the deep health probe waits for the runtime before reporting it
# offline. A sleeping serverless runtime is woken by the probe itself, so the
# first probe can report offline while the container starts; a second probe a
# couple of minutes later reports online.
OLLAMA_PROBE_TIMEOUT = getattr(
    settings,
    "THALES_ADVISOR_OLLAMA_PROBE_TIMEOUT",
    config("OLLAMA_PROBE_TIMEOUT", cast=int, default=10),
)

# Seconds a background warm-up may wait for the runtime to come up. This is
# deliberately longer than OLLAMA_TIMEOUT: a cold Modal start takes ~150 s,
# and nothing user-facing waits on this — it only decides when the warm-up
# thread gives up.
OLLAMA_WARM_TIMEOUT = getattr(
    settings,
    "THALES_ADVISOR_OLLAMA_WARM_TIMEOUT",
    config("OLLAMA_WARM_TIMEOUT", cast=int, default=180),
)

# Don't start another background warm-up within this many seconds of the last
# one finishing. The brain stays warm for its scaledown window (15 min), so a
# warm-up per page mount would only duplicate work.
OLLAMA_WARM_COOLDOWN = getattr(
    settings,
    "THALES_ADVISOR_OLLAMA_WARM_COOLDOWN",
    config("OLLAMA_WARM_COOLDOWN", cast=int, default=60),
)


def redact_url(url):
    """Return ``url`` safe to log, hiding the brain's auth token.

    The Modal brain gates itself with a token in the first path segment
    (``https://<workspace>--<label>.modal.run/<token>``), so a raw base URL
    in a log line would leak the only credential protecting GPU time. Bare
    URLs such as ``http://localhost:11434`` have no path and pass through
    unchanged.
    """
    parts = urlsplit(url)
    segments = [segment for segment in parts.path.split('/') if segment]
    if not segments:
        return url
    segments[0] = '<redacted>'
    return urlunsplit((parts.scheme, parts.netloc, '/' + '/'.join(segments), '', ''))


def is_loopback(url):
    """True when ``url`` points at this machine (localhost/127.0.0.1/::1)."""
    return (urlsplit(url).hostname or '') in ('localhost', '127.0.0.1', '::1')


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
