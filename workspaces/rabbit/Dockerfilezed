FROM stereolabs/zed:5.0-tools-devel-jetson-jp6.0.0

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=src:/usr/local/lib/python3.10/dist-packages

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN apt-get update
RUN apt-get install -y draco

WORKDIR /rabbit
COPY pyproject.toml ./
RUN uv sync
