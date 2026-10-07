# Set the python version as a build-time argument
# with Python 3.12 as the default
ARG PYTHON_VERSION=3.12-slim-bookworm
FROM python:${PYTHON_VERSION}

# Create a virtual environment
RUN python -m venv /opt/venv

# Set the virtual environment as the current location
ENV PATH=/opt/venv/bin:$PATH

# Upgrade pip
RUN pip install --upgrade pip

# Set Python-related environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# No apt packages, and deliberately none.
#
# This image used to `apt-get install libpq-dev libjpeg-dev libcairo2 gcc`,
# which added roughly 240 MB of build tooling and -dev headers to the runtime
# layer. None of it is needed, because every dependency resolves to a prebuilt
# manylinux wheel, so nothing is ever compiled:
#
#   gcc         pip builds no sdist here, so it is never invoked.
#   libpq-dev   psycopg-binary bundles its own libpq
#               (psycopg_binary.libs/libpq-*.so.5), resolved from the venv
#               rather than /usr/lib.
#   libjpeg-dev Pillow's wheels bundle jpeg, zlib and freetype, confirmed with
#               PIL.features inside this image.
#   libcairo2   cairosvg was never in requirements.txt and nothing imports it,
#               so this pulled in cairo, pixman, fontconfig and X libs for
#               nothing.
#
# Verified after removal: the image builds, boots, serves, and the full test
# suite passes inside it.
#
# If a future dependency ever needs compiling, pip will fail the build loudly
# with a missing-header error. That is the preferable outcome to a runtime
# image carrying a compiler, or to a multi-stage build whose venv silently links
# against a library that was never copied into the final stage.

# Create the mini vm's code directory
RUN mkdir -p /code

# Set the working directory to that same code directory
WORKDIR /code

# Copy the requirements file into the container
COPY requirements.txt /tmp/requirements.txt

# copy the project code into the container's working directory
COPY ./src /code

# Install the Python project requirements
RUN pip install -r /tmp/requirements.txt

# database isn't available during build
# run any other commands that do not need the database
# such as:
# RUN python manage.py collectstatic --noinput

# set the Django default project name
ARG PROJ_NAME="home"

# create a bash script to run the Django project
# this script will execute at runtime when
# the container starts and the database is available
RUN printf "#!/bin/bash\n" > ./paracord_runner.sh && \
    printf "# Abort on the first failure. Without this the script runs migrate,\n" >> ./paracord_runner.sh && \
    printf "# collectstatic and gunicorn in sequence regardless of exit status, so a\n" >> ./paracord_runner.sh && \
    printf "# failed migration (a transient Neon blip, a revoked credential) is\n" >> ./paracord_runner.sh && \
    printf "# swallowed and gunicorn serves traffic against an unmigrated database.\n" >> ./paracord_runner.sh && \
    printf "# ensure_superuser reads DJANGO_SUPERUSER_* from os.environ itself, so no\n" >> ./paracord_runner.sh && \
    printf "# shell variable is dereferenced here (which is why 'set -u' would be safe).\n" >> ./paracord_runner.sh && \
    printf "# It creates the bootstrap admin only when the account is missing and never\n" >> ./paracord_runner.sh && \
    printf "# touches an existing one — no password is stored in the environment.\n" >> ./paracord_runner.sh && \
    printf "set -e\n" >> ./paracord_runner.sh && \
    printf "RUN_PORT=\"\${PORT:-8080}\"\n\n" >> ./paracord_runner.sh && \
    printf "python manage.py migrate --no-input\n" >> ./paracord_runner.sh && \
    printf "python manage.py collectstatic --noinput\n" >> ./paracord_runner.sh && \
    printf "python manage.py ensure_superuser\n" >> ./paracord_runner.sh && \
    printf "echo \"Django setup complete. Starting gunicorn on port \$RUN_PORT...\"\n" >> ./paracord_runner.sh && \
    printf "GUNICORN_WORKERS=\"\${WEB_CONCURRENCY:-2}\"\n" >> ./paracord_runner.sh && \
    printf "GUNICORN_WORKER_CLASS=\"\${GUNICORN_WORKER_CLASS:-gthread}\"\n" >> ./paracord_runner.sh && \
    printf "GUNICORN_THREADS=\"\${GUNICORN_THREADS:-4}\"\n" >> ./paracord_runner.sh && \
    printf "GUNICORN_TIMEOUT=\"\${GUNICORN_TIMEOUT:-120}\"\n" >> ./paracord_runner.sh && \
    printf "GUNICORN_MAX_REQUESTS=\"\${GUNICORN_MAX_REQUESTS:-10000}\"\n" >> ./paracord_runner.sh && \
    printf "GUNICORN_MAX_REQUESTS_JITTER=\"\${GUNICORN_MAX_REQUESTS_JITTER:-1000}\"\n" >> ./paracord_runner.sh && \
    printf "exec gunicorn ${PROJ_NAME}.wsgi:application --bind \"0.0.0.0:\$RUN_PORT\" --workers \"\$GUNICORN_WORKERS\" --worker-class \"\$GUNICORN_WORKER_CLASS\" --threads \"\$GUNICORN_THREADS\" --timeout \"\$GUNICORN_TIMEOUT\" --max-requests \"\$GUNICORN_MAX_REQUESTS\" --max-requests-jitter \"\$GUNICORN_MAX_REQUESTS_JITTER\"\n" >> ./paracord_runner.sh

# make the bash script executable
RUN chmod +x paracord_runner.sh

# Run the Django project via the runtime script when the container starts.
# Exec form is required, not cosmetic: shell form would make `sh -c` PID 1, so
# SIGTERM on deploy/restart would go to sh instead of gunicorn and workers would
# be killed mid-request instead of draining. The script's own `exec gunicorn`
# then leaves gunicorn as PID 1. Docker flags this in JSONArgsRecommended.
CMD ["./paracord_runner.sh"]