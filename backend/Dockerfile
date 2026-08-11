# Build context is the repo root (see docker-compose.yml) so this image can
# also carry ai/face_recognition/ and ai/fraud_detection/ — both imported
# in-process at runtime (face_service.py, attendance_service.py) and need to
# be siblings of backend/, same layout as the local dev checkout.
FROM python:3.11-slim

WORKDIR /app

# opencv-python (pulled in transitively by insightface, which hard-requires the
# full GUI build, not headless) needs these shared libs — absent from the slim
# base image and otherwise fails at import time with "libxcb.so.1: cannot open
# shared object file".
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY ai/face_recognition/ ai/face_recognition/
COPY ai/fraud_detection/ ai/fraud_detection/
# alembic.ini + migrations live outside backend/ but ship in the same image so
# a platform preDeployCommand can run `alembic upgrade head` against them.
COPY database/ database/

# Bake insightface's buffalo_l weights into the image (downloads to
# ~/.insightface/models, same path pipeline.py's warm_up() checks at
# runtime) instead of fetching ~288MB from GitHub on every cold container
# start. Trades build-time network dependency for consistent, fast deploys.
RUN python -c "import sys; sys.path.insert(0, '/app/ai'); from face_recognition.pipeline import warm_up; warm_up()"

WORKDIR /app/backend

EXPOSE 8000

# Migration runs as part of container startup, not Railway's separate
# preDeployCommand — that mechanism gave zero log visibility on failure
# (confirmed: railway.json's preDeployCommand failed with no captured
# stdout/stderr in either the dashboard or CLI). Folding it into CMD means
# a migration failure shows up in ordinary deploy logs, which are captured.
# Shell form (not exec/JSON-array) so $PORT actually expands.
CMD cd /app/database && alembic upgrade head && cd /app/backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
