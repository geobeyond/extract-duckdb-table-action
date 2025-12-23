FROM debian:bookworm-slim

LABEL org.opencontainers.image.source="https://github.com/luipir/extract-duckdb-tables-action"
LABEL org.opencontainers.image.description="Extract DuckDB Tables Action - GitHub Action for extracting tables from DuckDB files"
LABEL org.opencontainers.image.authors="luipir"

# Install git for git history mode
RUN apt-get update
RUN apt-get install -y git python3 python3-venv python3-pip
RUN pip install --break-system-packages uv

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
