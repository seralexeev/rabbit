FROM python:3.13-slim

RUN apt update && apt install -y --no-install-recommends \
    build-essential \
    libgpiod-dev \
    libevdev-dev \
    libffi-dev \
    libusb-1.0-0-dev \
    i2c-tools \
    curl \
    git \
    ffmpeg \
    v4l-utils \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && apt clean && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml ./

RUN uv sync

EXPOSE 8080