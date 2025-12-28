FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fuse3 \
        libfuse3-dev \
        build-essential \
        pkg-config \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

COPY src /workspace/src
COPY tools /workspace/tools
COPY README.md /workspace/README.md
COPY docs /workspace/docs

ENTRYPOINT ["python", "-m", "cognitivefs"]
CMD ["--help"]
