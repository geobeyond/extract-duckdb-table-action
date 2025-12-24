FROM debian:bookworm-slim

LABEL org.opencontainers.image.source="https://github.com/luipir/extract-duckdb-tables-action"
LABEL org.opencontainers.image.description="Extract DuckDB Tables Action - GitHub Action for extracting tables from DuckDB files"
LABEL org.opencontainers.image.authors="luipir"

# Install git for git history mode
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates=20230601 curl=8.2.1-1 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
RUN apt-get install --no-install-recommends -y git=2.43.0 python3=3.12.0-1 python3-venv=3.12.0-1 python3-pip=23.0.1-4 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --break-system-packages uv==1.9.8

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy
# Ensure installed tools can be executed out of the box
ENV UV_TOOL_BIN_DIR=/usr/local/bin

COPY pyproject.toml uv.lock /
RUN uv sync --locked --no-dev

COPY src /src
ENV PATH="/.venv/bin:$PATH"
ENTRYPOINT ["python", "/src/main.py"]
