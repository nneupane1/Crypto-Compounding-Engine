FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RTS_PROJECT_ROOT=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt /app/requirements-prod.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements-prod.txt

COPY structural_compounding_lab /app/structural_compounding_lab
COPY production_api /app/production_api
COPY production_runtime /app/production_runtime

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "production_runtime.scheduler_loop"]

