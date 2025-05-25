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
    && apt clean && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync