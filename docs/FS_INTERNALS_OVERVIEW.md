# AmnesiaFS / CognitiveFS Internals: Design, Implementation, and Intent

This document is a deep technical overview of AmnesiaFS (also referred to as CognitiveFS in the codebase). It focuses on the filesystem’s unique design goals, how those goals are realized in the implementation, and the architectural intent that drives the current structure.

> **Scope note:** The implementation is an evolving FUSE-based filesystem. Several subsystems are fully implemented (formatting, knowledge graph, extraction, embeddings, virtual AI paths, version control), while core file I/O and directory operations are still in-progress in the FUSE layer. This document aims to describe the *actual* code as it exists today, plus the architectural intent that it is clearly setting up.

---

## 1) Original Intent: An AI-Native Filesystem

AmnesiaFS is not a conventional filesystem plus optional “AI features.” The *filesystem itself* is designed to be AI-native. The intention is that every file operation can feed a semantic substrate (knowledge graph, embeddings, versions), and that AI-derived insights become first-class filesystem views rather than a bolted-on index.

The design intent manifests in three pillars:

1. **Persistent semantic state** embedded alongside file data (knowledge graph + embeddings + version snapshots).
2. **Low-friction AI interactions** through a virtual `.ai/` directory that exposes semantic APIs as regular filesystem paths.
3. **Predictable system behavior** by preserving classic filesystem concepts (superblock, inodes, block allocation) while extending them with AI-specific metadata.

---

## 2) Architectural Layers and Their Roles

### Layer 0: Raw Block Device Access

**Goal:** Ensure the filesystem can operate directly on physical devices (Windows / Linux) or disk images, with explicit alignment and device-size detection.

Implementation highlights (`src/cognitivefs/blockdev.py`):

- **Cross-platform device abstraction** with OS-specific I/O paths.
  - Windows: `win32file.CreateFile` for `\\.\PhysicalDriveN`, uses `FILE_FLAG_NO_BUFFERING` for raw I/O.
  - Linux: `os.open` with `O_DIRECT` for `/dev/sdX` devices when available.
- **Sector alignment enforcement** for physical devices in both read and write paths, with explicit error messages for misaligned access.
- **Device size discovery** via WMI on Windows, ioctl on Linux, and file size for disk images.

This layer isolates OS quirks so that higher layers can operate on predictable 4KB blocks.

### Layer 1: On-Disk Format and Layout

**Goal:** Define a filesystem layout that reserves space for semantic systems (graph + embeddings + version store) without breaking classic filesystem structures.

Implementation highlights (`src/cognitivefs/diskformat.py`):

- **4KB block size** (aligned with modern SSD page size).
- **Superblock** (block 0) storing layout pointers, filesystem UUID, timestamps, and free counts.
- **Allocation bitmap** tracking block usage bit-by-bit.
- **Fixed-size inodes** (512 bytes) with AI-augmented fields.
- **Regions for AI subsystems** (knowledge graph, embedding store, version store) mapped into the disk layout as first-class regions.

#### Layout Model

The layout is deterministic and block-addressable. A reference 128GB device uses fixed sizes for metadata/AI regions; smaller devices scale proportionally with minimum sizes enforced:

```
Superblock → Allocation Bitmap → Inode Table → Knowledge Graph → Embedding Store → Version Store → Data Blocks → Journal
```

Key design choices:

- **Knowledge Graph region:** intended for SQLite-backed graph storage.
- **Embedding store region:** reserved for vector indices.
- **Version store region:** allocated for content-addressed snapshots.
- **Journal region:** reserved at the tail (1% or ≥1MB) to support crash recovery.

#### AI-Augmented Inode Format

The inode structure extends traditional metadata with AI-specific fields:

- `content_hash` (SHA-256) for content identity and deduplication.
- `embedding_offset` + `embedding_dims` for vector storage mapping.
- `knowledge_graph_id` for linking files to graph entities.
- `mime_type` and `language` for semantic processing.
- `version_count` and `latest_version_hash` for integrated versioning.

These fields allow the filesystem to treat semantic data as part of the file’s native metadata, not external indexes.

### Layer 2: FUSE Operations and the System Orchestrator

**Goal:** Present the filesystem to the OS and route operations to the semantic and storage subsystems.

Implementation highlights (`src/cognitivefs/fuse_ops.py`):

- **CognitiveFS class** implements a FUSE `Operations` interface.
- **Mount-time initialization** loads the superblock, bitmap, root inode, knowledge graph, and versioning layer.
- **Filesystem caches** for inodes and directory entries to reduce disk reads.
- **Virtual AI handler** that intercepts `.ai` paths.

The FUSE layer is currently in-progress for full read/write path resolution, but the existing structure shows a clear orchestration point: raw device I/O + metadata updates + background AI processing + virtual path projection.

---

## 3) Semantic Subsystems

### Knowledge Graph (SQLite + FTS)

**Goal:** Persist semantic entities, relationships, and file metadata in a structured, queryable store.

Implementation highlights (`src/cognitivefs/knowledge_graph.py`):

- **SQLite-backed storage** with a first-class schema for files, entities, relationships, and embeddings.
- **FTS5 virtual table** (`files_fts`) for full-text search, synchronized by triggers on the `files` table.
- **Entity types** include humans, orgs, locations, topics, tags, and structured data keys/columns.
- **Relationships** support semantic and structural edges (mentions, similar_to, referenced_by, created_by, etc.).

The graph design is intentionally flexible: it combines strongly-typed fields for indexing and summary data with a `metadata` JSON field to preserve future evolution.

### Embedding Pipeline

**Goal:** Attach semantic embeddings to files and entities to power similarity search and clustering.

Implementation highlights (`src/cognitivefs/embedder.py`):

- **Sentence-transformers integration** with selectable models.
- **Lazy model loading** to avoid heavy startup overhead.
- **GPU/CPU auto-selection** when CUDA is available.
- **Embeddings stored as packed float32** for space efficiency.

This makes semantic similarity a first-class capability rather than an external index.

### Content & Entity Extraction

**Goal:** Convert arbitrary files into structured metadata and textual content for indexing.

Implementation highlights (`src/cognitivefs/extractor.py`):

- **MIME inference** via extensions and content heuristics.
- **Text extraction** for dozens of common text/code/config formats.
- **Regex-based entity detection** (names, emails, URLs, dates, code constructs, structured schema types).

This module forms the “front door” for content entering the knowledge graph and embedding pipeline.

### Background Processing Pipeline

**Goal:** Ensure AI work does not block filesystem operations.

Implementation highlights (`src/cognitivefs/processor.py`):

- **Background thread** that processes queued file updates.
- **Processing stages:** extraction → entity linking → embedding generation → graph updates.
- **Ignore rules** for version control directories, caches, and build artifacts.
- **Relationship detection** for semantic linking across files.

This architecture separates fast IO from compute-heavy AI tasks, aligning with the “filesystem first, AI second” philosophy.

---

## 4) Virtual AI Filesystem (`/.ai`)

**Goal:** Expose AI-native features as a filesystem interface, where “queries” become directories/files instead of API calls.

Implementation highlights (`src/cognitivefs/virtual_ai/`):

- `.ai` acts as a virtual root with specialized subtrees (status, search, query, entities, similar, versions, graph, by-topic, summary, related, chat, by-date).
- Each subtree is implemented by a handler class, all routed through a central `VirtualAIHandler`.
- These handlers return virtual directory entries and file content through standard FUSE `getattr`, `readdir`, and `read` operations.

### Dual-View Files

Every virtual AI directory auto-generates:

- `_DASHBOARD.html` → human-friendly rich visualization
- `_manifest.md` → YAML-frontmatter summary
- `_index.json` → machine-readable metadata

Implementation highlights (`src/cognitivefs/generators.py`):

- A **generator factory** produces content lazily on access.
- HTML dashboards embed CSS inline to avoid external dependencies.
- Files are cached with TTL for quick reloads.

This design turns semantic metadata into multi-consumer views without special tooling.

---

## 5) Transparent Version Control

**Goal:** Make every filesystem change versioned by default, while isolating versioning concerns from the user.

Implementation highlights (`src/cognitivefs/version_control.py`):

- Git repository created per filesystem (`.vcs`), with LFS integration for large files.
- **Automatic commits** on write/rename/delete operations.
- **Excluded prefixes** ensure virtual paths and repo internals aren’t recursively versioned.

The system treats versioning as part of the filesystem substrate, not an optional workflow.

---

## 6) Formatting & Initialization Path

**Goal:** Ensure the filesystem can be initialized on a raw device or an image, with correct layout and metadata.

Implementation highlights (`tools/format_device.py`):

- **Layout calculation** uses proportional scaling for smaller devices with minimum region sizes.
- **Superblock initialization** writes the filesystem UUID and region layout pointers.
- **Allocation bitmap** pre-allocates metadata and journal regions.
- **Root inode** is created to bootstrap directory access.

This tool operationalizes the disk format and validates that the block-level system can be initialized safely.

---

## 7) What’s Unique vs. Traditional Filesystems

| Capability | Traditional FS | AmnesiaFS Design Intent |
|------------|----------------|--------------------------|
| File identity | Path + inode | Path + inode + content hash + embedding ID |
| Search | Optional (external) | Built-in (FTS + embeddings) |
| Semantic metadata | External index | Native inode fields + graph storage |
| AI insights | Separate pipeline | First-class `.ai` virtual filesystem |
| Versioning | External VCS | Embedded git-backed version store |

The core differentiator: **semantic state is treated as primary filesystem data**, not an afterthought.

---

## 8) Current Status & Forward Path

The system already implements a fully coherent semantic stack, but the FUSE file I/O layer is still being completed. The architecture is explicit about the intended next steps:

- **Complete path lookup and directory operations** in the FUSE layer.
- **Bind real file writes** to queue-based AI extraction and versioning.
- **Implement journaling** for crash recovery and metadata integrity.

The scaffolding indicates a deliberate progression: stabilize low-level storage and metadata, then expand IO operations, and finally scale out the AI-native behaviors.

---

## 9) Summary: Why This Design Matters

AmnesiaFS rethinks what a filesystem can be. It does not just store bytes; it stores meaning. The internals are engineered to treat AI data as a *native* storage class (graph, embeddings, version history) while preserving the performance and determinism of classic filesystem design.

The result is a system where:

- Files automatically generate structured knowledge.
- Queries become filesystem paths.
- Semantic views are first-class artifacts.
- Version history is implicit and persistent.

This is not merely a filesystem with AI features—it is an attempt to make the filesystem itself **semantic infrastructure**.
