FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# OpenCV native dependencies — python:slim images don't include X11/GL libs
# that opencv-contrib-python (pulled by mediapipe) needs at import time.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 libgles2 libegl1 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Two-step install so the slow wheels (mediapipe, rembg) stay cached across
# code edits. Step 1 installs runtime deps from pyproject.toml alone — setuptools
# will create an empty dist-info for the package itself, which we override next.
COPY pyproject.toml /app/pyproject.toml
RUN pip install --upgrade pip && pip install .

# Step 2 copies the source and reinstalls the package in editable mode so
# `import app.*` works from any cwd (pytest, alembic, scripts). --no-deps
# skips re-resolving the wheel set installed above.
COPY . /app
RUN pip install --no-deps -e .

# Download MediaPipe model files (pose + face landmarkers)
RUN python scripts/download_models.py
