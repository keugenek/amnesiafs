# CognitiveFS Implementation Guide

## Overview

CognitiveFS is implemented as a userspace filesystem using FUSE (Filesystem in Userspace) with a custom on-disk format optimized for AI-native operations.

## Architecture Layers

### Layer 0: Block Device Access (`blockdev.py`)

Provides low-level access to raw block devices across platforms:

**Windows:**
- Uses `win32file.CreateFile()` to open `\\.\PhysicalDriveN`
- Requires Administrator privileges
- Supports `FILE_FLAG_NO_BUFFERING` for direct I/O
- Uses `DeviceIoControl()` for device information

**Linux:**
- Uses standard `os.open()` with `O_DIRECT` flag
- Opens `/dev/sdX` or similar
- Requires root privileges

**Cross-platform:**
- Falls back to regular file I/O for testing
- Handles sector alignment for physical devices (512 bytes)
- Works with 4KB block size for efficiency

### Layer 1: On-Disk Format (`diskformat.py`)

Custom filesystem format optimized for knowledge storage:

```
Block Layout:
┌─────────────────────────────────────────────────┐
│ Superblock (1 block = 4KB)                      │
├─────────────────────────────────────────────────┤
│ Allocation Bitmap (4,095 blocks = 16MB)         │
├─────────────────────────────────────────────────┤
│ Inode Table (16,384 blocks = 64MB)              │
├─────────────────────────────────────────────────┤
│ Knowledge Graph Region (2M blocks = 8GB)        │
│ - SQLite database for entities & relationships  │
├─────────────────────────────────────────────────┤
│ Embedding Store (2M blocks = 8GB)               │
│ - FAISS index for vector search                 │
├─────────────────────────────────────────────────┤
│ Version Store (2.6M blocks = 10GB)              │
│ - Content-addressed storage (git-like)          │
├─────────────────────────────────────────────────┤
│ Data Blocks (~variable, rest of device)         │
│ - Actual file content                           │
├─────────────────────────────────────────────────┤
│ Journal (last 1% or 64MB min)                   │
│ - Write-ahead log for crash recovery            │
└─────────────────────────────────────────────────┘
```

**Superblock:**
- Magic number: `COGFS001`
- Version, timestamps, UUID
- Pointers to all regions
- Free block/inode counts

**Inodes:**
- 512 bytes each (8 per 4KB block)
- Standard metadata (size, timestamps, permissions)
- AI-specific fields:
  - `content_hash`: SHA256 for deduplication
  - `embedding_offset`: Location in embedding store
  - `knowledge_graph_id`: Link to knowledge graph
  - `mime_type`: Content type
  - Versioning information

**Allocation Bitmap:**
- One bit per block (0=free, 1=allocated)
- 16MB bitmap can track 128GB device
- Fast free block search

### Layer 2: FUSE Operations (`fuse_ops.py`)

Implements the FUSE interface:

**Current Status (Phase 1):**
- ✅ Basic mount/unmount
- ✅ Superblock read/write
- ✅ Root directory access
- ✅ Inode caching
- ⏳ Path lookup (TODO)
- ⏳ Directory operations (TODO)
- ⏳ File I/O (TODO)

**Planned Features:**
- Virtual paths (`.ai/` directory)
- Knowledge extraction on write
- AI-enhanced reads
- Background processing queue

## Raw Device Access on Windows

### Requirements

1. **Administrator Privileges:**
   - Physical drive access requires elevated privileges
   - Use "Run as Administrator" or UAC elevation

2. **Device Path Format:**
   ```
   \\.\PhysicalDrive0   # First physical drive (usually system)
   \\.\PhysicalDrive1   # Second drive (our 128GB SSD)
   \\.\PhysicalDrive2   # etc.
   ```

3. **Sector Alignment:**
   - Physical devices require 512-byte aligned reads/writes
   - Our 4KB blocks are naturally aligned (4096 = 512 × 8)

### Opening a Physical Drive

```python
import win32file
import win32con

# Open for read/write
handle = win32file.CreateFile(
    r'\\.\PhysicalDrive1',
    win32con.GENERIC_READ | win32con.GENERIC_WRITE,
    win32file.FILE_SHARE_READ,  # Allow concurrent readers
    None,
    win32con.OPEN_EXISTING,
    win32con.FILE_FLAG_NO_BUFFERING,  # Direct I/O
    None
)
```

### Common Issues

**Access Denied (Error 5):**
- Not running as Administrator
- Device locked by another process
- Solution: Run elevated, unmount any existing filesystems

**Incorrect Function (Error 1):**
- Misaligned reads/writes
- Wrong flags for the operation
- Solution: Ensure 512-byte alignment

## WSL Integration

### USB Passthrough

To access the physical drive from WSL:

1. **Install usbipd-win** (Windows):
   ```powershell
   winget install usbipd
   ```

2. **List USB devices:**
   ```powershell
   usbipd list
   ```

3. **Attach to WSL:**
   ```powershell
   usbipd attach --wsl --busid <BUSID>
   ```

4. **In WSL:**
   ```bash
   lsblk  # Should see the device (e.g., /dev/sdc)
   ```

### Alternative: Network Filesystem

Windows can run CognitiveFS and expose via SMB:
```
\\wsl$\Ubuntu\mnt\brain
```

## Testing Without Physical Device

For development, use a disk image file:

```bash
# Create 1GB test image
dd if=/dev/zero of=test.img bs=1M count=1024

# Format it
python tools/format_device.py test.img --force

# Mount it
python -m cognitivefs mount test.img /mnt/test
```

## Security Considerations

1. **Raw Device Access:**
   - Can read/write any sector
   - Bypasses filesystem permissions
   - **Never** run untrusted code with these privileges

2. **Data Validation:**
   - Always validate superblock magic
   - Check block numbers before access
   - Bounds checking on all I/O

3. **Crash Recovery:**
   - Journal for atomic operations
   - Superblock backup
   - Regular consistency checks

## Performance Optimization

1. **Block Size:**
   - 4KB matches SSD page size
   - Minimizes write amplification

2. **Caching:**
   - Inode cache in memory
   - Block cache for frequently accessed data
   - Metadata prefetch

3. **Async I/O:**
   - Write operations return immediately
   - Background queue for knowledge extraction
   - Batch writes to bitmap/inode table

## Next Steps

### Phase 1 Completion (Current)
- [x] Block device access layer
- [x] On-disk format structures
- [x] Basic FUSE skeleton
- [x] Format tool
- [ ] Path lookup implementation
- [ ] Basic read/write operations

### Phase 2: Core Operations
- [ ] Directory creation/deletion
- [ ] File creation/deletion
- [ ] Read/write file data
- [ ] Handle indirect blocks
- [ ] Implement journaling

### Phase 3: AI Integration
- [ ] Knowledge extraction pipeline
- [ ] SQLite knowledge graph setup
- [ ] Embedding generation
- [ ] Virtual `.ai/` paths

## Debugging

Enable debug output:
```bash
python -m cognitivefs mount \\.\PhysicalDrive1 K: --debug
```

Check device status:
```bash
python -m cognitivefs status \\.\PhysicalDrive1
```

List available devices:
```bash
python -m cognitivefs list
```

## References

- [WinFsp Documentation](https://winfsp.dev/doc/)
- [FUSE Documentation](https://www.kernel.org/doc/html/latest/filesystems/fuse.html)
- [Windows CreateFile API](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilea)
- [ext4 Disk Layout](https://ext4.wiki.kernel.org/index.php/Ext4_Disk_Layout)
