FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY cloud_run/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY Python /app/Python
COPY codet5p_type_retrieval /app/codet5p_type_retrieval
COPY cloud_run /app/cloud_run

ENTRYPOINT ["python", "-m", "cloud_run.runner"]
