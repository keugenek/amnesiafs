"""
FUSE Operations Implementation

Implements the FUSE filesystem interface for CognitiveFS.
Handles all file operations and routes to appropriate handlers.
"""

import os
import sys
import errno
import stat
import time
import struct
from typing import Optional, List, Dict, Tuple
from pathlib import Path

try:
    # Prefer refuse for better Windows/WinFsp support
    from refuse.high import FUSE, Operations, FuseOSError
except ImportError:
    try:
        from fuse import FUSE, Operations, FuseOSError
    except ImportError:
        # Fallback - define minimal interface for development
        class FuseOSError(OSError):
            def __init__(self, errno_val, msg=""):
                super().__init__(errno_val, msg)
                self.errno = errno_val

        class Operations:
            pass

        FUSE = None


from .blockdev import BlockDevice, BlockDeviceError
from .diskformat import Superblock, Inode, InodeType, InodeFlags, AllocationBitmap, BLOCK_SIZE
from .virtual_ai import VirtualAIHandler
from .knowledge_graph import KnowledgeGraph, FileRecord, Entity, EntityType


# Directory entry format: inode_num (8 bytes) + name_len (2 bytes) + name (variable)
DIR_ENTRY_HEADER_SIZE = 10  # 8 + 2
MAX_NAME_LEN = 255


class DirectoryEntry:
    """Represents a directory entry."""

    def __init__(self, inode_num: int, name: str):
        self.inode_num = inode_num
        self.name = name

    def pack(self) -> bytes:
        """Serialize directory entry."""
        name_bytes = self.name.encode('utf-8')[:MAX_NAME_LEN]
        return struct.pack('<QH', self.inode_num, len(name_bytes)) + name_bytes

    @classmethod
    def unpack(cls, data: bytes) -> Tuple['DirectoryEntry', int]:
        """Deserialize directory entry. Returns (entry, bytes_consumed)."""
        if len(data) < DIR_ENTRY_HEADER_SIZE:
            return None, 0

        inode_num, name_len = struct.unpack('<QH', data[:DIR_ENTRY_HEADER_SIZE])

        if inode_num == 0:  # Empty entry
            return None, 0

        total_len = DIR_ENTRY_HEADER_SIZE + name_len
        if len(data) < total_len:
            return None, 0

        name = data[DIR_ENTRY_HEADER_SIZE:total_len].decode('utf-8')
        return cls(inode_num, name), total_len

    def size(self) -> int:
        """Return serialized size of this entry."""
        return DIR_ENTRY_HEADER_SIZE + len(self.name.encode('utf-8'))


def get_device_size_wmi(device_path: str) -> int:
    """Get device size via WMI (Windows only)."""
    if sys.platform != 'win32':
        return 0
    try:
        import wmi
        import re
        match = re.search(r'PhysicalDrive(\d+)', device_path)
        if match:
            drive_num = int(match.group(1))
            c = wmi.WMI()
            for disk in c.Win32_DiskDrive():
                if disk.Index == drive_num:
                    return int(disk.Size) if disk.Size else 0
    except Exception:
        pass
    return 0


class CognitiveFS(Operations):
    """
    CognitiveFS FUSE operations.

    Implements a FUSE filesystem with AI-native features.
    """

    def __init__(self, device_path: str, debug: bool = False):
        """
        Initialize CognitiveFS.

        Args:
            device_path: Path to block device
            debug: Enable debug logging
        """
        self.device_path = device_path
        self.debug = debug
        self.device: Optional[BlockDevice] = None
        self.superblock: Optional[Superblock] = None
        self.bitmap: Optional[AllocationBitmap] = None

        # In-memory inode cache
        self.inode_cache: Dict[int, Inode] = {}

        # Directory entry cache: inode_num -> list of DirectoryEntry
        self.dir_cache: Dict[int, List[DirectoryEntry]] = {}

        # File handle counter
        self.fh_counter = 0
        self.open_files: Dict[int, Tuple[int, int]] = {}  # fh -> (inode_num, flags)

        # Data cache for open files
        self.file_data_cache: Dict[int, bytearray] = {}  # inode_num -> data

        # Root directory inode
        self.ROOT_INODE = 1

        # Knowledge graph
        self.knowledge_graph: Optional[KnowledgeGraph] = None

        # Background processor for knowledge extraction
        self.processor = None

        # Virtual AI directory handler
        self.virtual_ai = VirtualAIHandler(self)

    def init(self, path):
        """Initialize filesystem on mount."""
        self._log(f"Mounting CognitiveFS from {self.device_path}")

        # Get device size via WMI first (Windows)
        device_size = get_device_size_wmi(self.device_path)

        # Open block device
        self.device = BlockDevice(self.device_path, read_only=False)
        self.device.open()

        # Override size if WMI provided it
        if self.device.size == 0 and device_size > 0:
            self.device.size = device_size

        # Read superblock
        superblock_data = self.device.read_block(0)
        self.superblock = Superblock.unpack(superblock_data)

        if not self.superblock.is_valid():
            self._log(f"Invalid superblock! Magic={self.superblock.magic}, Version={self.superblock.version}")
            self._log("This usually means the device wasn't opened with admin privileges")
            raise FuseOSError(errno.EIO)

        # Update mount time
        self.superblock.mounted_at = int(time.time())
        self.device.write_block(0, self.superblock.pack())
        self.device.sync()

        # Load allocation bitmap
        bitmap_data = self._read_bitmap()
        self.bitmap = AllocationBitmap.from_bytes(bitmap_data, self.superblock.total_blocks)

        # Load root inode
        root_inode = self._read_inode(self.ROOT_INODE)
        if not root_inode:
            raise FuseOSError(errno.EIO)

        # Initialize knowledge graph
        self._init_knowledge_graph()

        self._log(f"Filesystem mounted successfully (UUID: {self.superblock.uuid.hex()})")

    def destroy(self, path):
        """Cleanup on unmount."""
        self._log("Unmounting CognitiveFS")

        # Stop background processor
        if self.processor:
            self._log("Stopping background processor")
            self.processor.stop()
            self.processor = None

        # Close knowledge graph
        if self.knowledge_graph:
            self.knowledge_graph.close()
            self.knowledge_graph = None

        if self.device:
            # Write back any cached data
            self._flush_all()
            self.device.sync()
            self.device.close()

    def _init_knowledge_graph(self):
        """Initialize the knowledge graph database."""
        # Store KG database alongside the device/image
        if self.device_path.endswith('.img'):
            kg_path = self.device_path.replace('.img', '.kg.db')
        else:
            # For physical devices, store in user's data directory
            import os
            uuid_hex = self.superblock.uuid.hex()
            data_dir = os.path.join(os.path.expanduser('~'), '.cognitivefs')
            os.makedirs(data_dir, exist_ok=True)
            kg_path = os.path.join(data_dir, f'{uuid_hex}.kg.db')

        self._log(f"Opening knowledge graph at {kg_path}")
        self.knowledge_graph = KnowledgeGraph(kg_path)
        self.knowledge_graph.open()

        # Connect to virtual AI handler
        self.virtual_ai.knowledge_graph = self.knowledge_graph

        # Initialize background processor for knowledge extraction
        self._init_processor()

    def _init_processor(self):
        """Initialize the background processor for knowledge extraction."""
        try:
            from .processor import BackgroundProcessor
            from .extractor import ContentExtractor
            from .embedder import EmbeddingGenerator

            self.processor = BackgroundProcessor(
                knowledge_graph=self.knowledge_graph,
                content_extractor=ContentExtractor(),
                embedding_generator=EmbeddingGenerator()
            )
            self.processor.start()
            self._log("Background processor started")
        except Exception as e:
            self._log(f"Warning: Failed to start background processor: {e}")
            self.processor = None

    def _log(self, msg: str):
        """Debug logging."""
        if self.debug:
            print(f"[CognitiveFS] {msg}", file=sys.stderr)

    # ============================================
    # Block and Inode Management
    # ============================================

    def _read_bitmap(self) -> bytes:
        """Read allocation bitmap from disk."""
        bitmap_bytes = self.superblock.bitmap_blocks * self.device.BLOCK_SIZE
        offset = self.superblock.bitmap_start * self.device.BLOCK_SIZE
        return self.device.read_bytes(offset, bitmap_bytes)

    def _write_bitmap(self):
        """Write allocation bitmap to disk."""
        offset = self.superblock.bitmap_start * self.device.BLOCK_SIZE
        self.device.write_bytes(offset, self.bitmap.to_bytes())

    def _read_inode(self, inode_num: int) -> Optional[Inode]:
        """Read inode from disk."""
        if inode_num in self.inode_cache:
            return self.inode_cache[inode_num]

        # Calculate inode position
        inodes_per_block = self.device.BLOCK_SIZE // Inode.INODE_SIZE
        block_offset = inode_num // inodes_per_block
        inode_offset = inode_num % inodes_per_block

        block_num = self.superblock.inode_table_start + block_offset
        block_data = self.device.read_block(block_num)

        inode_start = inode_offset * Inode.INODE_SIZE
        inode_data = block_data[inode_start:inode_start + Inode.INODE_SIZE]

        inode = Inode.unpack(inode_data)

        if inode.inode_num == 0:  # Empty inode
            return None

        self.inode_cache[inode_num] = inode
        return inode

    def _write_inode(self, inode: Inode):
        """Write inode to disk."""
        # Update cache
        self.inode_cache[inode.inode_num] = inode

        # Calculate inode position
        inodes_per_block = self.device.BLOCK_SIZE // Inode.INODE_SIZE
        block_offset = inode.inode_num // inodes_per_block
        inode_offset = inode.inode_num % inodes_per_block

        block_num = self.superblock.inode_table_start + block_offset

        # Read full block, modify inode, write back
        block_data = bytearray(self.device.read_block(block_num))
        inode_start = inode_offset * Inode.INODE_SIZE
        block_data[inode_start:inode_start + Inode.INODE_SIZE] = inode.pack()

        self.device.write_block(block_num, bytes(block_data))

    def _allocate_block(self) -> int:
        """Allocate a new data block."""
        # Find a free block starting from data blocks region
        block = self.bitmap.find_free_block(self.superblock.data_blocks_start)
        if block is None:
            raise FuseOSError(errno.ENOSPC)
        self.bitmap.allocate(block)
        self.superblock.free_blocks -= 1
        return block

    def _free_block(self, block_num: int):
        """Free a data block."""
        self.bitmap.free(block_num)
        self.superblock.free_blocks += 1

    def _allocate_inode(self) -> int:
        """Allocate a new inode number."""
        max_inodes = self.superblock.inode_table_blocks * (self.device.BLOCK_SIZE // Inode.INODE_SIZE)

        for inode_num in range(2, max_inodes):  # Start from 2 (1 is root)
            if inode_num not in self.inode_cache:
                inode = self._read_inode(inode_num)
                if inode is None or inode.inode_num == 0:
                    self.superblock.free_inodes -= 1
                    return inode_num

        raise FuseOSError(errno.ENOSPC)

    def _flush_all(self):
        """Flush all cached data."""
        # Write all dirty file data
        for inode_num, data in self.file_data_cache.items():
            self._write_file_data(inode_num, bytes(data))

        # Write bitmap
        self._write_bitmap()

        # Write superblock
        self.device.write_block(0, self.superblock.pack())

    # ============================================
    # Directory Operations
    # ============================================

    def _read_directory(self, inode: Inode) -> List[DirectoryEntry]:
        """Read directory entries from inode."""
        if inode.inode_num in self.dir_cache:
            return self.dir_cache[inode.inode_num]

        entries = []

        # Read data blocks containing directory entries
        data = self._read_file_data(inode)

        offset = 0
        while offset < len(data):
            entry, consumed = DirectoryEntry.unpack(data[offset:])
            if entry is None:
                break
            entries.append(entry)
            offset += consumed

        self.dir_cache[inode.inode_num] = entries
        return entries

    def _write_directory(self, inode: Inode, entries: List[DirectoryEntry]):
        """Write directory entries to inode."""
        # Serialize all entries
        data = b''.join(entry.pack() for entry in entries)

        # Pad to block boundary
        padded_len = ((len(data) + BLOCK_SIZE - 1) // BLOCK_SIZE) * BLOCK_SIZE
        data = data.ljust(padded_len, b'\x00')

        # Write data blocks
        self._write_file_data_to_inode(inode, data)

        # Update cache
        self.dir_cache[inode.inode_num] = entries

    def _add_directory_entry(self, parent_inode: Inode, name: str, child_inode_num: int):
        """Add entry to directory."""
        entries = self._read_directory(parent_inode)
        entries.append(DirectoryEntry(child_inode_num, name))
        self._write_directory(parent_inode, entries)

    def _remove_directory_entry(self, parent_inode: Inode, name: str) -> Optional[int]:
        """Remove entry from directory. Returns removed inode number."""
        entries = self._read_directory(parent_inode)

        for i, entry in enumerate(entries):
            if entry.name == name:
                removed_inode = entry.inode_num
                entries.pop(i)
                self._write_directory(parent_inode, entries)
                return removed_inode

        return None

    def _lookup_in_directory(self, parent_inode: Inode, name: str) -> Optional[int]:
        """Look up name in directory. Returns inode number or None."""
        entries = self._read_directory(parent_inode)

        for entry in entries:
            if entry.name == name:
                return entry.inode_num

        return None

    # ============================================
    # Path Resolution
    # ============================================

    def _resolve_path(self, path: str) -> Optional[Inode]:
        """Resolve path to inode."""
        if path == '/':
            return self._read_inode(self.ROOT_INODE)

        # Split path into components
        parts = [p for p in path.split('/') if p]

        current_inode = self._read_inode(self.ROOT_INODE)

        for part in parts:
            if current_inode is None:
                return None

            if current_inode.inode_type != InodeType.DIRECTORY:
                return None

            inode_num = self._lookup_in_directory(current_inode, part)
            if inode_num is None:
                return None

            current_inode = self._read_inode(inode_num)

        return current_inode

    def _resolve_parent(self, path: str) -> Tuple[Optional[Inode], str]:
        """Resolve parent directory and return (parent_inode, basename)."""
        if path == '/':
            return None, ''

        parts = [p for p in path.split('/') if p]
        if not parts:
            return None, ''

        basename = parts[-1]
        parent_path = '/' + '/'.join(parts[:-1]) if len(parts) > 1 else '/'

        parent_inode = self._resolve_path(parent_path)
        return parent_inode, basename

    # ============================================
    # File Data Operations
    # ============================================

    def _read_file_data(self, inode: Inode) -> bytes:
        """Read all data from file inode."""
        if inode.size == 0:
            return b''

        data = bytearray()
        blocks_needed = (inode.size + BLOCK_SIZE - 1) // BLOCK_SIZE

        # Read direct blocks
        for i in range(min(blocks_needed, 12)):
            if inode.direct_blocks[i] == 0:
                break
            block_data = self.device.read_block(inode.direct_blocks[i])
            data.extend(block_data)

        # TODO: Handle indirect blocks for large files

        return bytes(data[:inode.size])

    def _write_file_data_to_inode(self, inode: Inode, data: bytes):
        """Write data to inode's blocks."""
        blocks_needed = (len(data) + BLOCK_SIZE - 1) // BLOCK_SIZE

        # Allocate or reuse direct blocks
        for i in range(min(blocks_needed, 12)):
            if inode.direct_blocks[i] == 0:
                inode.direct_blocks[i] = self._allocate_block()

            start = i * BLOCK_SIZE
            end = min(start + BLOCK_SIZE, len(data))
            block_data = data[start:end].ljust(BLOCK_SIZE, b'\x00')
            self.device.write_block(inode.direct_blocks[i], block_data)

        # Free unused blocks
        for i in range(blocks_needed, 12):
            if inode.direct_blocks[i] != 0:
                self._free_block(inode.direct_blocks[i])
                inode.direct_blocks[i] = 0

        inode.size = len(data)
        inode.blocks_allocated = blocks_needed
        self._write_inode(inode)

    def _write_file_data(self, inode_num: int, data: bytes):
        """Write file data for inode."""
        inode = self._read_inode(inode_num)
        if inode:
            self._write_file_data_to_inode(inode, data)

    # ============================================
    # FUSE Operations - Metadata
    # ============================================

    def getattr(self, path, fh=None):
        """Get file attributes."""
        self._log(f"getattr: {path}")

        # Handle virtual /.ai/ paths
        if self.virtual_ai.is_ai_path(path):
            result = self.virtual_ai.getattr(path)
            if result:
                return result
            raise FuseOSError(errno.ENOENT)

        inode = self._resolve_path(path)
        if not inode:
            raise FuseOSError(errno.ENOENT)

        return self._inode_to_stat(inode)

    def _inode_to_stat(self, inode: Inode) -> dict:
        """Convert inode to stat dict."""
        mode = inode.mode

        if inode.inode_type == InodeType.DIRECTORY:
            mode |= stat.S_IFDIR
        elif inode.inode_type == InodeType.SYMLINK:
            mode |= stat.S_IFLNK
        else:
            mode |= stat.S_IFREG

        return {
            'st_mode': mode,
            'st_ino': inode.inode_num,
            'st_nlink': inode.nlinks,
            'st_uid': inode.uid,
            'st_gid': inode.gid,
            'st_size': inode.size,
            'st_atime': inode.accessed_at,
            'st_mtime': inode.modified_at,
            'st_ctime': inode.created_at,
            'st_blocks': inode.blocks_allocated * (BLOCK_SIZE // 512),
            'st_blksize': BLOCK_SIZE,
        }

    def readdir(self, path, fh):
        """Read directory contents."""
        self._log(f"readdir: {path}")

        # Handle virtual /.ai/ paths
        if self.virtual_ai.is_ai_path(path):
            entries = ['.', '..']
            entries.extend(self.virtual_ai.readdir(path))
            return entries

        inode = self._resolve_path(path)
        if not inode:
            raise FuseOSError(errno.ENOENT)

        if inode.inode_type != InodeType.DIRECTORY:
            raise FuseOSError(errno.ENOTDIR)

        entries = ['.', '..']

        for entry in self._read_directory(inode):
            entries.append(entry.name)

        # Add .ai virtual directory to root
        if path == "/" or path == "":
            entries.append(".ai")

        return entries

    def mkdir(self, path, mode):
        """Create directory."""
        self._log(f"mkdir: {path} mode={oct(mode)}")

        parent_inode, name = self._resolve_parent(path)
        if not parent_inode:
            raise FuseOSError(errno.ENOENT)

        # Check if name already exists
        if self._lookup_in_directory(parent_inode, name) is not None:
            raise FuseOSError(errno.EEXIST)

        # Allocate new inode
        new_inode_num = self._allocate_inode()
        now = int(time.time())

        new_inode = Inode(
            inode_num=new_inode_num,
            inode_type=InodeType.DIRECTORY,
            mode=mode & 0o7777,
            uid=os.getuid() if hasattr(os, 'getuid') else 0,
            gid=os.getgid() if hasattr(os, 'getgid') else 0,
            created_at=now,
            modified_at=now,
            accessed_at=now,
            nlinks=2,  # . and parent's link
        )

        self._write_inode(new_inode)
        self._add_directory_entry(parent_inode, name, new_inode_num)

        # Update parent's link count
        parent_inode.nlinks += 1
        self._write_inode(parent_inode)

        return 0

    def rmdir(self, path):
        """Remove directory."""
        self._log(f"rmdir: {path}")

        inode = self._resolve_path(path)
        if not inode:
            raise FuseOSError(errno.ENOENT)

        if inode.inode_type != InodeType.DIRECTORY:
            raise FuseOSError(errno.ENOTDIR)

        # Check if directory is empty
        entries = self._read_directory(inode)
        if entries:
            raise FuseOSError(errno.ENOTEMPTY)

        # Remove from parent
        parent_inode, name = self._resolve_parent(path)
        if parent_inode:
            self._remove_directory_entry(parent_inode, name)
            parent_inode.nlinks -= 1
            self._write_inode(parent_inode)

        # Free inode
        inode.inode_num = 0
        self._write_inode(inode)

        # Remove from cache
        if inode.inode_num in self.inode_cache:
            del self.inode_cache[inode.inode_num]
        if inode.inode_num in self.dir_cache:
            del self.dir_cache[inode.inode_num]

        return 0

    def unlink(self, path):
        """Remove file."""
        self._log(f"unlink: {path}")

        # Handle virtual /.ai/ paths
        if self.virtual_ai.is_ai_path(path):
            if self.virtual_ai.unlink(path):
                return
            raise FuseOSError(errno.EPERM)

        inode = self._resolve_path(path)
        if not inode:
            raise FuseOSError(errno.ENOENT)

        if inode.inode_type == InodeType.DIRECTORY:
            raise FuseOSError(errno.EISDIR)

        # Remove from parent
        parent_inode, name = self._resolve_parent(path)
        if parent_inode:
            self._remove_directory_entry(parent_inode, name)

        # Decrement link count
        inode.nlinks -= 1

        if inode.nlinks == 0:
            # Free data blocks
            for block in inode.direct_blocks:
                if block != 0:
                    self._free_block(block)

            # Free inode
            old_num = inode.inode_num
            inode.inode_num = 0
            self._write_inode(inode)

            if old_num in self.inode_cache:
                del self.inode_cache[old_num]
        else:
            self._write_inode(inode)

        # Remove from knowledge graph
        if self.knowledge_graph:
            self.knowledge_graph.delete_file(path)

        return 0

    def rename(self, old, new):
        """Rename file."""
        self._log(f"rename: {old} -> {new}")

        inode = self._resolve_path(old)
        if not inode:
            raise FuseOSError(errno.ENOENT)

        # Remove from old parent
        old_parent, old_name = self._resolve_parent(old)
        if old_parent:
            self._remove_directory_entry(old_parent, old_name)

        # Add to new parent
        new_parent, new_name = self._resolve_parent(new)
        if not new_parent:
            raise FuseOSError(errno.ENOENT)

        # Check if target exists
        existing = self._lookup_in_directory(new_parent, new_name)
        if existing is not None:
            # Remove existing
            self._remove_directory_entry(new_parent, new_name)

        self._add_directory_entry(new_parent, new_name, inode.inode_num)

        # Update knowledge graph with new path
        if self.knowledge_graph:
            self.knowledge_graph.rename_file(old, new)

        return 0

    def chmod(self, path, mode):
        """Change permissions."""
        self._log(f"chmod: {path} mode={oct(mode)}")

        inode = self._resolve_path(path)
        if not inode:
            raise FuseOSError(errno.ENOENT)

        inode.mode = mode & 0o7777
        self._write_inode(inode)

        return 0

    def chown(self, path, uid, gid):
        """Change owner."""
        self._log(f"chown: {path} uid={uid} gid={gid}")

        inode = self._resolve_path(path)
        if not inode:
            raise FuseOSError(errno.ENOENT)

        if uid != -1:
            inode.uid = uid
        if gid != -1:
            inode.gid = gid
        self._write_inode(inode)

        return 0

    def utimens(self, path, times=None):
        """Update timestamps."""
        self._log(f"utimens: {path}")

        inode = self._resolve_path(path)
        if not inode:
            raise FuseOSError(errno.ENOENT)

        now = int(time.time())
        if times is None:
            inode.accessed_at = now
            inode.modified_at = now
        else:
            inode.accessed_at = int(times[0])
            inode.modified_at = int(times[1])

        self._write_inode(inode)
        return 0

    # ============================================
    # FUSE Operations - File I/O
    # ============================================

    def open(self, path, flags):
        """Open file."""
        self._log(f"open: {path} flags={flags}")

        # Handle virtual /.ai/ paths
        if self.virtual_ai.is_ai_path(path):
            # Verify the virtual file exists
            if self.virtual_ai.getattr(path):
                self.fh_counter += 1
                return self.fh_counter
            raise FuseOSError(errno.ENOENT)

        inode = self._resolve_path(path)
        if not inode:
            raise FuseOSError(errno.ENOENT)

        if inode.inode_type == InodeType.DIRECTORY:
            raise FuseOSError(errno.EISDIR)

        self.fh_counter += 1
        fh = self.fh_counter
        self.open_files[fh] = (inode.inode_num, flags)

        return fh

    def create(self, path, mode, fi=None):
        """Create and open file."""
        self._log(f"create: {path} mode={oct(mode)}")

        # Handle virtual /.ai/ paths
        if self.virtual_ai.is_ai_path(path):
            if self.virtual_ai.create(path, mode):
                self.fh_counter += 1
                return self.fh_counter
            raise FuseOSError(errno.EPERM)

        parent_inode, name = self._resolve_parent(path)
        if not parent_inode:
            raise FuseOSError(errno.ENOENT)

        # Check if exists
        existing = self._lookup_in_directory(parent_inode, name)
        if existing is not None:
            # Truncate existing file
            inode = self._read_inode(existing)
            inode.size = 0
            inode.modified_at = int(time.time())
            self._write_inode(inode)

            self.fh_counter += 1
            fh = self.fh_counter
            self.open_files[fh] = (existing, os.O_RDWR)
            return fh

        # Allocate new inode
        new_inode_num = self._allocate_inode()
        now = int(time.time())

        new_inode = Inode(
            inode_num=new_inode_num,
            inode_type=InodeType.REGULAR_FILE,
            mode=mode & 0o7777,
            uid=os.getuid() if hasattr(os, 'getuid') else 0,
            gid=os.getgid() if hasattr(os, 'getgid') else 0,
            created_at=now,
            modified_at=now,
            accessed_at=now,
            nlinks=1,
        )

        self._write_inode(new_inode)
        self._add_directory_entry(parent_inode, name, new_inode_num)

        self.fh_counter += 1
        fh = self.fh_counter
        self.open_files[fh] = (new_inode_num, os.O_RDWR)

        return fh

    def read(self, path, size, offset, fh):
        """Read from file."""
        self._log(f"read: {path} size={size} offset={offset} fh={fh}")

        # Handle virtual /.ai/ paths
        if self.virtual_ai.is_ai_path(path):
            return self.virtual_ai.read(path, size, offset)

        if fh not in self.open_files:
            raise FuseOSError(errno.EBADF)

        inode_num, flags = self.open_files[fh]
        inode = self._read_inode(inode_num)

        if not inode:
            raise FuseOSError(errno.EIO)

        data = self._read_file_data(inode)
        return data[offset:offset + size]

    def write(self, path, data, offset, fh):
        """Write to file."""
        self._log(f"write: {path} len={len(data)} offset={offset} fh={fh}")

        # Handle virtual /.ai/ paths
        if self.virtual_ai.is_ai_path(path):
            return self.virtual_ai.write(path, data, offset)

        if fh not in self.open_files:
            raise FuseOSError(errno.EBADF)

        inode_num, flags = self.open_files[fh]
        inode = self._read_inode(inode_num)

        if not inode:
            raise FuseOSError(errno.EIO)

        # Read existing data
        existing = self._read_file_data(inode)
        existing = bytearray(existing)

        # Extend if needed
        end_pos = offset + len(data)
        if end_pos > len(existing):
            existing.extend(b'\x00' * (end_pos - len(existing)))

        # Write new data
        existing[offset:offset + len(data)] = data

        # Update file
        self._write_file_data_to_inode(inode, bytes(existing))
        inode.modified_at = int(time.time())
        self._write_inode(inode)

        return len(data)

    def truncate(self, path, length, fh=None):
        """Truncate file."""
        self._log(f"truncate: {path} length={length}")

        inode = self._resolve_path(path)
        if not inode:
            raise FuseOSError(errno.ENOENT)

        data = self._read_file_data(inode)

        if length < len(data):
            data = data[:length]
        else:
            data = data + b'\x00' * (length - len(data))

        self._write_file_data_to_inode(inode, data)
        inode.modified_at = int(time.time())
        self._write_inode(inode)

        # Queue for re-extraction since content changed
        self._queue_for_extraction(path, inode.inode_num)

        return 0

    def flush(self, path, fh):
        """Flush file."""
        self._log(f"flush: {path} fh={fh}")
        return 0

    def release(self, path, fh):
        """Close file."""
        self._log(f"release: {path} fh={fh}")
        if fh in self.open_files:
            inode_num, flags = self.open_files[fh]

            # Queue for knowledge extraction if file was modified
            if flags & (os.O_WRONLY | os.O_RDWR):
                self._queue_for_extraction(path, inode_num)

            del self.open_files[fh]
        return 0

    def _queue_for_extraction(self, path: str, inode_num: int):
        """Queue file for knowledge extraction."""
        # Skip virtual /.ai/ paths
        if path.startswith('/.ai/') or path.startswith('\\.ai\\'):
            return

        # Skip if no processor
        if not self.processor:
            return

        try:
            inode = self._read_inode(inode_num)
            if inode and inode.size > 0:
                # Read file data
                data = self._read_file_data(inode)
                if data:
                    self._log(f"Queuing for extraction: {path} ({len(data)} bytes)")
                    self.processor.queue_file(path, inode_num, data)
        except Exception as e:
            self._log(f"Failed to queue {path} for extraction: {e}")

    def fsync(self, path, datasync, fh):
        """Sync file."""
        self._log(f"fsync: {path} fh={fh}")
        self.device.sync()
        return 0

    # ============================================
    # FUSE Operations - Access Control
    # ============================================

    def access(self, path, amode):
        """Check file access permissions."""
        self._log(f"access: {path} mode={amode}")
        # Allow all access for now
        inode = self._resolve_path(path)
        if not inode:
            raise FuseOSError(errno.ENOENT)
        return 0

    def mknod(self, path, mode, dev):
        """Create a file node (used by some FUSE implementations instead of create)."""
        self._log(f"mknod: {path} mode={oct(mode)}")
        # Delegate to create
        return self.create(path, mode)

    # ============================================
    # FUSE Operations - Extended Attributes
    # ============================================

    def getxattr(self, path, name, position=0):
        """Get extended attribute."""
        raise FuseOSError(errno.ENODATA)

    def listxattr(self, path):
        """List extended attributes."""
        return []

    def setxattr(self, path, name, value, options, position=0):
        """Set extended attribute."""
        raise FuseOSError(errno.ENOTSUP)

    def removexattr(self, path, name):
        """Remove extended attribute."""
        raise FuseOSError(errno.ENOTSUP)

    # ============================================
    # FUSE Operations - Filesystem Stats
    # ============================================

    def statfs(self, path):
        """Get filesystem statistics."""
        self._log(f"statfs: {path}")

        return {
            'f_bsize': BLOCK_SIZE,
            'f_frsize': BLOCK_SIZE,
            'f_blocks': self.superblock.total_blocks,
            'f_bfree': self.superblock.free_blocks,
            'f_bavail': self.superblock.free_blocks,
            'f_files': self.superblock.total_inodes,
            'f_ffree': self.superblock.free_inodes,
            'f_favail': self.superblock.free_inodes,
            'f_namemax': MAX_NAME_LEN,
        }


def mount_cognitivefs(device_path: str, mount_point: str, debug: bool = False, foreground: bool = True):
    """
    Mount CognitiveFS.

    Args:
        device_path: Path to block device
        mount_point: Mount point directory (or drive letter on Windows like "X:")
        debug: Enable debug output
        foreground: Run in foreground (required for debugging)
    """
    if FUSE is None:
        print("ERROR: FUSE library not installed. Install with: pip install fusepy")
        sys.exit(1)

    # Ensure mount point exists (skip for Windows drive letters)
    is_drive_letter = (sys.platform == 'win32' and
                       len(mount_point) <= 3 and
                       mount_point[0].isalpha() and
                       (len(mount_point) == 1 or mount_point[1] == ':'))

    if not is_drive_letter:
        os.makedirs(mount_point, exist_ok=True)

    # Create FUSE operations
    operations = CognitiveFS(device_path, debug=debug)

    # Mount
    print(f"Mounting {device_path} at {mount_point}...")

    fuse_kwargs = {
        'foreground': foreground,
        'nothreads': True,  # Single-threaded for now
        'allow_other': False,
    }

    # Platform-specific options
    if sys.platform == 'win32':
        # WinFsp options for full read/write access
        fuse_kwargs.update({
            'volname': 'CognitiveFS',
            'umask': 0,  # Allow all permissions
        })

    try:
        FUSE(operations, mount_point, **fuse_kwargs)
    except Exception as e:
        print(f"Mount failed: {e}")
        sys.exit(1)
