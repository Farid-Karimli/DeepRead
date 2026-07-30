FROM python:3.11-slim-bookworm

# PaperMage/OpenCV needs the X11/GL libraries. pdf2image needs Poppler.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    libsm6 \
    libxcb1 \
    libxext6 \
    libxrender1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv==0.11.6

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# The source tree is imported as `src`; the pyproject's historical package
# metadata names `deepread`, so install dependencies without building that
# project wheel.
RUN uv sync --frozen --no-dev --no-install-project \
    && rm -rf /root/.cache/uv

ENV PATH="/app/.venv/bin:$PATH"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home app \
    && mkdir -p \
        /app/temp \
        /app/tmp \
        /app/src/temp \
        /app/src/agentic_localization/cache \
    && chown -R app:app \
        /app/temp \
        /app/tmp \
        /app/src/temp \
        /app/src/agentic_localization/cache

USER app

EXPOSE 8000

# Default: API server (override in Compose for the Celery worker)
CMD ["python", "-m", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000"]
