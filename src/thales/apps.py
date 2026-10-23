from django.apps import AppConfig


class ThalesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'thales'

    def ready(self):
        # Registers the post_migrate receiver that creates the Thales group.
        from . import signals  # noqa: F401
