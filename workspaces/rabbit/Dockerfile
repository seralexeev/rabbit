FROM stereolabs/zed:5.0-tools-devel-jetson-jp6.0.0

ENV PYTHONUNBUFFERED=1
    
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /rabbit
COPY pyproject.toml ./
RUN uv sync
