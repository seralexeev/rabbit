FROM ros:jazzy-ros-base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml ./

RUN uv sync

COPY src/ src/

CMD ["uv", "run", "src/main.py"]
