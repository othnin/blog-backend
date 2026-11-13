import logging

from django.apps import AppConfig
from django.conf import settings


class ThalesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'thales'

    def ready(self):
        # Registers the post_migrate receiver that creates the Thales group.
        from . import signals  # noqa: F401
        from .advisor import config as advisor_config

        # Say which brain this process will talk to. Without this line a
        # missing/stale OLLAMA_BASE_URL is invisible: the advisor simply
        # answers 503 on every question while the logs blame "Ollama".
        logger = logging.getLogger('thales')
        logger.info(
            'Advisor brain: %s (timeout=%ss)',
            advisor_config.redact_url(advisor_config.OLLAMA_BASE_URL),
            advisor_config.OLLAMA_TIMEOUT,
        )
        if not settings.DEBUG and advisor_config.is_loopback(
            advisor_config.OLLAMA_BASE_URL
        ):
            logger.warning(
                'Advisor brain points at loopback in production (%s). '
                'Set OLLAMA_BASE_URL to the deployed runtime, or every '
                'advisor question will answer 503.',
                advisor_config.redact_url(advisor_config.OLLAMA_BASE_URL),
            )
