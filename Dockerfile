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

# resvg — the rasteriser that turns a rendered card into a publishable PNG.
# Pinned to the SAME version used on the development machine so a card that was
# eyeballed locally produces the same pixels in production. Not on PyPI as a
# usable wheel for this interpreter, so it comes from the upstream release,
# verified against its SHA-256 (an unpinned download is an unreviewed binary).
# Fetched with python's urllib rather than curl to avoid an apt layer.
ARG RESVG_VERSION=0.48.1
ARG RESVG_SHA256=fa8c26495a187e592c501db15bf9e8a9fdc051d4b2b336b39703d5b59f912b9d
RUN set -eu; \
    arch="$(uname -m)"; \
    if [ "$arch" != "x86_64" ]; then \
        echo "resvg release binaries are x86_64 only; this build is $arch" >&2; \
        exit 1; \
    fi; \
    url="https://github.com/linebender/resvg/releases/download/v${RESVG_VERSION}/resvg-linux-x86_64.tar.gz"; \
    python -c "import urllib.request,sys; urllib.request.urlretrieve(sys.argv[1], '/tmp/resvg.tgz')" "$url"; \
    echo "${RESVG_SHA256}  /tmp/resvg.tgz" | sha256sum -c -; \
    tar -xzf /tmp/resvg.tgz -C /usr/local/bin resvg; \
    rm /tmp/resvg.tgz; \
    chmod 0755 /usr/local/bin/resvg; \
    /usr/local/bin/resvg --version

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src
COPY --from=builder /install /usr/local
COPY --from=builder /usr/local/bin/resvg /usr/local/bin/resvg
WORKDIR /app
COPY src ./src
# JSON-Schema command contracts: the app resolves them as /app/contracts
# (CONTRACTS_ROOT = parents[3] / "contracts" from validation.py), so they must be
# shipped in the image, not just present in the build context.
COPY contracts ./contracts
# FASE 25 — server-side catalog backfill (backfill_catalog command): the official
# name resolvers late-import scripts/feb (ingest_match/discover_matches/
# backfill_catalog) at runtime, so the scripts must be shipped in the image.
COPY scripts ./scripts

# Non-root: the container runs as an unprivileged user.
RUN useradd --create-home --uid 1000 feb
USER feb

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

ENTRYPOINT ["python", "-m", "feb_score.server"]
