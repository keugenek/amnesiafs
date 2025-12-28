FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/workspace/src

# Install only essential runtime deps (no build tools)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fuse3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Use minimal requirements for smaller image
COPY requirements-minimal.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

COPY src /workspace/src
COPY tools /workspace/tools

ENTRYPOINT ["python", "-m", "cognitivefs"]
CMD ["--help"]
