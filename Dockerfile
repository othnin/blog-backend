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
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install os dependencies for our mini vm
RUN apt-get update && apt-get install -y \
    # for postgres
    libpq-dev \
    # for Pillow
    libjpeg-dev \
    # for CairoSVG
    libcairo2 \
    # other
    gcc \
    && rm -rf /var/lib/apt/lists/*

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
    printf "RUN_PORT=\"\${PORT:-8080}\"\n\n" >> ./paracord_runner.sh && \
    printf "python manage.py migrate --no-input\n" >> ./paracord_runner.sh && \
    printf "python manage.py collectstatic --noinput\n" >> ./paracord_runner.sh && \
    printf "if [ -n \"\$DJANGO_SUPERUSER_USERNAME\" ]; then\n" >> ./paracord_runner.sh && \
    printf "  python manage.py createsuperuser --noinput 2>/dev/null || true\n" >> ./paracord_runner.sh && \
    printf "  python manage.py shell -c \"from django.contrib.auth.models import User; u = User.objects.get(username='\$DJANGO_SUPERUSER_USERNAME'); u.set_password('\$DJANGO_SUPERUSER_PASSWORD'); u.save(); u.profile.role='admin'; u.profile.email_verified=True; u.profile.save()\" 2>/dev/null || true\n" >> ./paracord_runner.sh && \
    printf "fi\n" >> ./paracord_runner.sh && \
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

# Clean up apt cache to reduce image size
RUN apt-get remove --purge -y \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Run the Django project via the runtime script when the container starts.
# Exec form is required, not cosmetic: shell form would make `sh -c` PID 1, so
# SIGTERM on deploy/restart would go to sh instead of gunicorn and workers would
# be killed mid-request instead of draining. The script's own `exec gunicorn`
# then leaves gunicorn as PID 1. Docker flags this in JSONArgsRecommended.
CMD ["./paracord_runner.sh"]