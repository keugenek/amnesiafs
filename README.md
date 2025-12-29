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

### ✅ Fully Working
- **Knowledge Graph**: SQLite + FTS5 with entities, relationships, embeddings
- **Entity Extraction**: 10 types (PERSON, ORG, LOCATION, DATE, etc.) via regex
- **Semantic Search**: Embedding-based similarity with BAAI/bge models
- **Text Extraction**: 30+ file types including JSON, CSV, YAML parsing
- **Background Processing**: Async file analysis on write
- **Virtual AI Directory**: `.ai/` folder with query, status, search, entities
- **Dual-View Files**: Auto-generated `_DASHBOARD.html`, `_manifest.md`, `_index.json` in each `.ai/` folder
- **Transparent Version Control**: Git-backed versioning of all files with LFS support

### ⚠️ Partial/Basic
- **Topic Clustering**: Infrastructure exists, limited auto-population
- **Related Files**: Shows similar files but basic implementation
- **LLM Queries**: Works with Ollama but requires external setup

### ❌ Not Yet Implemented
- **LLM Summaries**: Disabled for stability (shows file preview only)
- **Multi-Modal**: No image/video/audio processing yet
- **Version Browser**: `/.ai/versions/` virtual paths not yet exposed
- **Graph Visualization**: Returns help text only

## Virtual AI Paths (`.ai/`)

When mounted, browse `K:\.ai\` for AI-powered virtual directories:

| Path | Status | Description |
|------|--------|-------------|
| `.ai/status/` | ✅ Working | System status JSON (files, entities, queue) |
| `.ai/query/<question>` | ✅ Working | Async LLM query (requires Ollama) |
| `.ai/search/<text>` | ✅ Working | Full-text search with snippets |
| `.ai/entities/` | ✅ Working | List all extracted entities |
| `.ai/related/<file>` | ⚠️ Basic | Find similar files by embedding |
| `.ai/similar/<file>` | ⚠️ Basic | Embedding similarity search |
| `.ai/summary/<file>` | ❌ Disabled | Shows preview only (LLM disabled) |
| `.ai/by-topic/` | ⚠️ Basic | Topic clusters (limited) |
| `.ai/by-date/` | ❌ Stub | Not fully implemented |
| `.ai/chat/` | ⚠️ Basic | Session handling infrastructure |
| `.ai/graph/` | ❌ Stub | Returns help text only |

**Example usage:**
```powershell
# Check system status
type K:\.ai\status\index.txt

# Search for files
dir K:\.ai\search\machine learning

# List entities
dir K:\.ai\entities\

# Find related files (requires embeddings)
dir K:\.ai\related\myfile.txt
```

## Dual-View Files (NEW)

Every `.ai/` subdirectory automatically contains three generated files:

| File | For | Description |
|------|-----|-------------|
| `_DASHBOARD.html` | Humans | Rich visual dashboard - open in browser |
| `_manifest.md` | Both | Readable summary with YAML frontmatter |
| `_index.json` | Agents | Structured JSON metadata |

```powershell
# Open visual dashboard in browser
start K:\.ai\status\_DASHBOARD.html

# Read manifest (human + agent friendly)
type K:\.ai\status\_manifest.md

# Parse JSON for automation
type K:\.ai\status\_index.json | ConvertFrom-Json
```

The dashboard includes:
- File count, total size, topic distribution
- Entity word cloud
- Recent files with metadata
- Dark theme, no external dependencies

## Transparent Version Control (NEW)

All file changes are automatically versioned using git under the hood:

```powershell
# Version control repo created at: test.vcs/ (alongside test.img)
# Every write, rename, delete is tracked automatically
# Large files (>10MB) use Git LFS
```

**What's versioned:**
- All real files (documents, code, media)
- Directory creation/deletion
- File renames and moves

**What's NOT versioned:**
- `.ai/` paths (virtual, computed on-the-fly)

The git repo is stored at `<image>.vcs/` (e.g., `test.vcs/` for `test.img`).

## Project Structure

```
amnesiafs/
├── src/cognitivefs/         # Main package
│   ├── blockdev.py          # Block device access layer
│   ├── diskformat.py        # On-disk format structures
│   ├── fuse_ops.py          # FUSE operations implementation
│   ├── knowledge_graph.py   # Knowledge graph + SQLite storage
│   ├── embedder.py          # Embedding generation (6 models, CUDA)
│   ├── processor.py         # Background file processing
│   ├── virtual_ai.py        # .ai/ virtual directory handler
│   ├── generators.py        # Dual-view file generators (NEW)
│   ├── version_control.py   # Git-backed versioning (NEW)
│   ├── extractor.py         # Text/entity extraction (30+ types)
│   ├── llm.py               # Ollama LLM integration
│   └── relationship_detector.py  # Co-occurrence & similarity
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
