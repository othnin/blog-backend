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
import unittest
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
        # Settings now refuse to fall back to SQLite when DEBUG is off, and this
        # subprocess deliberately runs with DEBUG=False because that is the
        # production path under test. The subprocess never opens a database
        # connection, so a dummy Neon URL satisfies the guard while preserving
        # the DEBUG=False condition the test actually cares about.
        env = {
            **os.environ,
            'DJANGO_DEBUG': 'False',
            'DATABASE_URL': (
                'postgresql://user:pass@ep-example-pooler.'
                'us-east-2.aws.neon.tech/neondb?sslmode=require'
            ),
        }
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


@unittest.skipUnless(
    (SRC_DIR.parent / 'requirements.txt').exists()
    and (SRC_DIR.parent / 'Dockerfile').exists(),
    'build files are not present in this environment (e.g. inside the '
    'image, where only src/ is copied to /code)',
)
class GunicornDeploymentConfigTests(SimpleTestCase):
    """
    Guards the production WSGI configuration.

    Two classes of regression are checked here, both of which fail quietly:

    1. An unpinned `pip install gunicorn` in the Dockerfile. It bypasses
       requirements.txt, so the image stops being reproducible and dependency
       scanners, which read requirements.txt, never see gunicorn at all.
    2. Gunicorn left on its defaults. --timeout defaults to 30s, which this app
       can exceed given image processing and outbound email/S3 calls, and
       --max-requests defaults to unlimited, so a slow memory leak accumulates
       for the life of the container.
    """

    REPO_DIR = SRC_DIR.parent
    REQUIREMENTS = SRC_DIR.parent / 'requirements.txt'
    DOCKERFILE = SRC_DIR.parent / 'Dockerfile'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.requirements_text = cls.REQUIREMENTS.read_text()
        cls.dockerfile_text = cls.DOCKERFILE.read_text()

    def test_gunicorn_is_pinned_in_requirements(self):
        pins = [
            line.strip()
            for line in self.requirements_text.splitlines()
            if line.strip().lower().startswith('gunicorn')
        ]
        self.assertEqual(
            len(pins),
            1,
            f'expected exactly one gunicorn pin in requirements.txt, got {pins}',
        )
        pin = pins[0]
        self.assertIn('>=', pin, f'gunicorn needs a lower bound: {pin}')
        self.assertIn(
            '<',
            pin,
            f'gunicorn needs an upper bound so a major release cannot land '
            f'untested in production: {pin}',
        )

    def test_dockerfile_does_not_install_packages_ad_hoc(self):
        offenders = [
            line.strip()
            for line in self.dockerfile_text.splitlines()
            if 'pip install' in line
            and '-r' not in line
            and '--upgrade' not in line
            and not line.strip().endswith('pip install --upgrade pip')
        ]
        self.assertEqual(
            offenders,
            [],
            'packages must be installed via requirements.txt so the build is '
            f'reproducible and scannable. Offending line(s): {offenders}',
        )

    def test_gunicorn_launch_sets_tuning_flags(self):
        launch_lines = [
            line
            for line in self.dockerfile_text.splitlines()
            if 'gunicorn' in line and 'wsgi:application' in line
        ]
        self.assertEqual(
            len(launch_lines),
            1,
            f'expected one gunicorn launch line, found {launch_lines}',
        )
        launch = launch_lines[0]
        for flag in (
            '--workers',
            '--worker-class',
            '--threads',
            '--timeout',
            '--max-requests',
            '--max-requests-jitter',
        ):
            self.assertIn(
                flag,
                launch,
                f'gunicorn launch is missing {flag}: {launch}',
            )

    def test_gunicorn_flags_are_env_overridable(self):
        # Hardcoded values would mean a retune forces a rebuild; each flag reads
        # from the environment with a default instead.
        for var in (
            'GUNICORN_WORKER_CLASS',
            'GUNICORN_THREADS',
            'GUNICORN_TIMEOUT',
            'GUNICORN_MAX_REQUESTS',
            'GUNICORN_MAX_REQUESTS_JITTER',
        ):
            self.assertIn(
                var,
                self.dockerfile_text,
                f'{var} should be overridable without rebuilding the image',
            )

    def test_worker_class_supports_concurrency(self):
        # The default worker class is `sync`, which serves exactly one request
        # per worker at a time. With 2 workers that is 2 concurrent requests
        # site-wide, and an image upload blocks its worker entirely.
        self.assertIn('gthread', self.dockerfile_text)
        self.assertNotIn(
            '--worker-class sync',
            self.dockerfile_text,
            'sync workers serialise the whole site behind 2 connections',
        )

    def test_entrypoint_aborts_on_the_first_failure(self):
        # paracord_runner.sh runs migrate, then collectstatic, then gunicorn.
        # Without `set -e` a failed migration does not stop the script: it logs
        # "Django setup complete" and starts serving traffic against a database
        # that was never migrated. That is exactly what happens when Neon drops
        # the connection mid-deploy, and it is invisible from the outside.
        self.assertRegex(
            self.dockerfile_text,
            r'printf "set -e',
            'the generated entrypoint must abort on the first failing command',
        )
        self.assertNotIn(
            'set -euo',
            self.dockerfile_text,
            'set -u would break the optional superuser block, which reads '
            'DJANGO_SUPERUSER_USERNAME without a default',
        )


class DatabaseFallbackTests(SimpleTestCase):
    """
    Guards against the silent SQLite fallback reaching production.

    Settings used to fall back to SQLite whenever DATABASE_URL was unset. In
    production that does not raise: `manage.py migrate` builds a fresh, empty
    database inside the container, gunicorn boots, the healthcheck passes, and
    the site serves an empty blog whose logins all fail and whose writes vanish
    on the next deploy. Every replica would hold its own private database.

    Production uses Neon Postgres behind PgBouncer, so the only correct outcome
    with no DATABASE_URL is a loud failure at import time.
    """

    def _run_settings(self, script, **env_overrides):
        env = {
            **os.environ,
            'DJANGO_DEBUG': 'False',
            'DATABASE_URL': '',
            'DJANGO_SETTINGS_MODULE': 'home.settings',
        }
        # Removed rather than set to '0': production has no DJANGO_ALLOW_SQLITE
        # variable at all, so leaving it defined here would let the env override
        # do the guard's job and make these tests pass for the wrong reason.
        env.pop('DJANGO_ALLOW_SQLITE', None)
        env.update(env_overrides)
        return subprocess.run(
            [sys.executable, '-c', textwrap.dedent(script)],
            cwd=str(SRC_DIR),
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    def test_production_without_database_url_refuses_to_start(self):
        proc = self._run_settings(
            """
            import django
            django.setup()
            print('SHOULD NOT REACH HERE')
            """
        )
        combined = proc.stdout + proc.stderr
        self.assertNotIn(
            'SHOULD NOT REACH HERE',
            combined,
            'settings imported successfully with no DATABASE_URL in production',
        )
        self.assertIn(
            'ImproperlyConfigured',
            combined,
            f'expected an ImproperlyConfigured error, got:\n{combined}',
        )
        self.assertIn(
            'DATABASE_URL',
            combined,
            f'the error should name the missing variable, got:\n{combined}',
        )

    def test_error_message_names_the_neon_pooler_host(self):
        # The message tells an operator what to actually paste, including the
        # "-pooler" host. Getting this wrong sends them to the direct host, which
        # Neon limits far more aggressively.
        proc = self._run_settings(
            """
            import django
            django.setup()
            """
        )
        self.assertIn('-pooler', proc.stdout + proc.stderr)

    def test_sqlite_still_works_for_local_development(self):
        proc = self._run_settings(
            """
            import django
            django.setup()
            from django.conf import settings
            assert settings.DATABASES['default']['ENGINE'] == \\
                'django.db.backends.sqlite3', settings.DATABASES
            print('OK')
            """,
            DJANGO_ALLOW_SQLITE='1',
        )
        self.assertIn('OK', proc.stdout, proc.stdout + proc.stderr)

    def test_debug_mode_needs_no_database_url_or_escape_hatch(self):
        """The everyday local-dev path must keep working with zero env setup."""
        proc = self._run_settings(
            """
            import django
            django.setup()
            from django.conf import settings
            assert settings.DATABASES['default']['ENGINE'] == \\
                'django.db.backends.sqlite3', settings.DATABASES
            print('OK')
            """,
            DJANGO_DEBUG='True',
        )
        self.assertIn('OK', proc.stdout, proc.stdout + proc.stderr)

    def test_database_url_wins_over_sqlite_permission(self):
        # Setting DATABASE_URL must always select Postgres, even when the
        # SQLite escape hatch is also enabled.
        proc = self._run_settings(
            """
            import django
            django.setup()
            from django.conf import settings
            engine = settings.DATABASES['default']['ENGINE']
            assert engine == 'django.db.backends.postgresql', engine
            print('OK')
            """,
            DJANGO_ALLOW_SQLITE='1',
            DATABASE_URL=(
                'postgresql://user:pass@ep-example-pooler.'
                'us-east-2.aws.neon.tech/neondb?sslmode=require'
            ),
        )
        self.assertIn('OK', proc.stdout, proc.stdout + proc.stderr)

    def test_neon_tls_options_are_preserved(self):
        # sslmode/channel_binding must reach psycopg via OPTIONS, otherwise the
        # Neon connection is not encrypted.
        proc = self._run_settings(
            """
            import django
            django.setup()
            from django.conf import settings
            options = settings.DATABASES['default'].get('OPTIONS') or {}
            assert options.get('sslmode') == 'require', options
            print('OK')
            """,
            DATABASE_URL=(
                'postgresql://user:pass@ep-example-pooler.'
                'us-east-2.aws.neon.tech/neondb?sslmode=require'
                '&channel_binding=require'
            ),
        )
        self.assertIn('OK', proc.stdout, proc.stdout + proc.stderr)

    def test_neon_connections_are_kept_warm(self):
        # conn_max_age keeps client connections warm on PgBouncer; without it
        # every request pays a fresh TLS handshake to Neon.
        proc = self._run_settings(
            """
            import django
            django.setup()
            from django.conf import settings
            db = settings.DATABASES['default']
            assert db['CONN_MAX_AGE'] == 300, db.get('CONN_MAX_AGE')
            assert db['CONN_HEALTH_CHECKS'] is True, db.get('CONN_HEALTH_CHECKS')
            print('OK')
            """,
            DATABASE_URL=(
                'postgresql://user:pass@ep-example-pooler.'
                'us-east-2.aws.neon.tech/neondb?sslmode=require'
            ),
        )
        self.assertIn('OK', proc.stdout, proc.stdout + proc.stderr)
