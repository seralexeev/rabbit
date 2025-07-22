FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
    
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV PYTHONUNBUFFERED=1

WORKDIR /rabbit
COPY pyproject.toml ./
RUN uv sync
COPY src/ src/

CMD ["uv", "run", "src/main.py"]
