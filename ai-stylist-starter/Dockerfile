FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# OpenCV native dependencies — python:slim images don't include X11/GL libs
# that opencv-contrib-python (pulled by mediapipe) needs at import time.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
RUN pip install --upgrade pip && pip install .

COPY . /app

# Download MediaPipe model files (pose + face landmarkers)
RUN python scripts/download_models.py
