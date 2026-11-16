# ─── Builder ────────────────────────────────────────────────
# Poetry exists only here: it resolves the lockfile (main + hardware
# groups) into /app/.venv, which the prod stage copies wholesale. evdev
# and pyserial-asyncio (hardware group) need a C toolchain to build on
# arm64 -- most SBC architectures have no prebuilt wheel for them --
# hence build-essential + python3-dev here, dropped again in prod.
FROM python:3.13-slim AS builder

WORKDIR /app

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/*

# The same Poetry as CI (POETRY_VERSION in .github/workflows/ci.yml), the
# version that wrote poetry.lock. Bump both together.
ARG POETRY_VERSION=2.4.1

COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
    && poetry config virtualenvs.in-project true \
    && poetry install --no-root --only main,hardware

# ─── Prod stage ─────────────────────────────────────────────
# Fresh base: no poetry, no build toolchain, just the ready-made venv.
#
# Runs as root, deliberately: the bridge needs evdev's exclusive grab()
# on /dev/input/eventN and raw access to the scanner's serial device
# node, neither of which a fixed --uid non-root user reliably has without
# matching the host's input/dialout GIDs at build time, and those GIDs
# differ across DietPi images. This is a single-purpose kiosk container
# with no business logic and no auth checks (see CLAUDE.md), so the usual
# least-privilege tradeoff is deliberately relaxed here rather than
# fought with brittle GID-matching -- see docker-compose.yml's
# `privileged: true` on this service for the matching device-access side
# of the same tradeoff.
FROM python:3.13-slim AS prod

WORKDIR /app

# cec-ctl (v4l-utils) puts a TV into standby and wakes it over HDMI-CEC
# for POST /display (src/host/cec.py). The bridge reaches /dev/cec* as
# root through the /dev mount, like the RFID reader and the scanner.
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends v4l-utils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv ./.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY src/ ./src/
COPY pyproject.toml ./

EXPOSE 8600

# No curl in this minimal image; urllib is stdlib. Always resolves
# 127.0.0.1 to this container's own process regardless of BRIDGE__HOST.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8600/health', timeout=3)" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8600"]
