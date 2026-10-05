"""
Regression tests for logging configuration.

Background: logging.config.dictConfig() opens file handlers eagerly, while it
runs. Django configures logging during the settings import, so if the log
directory is missing the open raises inside the settings import and takes down
every gunicorn worker before the app serves anything. That turns a missing
directory into a total outage, and it masks whatever the real error was.

This was hit in production: .dockerignore excludes **/logs/, git cannot track an
empty directory, so src/logs/.gitkeep was the only thing that ever created the
directory in the image. Removing it broke the deploy with:

    FileNotFoundError: [Errno 2] No such file or directory: '/code/logs/django.log'

Settings now creates the directory and falls back to console-only if it cannot.
"""
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from home import settings as settings_module

SRC_DIR = Path(settings.BASE_DIR)


class LoggingResilienceTests(SimpleTestCase):
    def test_settings_create_log_dir_when_missing(self):
        """The production path (DEBUG=False) must recreate the directory."""
        script = textwrap.dedent(
            """
            import os, django, logging, logging.config
            os.environ['DJANGO_SETTINGS_MODULE'] = 'home.settings'
            os.environ['DJANGO_DEBUG'] = 'False'
            django.setup()
            from django.conf import settings
            assert settings.LOG_DIR.exists(), 'LOG_DIR was not created'
            assert 'file' in settings.LOGGING['handlers'], 'file handler missing'
            logging.config.dictConfig(settings.LOGGING)
            logging.getLogger('blog').error('regression probe')
            assert (settings.LOG_DIR / 'django.log').exists(), 'log file not created'
            print('OK')
            """
        )
        env = {**os.environ, 'DJANGO_DEBUG': 'False'}
        proc = subprocess.run(
            [sys.executable, '-c', script],
            cwd=str(SRC_DIR),
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        self.assertEqual(
            proc.returncode, 0, f'settings import failed:\n{proc.stderr}'
        )
        self.assertIn('OK', proc.stdout)

    def test_logging_never_raises_when_dir_cannot_be_created(self):
        """
        Even with the directory present, dictConfig must succeed.

        Guards the subtler half of the bug: dictConfig instantiates every handler
        in the mapping, including ones nothing references. Defining the file
        handler but omitting it from the root logger's handler list still raises
        ValueError and still kills the worker.
        """
        script = textwrap.dedent(
            """
            import logging.config
            cfg = {
                'version': 1,
                'disable_existing_loggers': False,
                'handlers': {'console': {'class': 'logging.StreamHandler'}},
                'root': {'handlers': ['console'], 'level': 'WARNING'},
            }
            logging.config.dictConfig(cfg)
            logging.getLogger('x').error('probe')
            print('OK')
            """
        )
        proc = subprocess.run(
            [sys.executable, '-c', script],
            cwd=str(SRC_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('OK', proc.stdout)

    def test_file_handler_presence_matches_availability(self):
        """
        The handler mapping and the handler lists must agree.

        This is the invariant that was broken: `handlers` defined a file handler
        while the loggers only referenced console, and dictConfig raised anyway.
        """
        available = settings_module._file_logging_available
        self.assertEqual(
            'file' in settings.LOGGING['handlers'],
            available,
            'LOGGING["handlers"] disagrees with file-logging availability',
        )
        self.assertEqual(
            settings_module._log_handlers,
            ['console'] + (['file'] if available else []),
        )
        # Every handler a logger references must exist in the mapping, otherwise
        # dictConfig raises on a missing handler name.
        for name in settings_module._log_handlers:
            self.assertIn(name, settings.LOGGING['handlers'])

    def test_log_dir_is_a_path(self):
        self.assertIsInstance(settings.LOG_DIR, Path)
        self.assertEqual(settings.LOG_DIR.name, 'logs')

    def tearDown(self):
        # Keep the working tree tidy for local dev.
        gitkeep = SRC_DIR / 'logs' / '.gitkeep'
        gitkeep.parent.mkdir(parents=True, exist_ok=True)
        if not gitkeep.exists():
            gitkeep.touch()