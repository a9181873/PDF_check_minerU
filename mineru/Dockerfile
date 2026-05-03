FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MINERU_MODEL_SOURCE=local

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && pip install "mineru[pipeline]" lxml

# Pre-download pipeline models from ModelScope at build time.
# Mount a named volume over /root/.cache/modelscope to reuse across rebuilds.
RUN MINERU_MODEL_SOURCE=modelscope mineru-models-download -s modelscope -m pipeline

EXPOSE 18080

CMD ["mineru-api", "--pipeline-backend", "pipeline", "--host", "0.0.0.0", "--port", "18080"]
