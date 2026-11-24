# syntax=docker/dockerfile:1
FROM python:3.12.16-slim-bookworm@sha256:b1233897230b2046795042a642dc2a1849774c60469bb57d1a90622b501443a0

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/home/app \
    SUPERMARKET_FRONTEND_DIR=/app/frontend

# Runtime tools: curl for the healthcheck, Tesseract (German) for the
# optional receipt-image OCR path. Single layer, no apt lists retained.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        tesseract-ocr \
        tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*

# uv from the official image (no pip bootstrap needed).
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /uvx /bin/

WORKDIR /app

# Layer 1: dependencies only. Rebuilt only when pyproject.toml/uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Layer 2: application code, modular PWA frontend and the project itself.
COPY supermarket_comparison ./supermarket_comparison
COPY frontend ./frontend
RUN python -m compileall -q supermarket_comparison \
    && uv sync --frozen --no-dev

# Fail the build early when the receipt-image OCR path is not usable:
# both the Python packages and the German Tesseract language data must exist.
RUN python -c "import pytesseract, PIL; print('ocr-imports-ok')" \
    && tesseract --list-langs 2>/dev/null | grep -qx deu

# Non-root runtime user with a fixed UID/GID (1000) so the bind-mounted
# ./data directory can simply be chowned to 1000:1000 on the host.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/app \
        --shell /usr/sbin/nologin app \
    && mkdir -p /app/data /app/.cache \
    && chown -R app:app /app/data /app/.cache /home/app \
    && chmod -R a+rX /app/frontend

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS --max-time 5 http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "supermarket_comparison.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
