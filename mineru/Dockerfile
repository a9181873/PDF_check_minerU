FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MINERU_HOME=/opt/mineru \
    MINERU_MODEL_SOURCE=local \
    MINERU_MODEL_SMALL_BACKEND=onnx \
    MINERU_DEVICE_MODE=cpu \
    OMP_NUM_THREADS=4

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*
COPY mineru/constraints-cpu.txt ./constraints-cpu.txt
RUN pip install "pip==26.1.2" && \
    pip install -c constraints-cpu.txt "mineru==4.0.12" && \
    pip check && \
    python -c "import importlib.metadata as m; bad=sorted(d.metadata['Name'] for d in m.distributions() if d.metadata['Name'].lower().startswith(('nvidia-', 'cuda-', 'torch'))); assert not bad, bad; print('MinerU ONNX CPU runtime verified')"
COPY mineru/verify_models.py ./verify_models.py

FROM runtime AS final
# Only the basic ONNX bundle is needed on the CPU-only OCI deployment.
ARG MODEL_DOWNLOAD_SOURCE=huggingface
RUN mineru-kit models download --tier basic --small-backend onnx --source "$MODEL_DOWNLOAD_SOURCE" && \
    python ./verify_models.py
EXPOSE 18080
CMD ["mineru-api", "--tier", "basic", "--concurrency", "1", "--host", "0.0.0.0", "--port", "18080"]
