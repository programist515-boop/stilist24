FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
RUN pip install --upgrade pip && pip install .

COPY . /app

# Download MediaPipe model files (pose + face landmarkers)
RUN python scripts/download_models.py
