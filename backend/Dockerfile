# FloodOps backend — lean by default; optional ML stack via --build-arg INCLUDE_ML=true.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps kept minimal (curl for the healthcheck only).
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 1) Lean Python deps (fast, no GDAL/torch).
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 2) Optional semantic-memory stack — installed AND model weights pre-downloaded
#    only when INCLUDE_ML=true, so a network-isolated container's first recall
#    doesn't fail. Default lean image runs recall disabled (returns []), not broken.
ARG INCLUDE_ML=false
COPY requirements-ml.txt ./
RUN if [ "$INCLUDE_ML" = "true" ]; then \
        pip install -r requirements-ml.txt && \
        python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" ; \
    fi

# App code.
COPY floodops ./floodops

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "floodops.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
