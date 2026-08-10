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

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
