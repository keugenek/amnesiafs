# AmnesiaFS - AI-Native File System

A true FUSE-based file system with AI cognition built into every file operation. Features automatic knowledge graph construction, semantic search, and AI-powered file organization.

## Quick Start (Windows)

### Automatic Setup

```powershell
# Run setup script (installs WinFsp + dependencies)
.\setup.ps1

# Create and format a test image
python tools/format_device.py test.img --force

# Mount to K: drive
python tools/mount.py test.img K: --debug
```

### Manual Setup

1. **Install WinFsp** (required for FUSE on Windows):
   ```powershell
   winget install WinFsp.WinFsp
   ```

2. **Install Python dependencies**:
   ```powershell
   pip install fusepy pywin32 sqlalchemy lz4 networkx numpy rich pyyaml psutil

   # Optional: For AI embeddings (adds ~1GB)
   pip install sentence-transformers
   ```

3. **Format a test image** (or physical drive):
   ```powershell
   # Create 100MB test image
   python tools/format_device.py test.img --force

   # Or format a physical drive (CAUTION: erases all data!)
   # python tools/format_device.py \\.\PhysicalDrive1 --force
   ```

4. **Mount the filesystem**:
   ```powershell
   python tools/mount.py test.img K: --debug
   ```

5. **Use the filesystem**:
   - Copy files to `K:\` - they're automatically analyzed
   - Browse `K:\.ai\` for virtual AI-powered directories
   - Query: `K:\.ai\search\your query here`

## Features

- **Knowledge Graph**: Every file is analyzed and connected
- **Semantic Search**: Find files by meaning, not just name
- **Entity Extraction**: Automatic detection of people, places, concepts
- **Version History**: Built-in file versioning
- **Virtual AI Directory**: Access AI features through `.ai/` folder

## Project Structure

```
amnesiafs/
├── src/cognitivefs/         # Main package
│   ├── blockdev.py          # Block device access layer
│   ├── diskformat.py        # On-disk format structures
│   ├── fuse_ops.py          # FUSE operations implementation
│   ├── knowledge_graph.py   # Knowledge graph + SQLite storage
│   ├── embedder.py          # Embedding generation
│   ├── processor.py         # Background file processing
│   ├── virtual_ai.py        # .ai/ virtual directory
│   └── extractor.py         # Text/entity extraction
├── tools/                   # Utility scripts
│   ├── format_device.py     # Format disk/image
│   ├── mount.py             # Mount filesystem
│   └── verify_format.py     # Verify disk format
└── requirements.txt         # Python dependencies
```

## Embedding Models

AmnesiaFS uses sentence-transformers for semantic search. The default model is **BAAI/bge-base-en-v1.5** which provides excellent quality for local use.

### Available Models

| Model | Dimensions | Size | Quality | Speed |
|-------|------------|------|---------|-------|
| `BAAI/bge-base-en-v1.5` | 768 | ~440MB | Excellent | Good |
| `BAAI/bge-large-en-v1.5` | 1024 | ~1.3GB | Best | Slower |
| `all-mpnet-base-v2` | 768 | ~420MB | Very Good | Good |
| `all-MiniLM-L6-v2` | 384 | ~80MB | Good | Fast |
| `BAAI/bge-m3` | 1024 | ~2.3GB | Best (multilingual) | Slow |

### Changing the Model

Set the `COGNITIVEFS_EMBEDDING_MODEL` environment variable:

```powershell
# Use the large model for best quality
$env:COGNITIVEFS_EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
python tools/mount.py test.img K:

# Or use the fast model for lower-end hardware
$env:COGNITIVEFS_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
python tools/mount.py test.img K:
```

### GPU Acceleration

If you have an NVIDIA GPU with CUDA, embeddings will automatically use GPU acceleration. Install PyTorch with CUDA support:

```powershell
# Check if CUDA is available
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}')"

# Install PyTorch with CUDA (if not already installed)
pip install torch --index-url https://download.pytorch.org/whl/cu124
```

The mount log will show which device is being used:
```
Loading embedding model: BAAI/bge-base-en-v1.5
CUDA available: NVIDIA GeForce RTX 3080
Model loaded on cuda. Dimensions: 768
```

## Troubleshooting

### "FUSE library not installed"
```powershell
pip install fusepy
```

### "No module named 'win32file'"
```powershell
pip install pywin32
```

### "WinFsp not found" or mount hangs
```powershell
winget install WinFsp.WinFsp
# Restart terminal after installation
```

### "sentence-transformers not installed"
This is optional. Embeddings/semantic search will be disabled without it:
```powershell
pip install sentence-transformers  # ~1GB download
```

### Mount point already in use
```powershell
# Unmount first (close any Explorer windows to K:)
# Then re-mount
```

## Platform Support

- **Windows**: WinFsp + fusepy (primary target)
- **Linux**: Native FUSE
- **macOS**: macFUSE + fusepy
