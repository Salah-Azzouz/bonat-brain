# Build arguments for custom base images
# ---------------------------------------
ARG PYTHON_BASE_ALPINE=python:3.10-alpine
ARG PYTHON_BASE_SLIM=python:3.11-slim
ARG PYTHON_DISTROLESS_RUNTIME=gcr.io/distroless/python3-debian12

# ============= ALPINE BUILDER STAGE =============
FROM ${PYTHON_BASE_ALPINE} AS alpine-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk add --no-cache --virtual .build-deps \
    gcc \
    g++ \
    musl-dev \
    postgresql-dev \
    python3-dev \
    rust \
    cargo \
    linux-headers \
    && rm -rf /var/cache/apk/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN apk del .build-deps


# ============= DEBIAN BUILDER STAGE =============
FROM ${PYTHON_BASE_SLIM} AS debian-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    pkg-config \
    libpq-dev \
    python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt


# ============= ALPINE PRODUCTION STAGE =============
FROM ${PYTHON_BASE_ALPINE} AS production-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH"

RUN apk add --no-cache \
    libgcc \
    libpq \
    && rm -rf /var/cache/apk/*

COPY --from=alpine-builder /opt/venv /opt/venv
WORKDIR /app
RUN addgroup -g 1001 appgroup && \
    adduser -D -u 1001 -G appgroup appuser && \
    chown -R appuser:appgroup /app
COPY --chown=appuser:appgroup . .
USER appuser

EXPOSE 8000
CMD ["python", "app.py"]


# ============= DISTROLESS PRODUCTION STAGE =============
FROM ${PYTHON_DISTROLESS_RUNTIME} AS production-distroless

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/usr/lib/python3.11/site-packages

# Copy site-packages to distroless Python path (both use Python 3.11 now)
COPY --from=debian-builder /opt/venv/lib/python3.11/site-packages /usr/lib/python3.11/site-packages

WORKDIR /app
COPY . .

EXPOSE 8000
CMD ["app.py"]

# ============= DEFAULT PRODUCTION STAGE =============
FROM production-alpine AS production
