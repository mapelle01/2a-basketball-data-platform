# FASE 13 — Container image for feb_score.
#
# Multi-stage: builder installs the runtime requirements; the final image ships
# only the application + deps (no build tooling). The app is a single Uvicorn
# worker by design (the dispatcher is synchronous and inline; the rate limiter is
# in-memory), so a cluster should run one container per replica and scale out by
# replicas — NOT by spawning many workers in one container.

FROM python:3.11-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src
COPY --from=builder /install /usr/local
WORKDIR /app
COPY src ./src
# JSON-Schema command contracts: the app resolves them as /app/contracts
# (CONTRACTS_ROOT = parents[3] / "contracts" from validation.py), so they must be
# shipped in the image, not just present in the build context.
COPY contracts ./contracts

# Non-root: the container runs as an unprivileged user.
RUN useradd --create-home --uid 1000 feb
USER feb

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

ENTRYPOINT ["python", "-m", "feb_score.server"]
