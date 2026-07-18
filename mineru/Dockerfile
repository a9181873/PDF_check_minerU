FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91 AS runtime

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

COPY mineru/constraints-cpu.txt ./constraints-cpu.txt

RUN pip install "pip==26.1.2" && \
    pip install \
      --index-url https://download.pytorch.org/whl/cpu \
      --extra-index-url https://pypi.org/simple \
      -c constraints-cpu.txt \
      "torch==2.12.1+cpu" \
      "torchvision==0.27.1+cpu" && \
    pip install \
      --extra-index-url https://download.pytorch.org/whl/cpu \
      -c constraints-cpu.txt \
      "mineru[pipeline]==3.4.0" \
      "lxml==6.1.1" \
      "six==1.17.0" && \
    pip check && \
    python -c "import importlib.metadata as m, torch; bad=sorted({(d.metadata.get('Name') or '').lower() for d in m.distributions() if (d.metadata.get('Name') or '').lower().startswith(('nvidia-', 'cuda-'))}); assert torch.version.cuda is None and torch.__version__.endswith('+cpu'), torch.__version__; assert not bad, bad; print('MinerU CPU runtime:', torch.__version__)"

FROM runtime AS final

# Pre-download pipeline models from ModelScope at build time.
RUN MINERU_MODEL_SOURCE=modelscope mineru-models-download -s modelscope -m pipeline

COPY mineru/verify_models.py ./verify_models.py

# Fail the image build if mineru.json or any required pipeline model is absent.
RUN python ./verify_models.py

EXPOSE 18080

CMD ["mineru-api", "--pipeline-backend", "pipeline", "--host", "0.0.0.0", "--port", "18080"]
