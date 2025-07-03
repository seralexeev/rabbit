FROM ros:jazzy-ros-base

SHELL ["/bin/bash", "-c"]
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /rabbit

COPY pyproject.toml ./
RUN uv sync
COPY src/ src/

CMD ["uv", "run", "src/main.py"]
