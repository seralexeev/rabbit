FROM ubuntu:24.04

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV PYTHONUNBUFFERED=1

WORKDIR /rabbit
COPY pyproject.toml ./
RUN uv sync
COPY src/ src/

CMD ["uv", "run", "src/main.py"]
