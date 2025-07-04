FROM ubuntu:24.04

RUN apt-get update
RUN apt-get install -y --no-install-recommends libgl1 libglib2.0-0
RUN rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /rabbit
COPY pyproject.toml ./
RUN uv sync
COPY src/ src/

CMD ["uv", "run", "src/main.py"]
