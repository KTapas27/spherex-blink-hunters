# Blink Hunters: container image for Google Cloud Run (or any Docker host).
#
# The pre-built cache/ (stamps + views for the 5 challenge targets) is baked into the image,
# so the demo targets load instantly with no archive access. New targets are still fetched
# live from IRSA / AWS S3 and cached inside the running container.
#
# Build the cache first on a machine with good internet:
#   .venv/bin/python scripts/precache.py --per-group 0
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/app \
    MPLCONFIGDIR=/tmp/matplotlib \
    BLINK_CACHE_DIR=/app/cache \
    PORT=8080

RUN useradd --create-home --uid 1000 app
WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app backend/ backend/
COPY --chown=app:app frontend/ frontend/
COPY --chown=app:app scripts/ scripts/
COPY --chown=app:app cache/ cache/

USER app
EXPOSE 8080

# One worker: view-building jobs and their progress are kept in process memory.
CMD ["sh", "-c", "exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
