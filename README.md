# CognitiveFS - AI-Native File System

A true FUSE-based file system with AI cognition built into every file operation.

## Project Structure

```
cognitivefs/
├── src/cognitivefs/         # Main package
│   ├── __init__.py
│   ├── blockdev.py          # Block device access layer
│   ├── diskformat.py        # On-disk format structures
│   ├── fuse_ops.py          # FUSE operations implementation
│   ├── knowledge_graph.py   # Knowledge graph core
│   ├── embeddings.py        # Embedding generation/storage
│   ├── agents.py            # Background processing agents
│   ├── virtual_paths.py     # .ai/ virtual directory handling
│   └── utils.py             # Utilities
├── tests/                   # Test suite
├── docs/                    # Documentation
├── tools/                   # Utility scripts
│   └── format_device.py     # Initialize raw device
└── requirements.txt         # Python dependencies
```

## Target Device

- 128GB USB SSD (DEXP SSD C100 128GB)
- Device path: `\\.\PHYSICALDRIVE1` (Windows)
- Raw device with custom on-disk format

## Platform Support

- **Windows**: WinFsp (FUSE-compatible)
- **WSL/Linux**: Native FUSE
- **Cross-platform**: Same Python codebase

## Installation

1. Install WinFsp (Windows): https://winfsp.dev/
2. Install dependencies: `pip install -r requirements.txt`
3. Format the device: `python tools/format_device.py`
4. Mount: `python -m cognitivefs mount`

## Docker Development

Docker support makes it easier to build a repeatable dev environment. Because FUSE
needs elevated privileges, containers must run with `/dev/fuse` and `SYS_ADMIN`.

### Build the image

```bash
docker build -t cognitivefs:dev .
```

### Use docker compose (recommended)

```bash
# Shows CLI help
docker compose run --rm cognitivefs --help

# List devices in the container
docker compose run --rm cognitivefs list

# Format a test image (file-backed device)
dd if=/dev/zero of=test.img bs=1M count=1024
docker compose run --rm cognitivefs format /workspace/test.img --force

# Mount the image (create a mountpoint first)
mkdir -p /workspace/mnt/cognitivefs
docker compose run --rm cognitivefs mount /workspace/test.img /workspace/mnt/cognitivefs --debug
```

### Makefile shortcuts

```bash
make docker-build
make docker-list
make docker-format DEVICE=/workspace/test.img
make docker-mount DEVICE=/workspace/test.img MOUNTPOINT=/workspace/mnt/cognitivefs
```

### Notes

- For raw devices, pass them through (e.g. `/dev/sdb`) and ensure the container
  has permission to access them.
- Running in Docker on macOS/Windows requires a Linux VM; FUSE passthrough may
  be limited.

## Development Status

Phase 1: FUSE Foundation (In Progress)
- Block device access layer
- On-disk format structures
- Basic FUSE skeleton

See plan: C:\Users\Admin\.claude\plans\typed-seeking-hammock.md
