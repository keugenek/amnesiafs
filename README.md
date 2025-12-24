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

## Development Status

Phase 1: FUSE Foundation (In Progress)
- Block device access layer
- On-disk format structures
- Basic FUSE skeleton

See plan: C:\Users\Admin\.claude\plans\typed-seeking-hammock.md
