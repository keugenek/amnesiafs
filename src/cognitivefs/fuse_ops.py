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
from typing import Optional, List
from pathlib import Path

try:
    from refuse.high import FUSE, Operations, FuseOSError
except ImportError:
    try:
        from fuse import FUSE, Operations, FuseOSError
    except ImportError:
        # Fallback - define minimal interface for development
        class FuseOSError(OSError):
            pass

        class Operations:
            pass

        class FUSE:
            def __init__(self, operations, mountpoint, **kwargs):
                raise NotImplementedError("FUSE library not installed")


from .blockdev import BlockDevice, BlockDeviceError
from .diskformat import Superblock, Inode, InodeType, AllocationBitmap


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
        self.inode_cache = {}

        # File handle counter
        self.fh_counter = 0
        self.open_files = {}  # fh -> (inode_num, flags)

        # Root directory inode
        self.ROOT_INODE = 1

    def init(self, path):
        """Initialize filesystem on mount."""
        self._log(f"Mounting CognitiveFS from {self.device_path}")

        # Open block device
        self.device = BlockDevice(self.device_path, read_only=False)
        self.device.open()

        # Read superblock
        superblock_data = self.device.read_block(0)
        self.superblock = Superblock.unpack(superblock_data)

        if not self.superblock.is_valid():
            raise FuseOSError(errno.EIO, "Invalid filesystem - not formatted?")

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
            raise FuseOSError(errno.EIO, "Root inode not found")

        self._log("Filesystem mounted successfully")

    def destroy(self, path):
        """Cleanup on unmount."""
        self._log("Unmounting CognitiveFS")

        if self.device:
            # Write back any cached data
            self._flush_all()
            self.device.sync()
            self.device.close()

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

    def _allocate_inode(self) -> int:
        """Allocate a new inode number."""
        # Simple linear search for free inode
        # TODO: Maintain free inode list for efficiency
        max_inodes = self.superblock.inode_table_blocks * (self.device.BLOCK_SIZE // Inode.INODE_SIZE)

        for inode_num in range(2, max_inodes):  # Start from 2 (1 is root)
            if inode_num not in self.inode_cache:
                inode = self._read_inode(inode_num)
                if inode is None or inode.inode_num == 0:
                    return inode_num

        raise FuseOSError(errno.ENOSPC, "No free inodes")

    def _flush_all(self):
        """Flush all cached data."""
        # Write bitmap
        self._write_bitmap()

        # Write superblock
        self.device.write_block(0, self.superblock.pack())

    # ============================================
    # FUSE Operations - Metadata
    # ============================================

    def getattr(self, path, fh=None):
        """Get file attributes."""
        self._log(f"getattr: {path}")

        # Special case: root directory
        if path == '/':
            inode = self._read_inode(self.ROOT_INODE)
        else:
            # TODO: Path lookup implementation
            # For now, return ENOENT
            raise FuseOSError(errno.ENOENT)

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
        }

    def readdir(self, path, fh):
        """Read directory contents."""
        self._log(f"readdir: {path}")

        # Basic implementation - return . and ..
        # TODO: Read actual directory entries from data blocks
        return ['.', '..']

    def mkdir(self, path, mode):
        """Create directory."""
        self._log(f"mkdir: {path} mode={oct(mode)}")
        # TODO: Implement directory creation
        raise FuseOSError(errno.EROFS)  # Read-only for now

    def rmdir(self, path):
        """Remove directory."""
        self._log(f"rmdir: {path}")
        raise FuseOSError(errno.EROFS)

    def unlink(self, path):
        """Remove file."""
        self._log(f"unlink: {path}")
        raise FuseOSError(errno.EROFS)

    def rename(self, old, new):
        """Rename file."""
        self._log(f"rename: {old} -> {new}")
        raise FuseOSError(errno.EROFS)

    def chmod(self, path, mode):
        """Change permissions."""
        self._log(f"chmod: {path} mode={oct(mode)}")
        raise FuseOSError(errno.EROFS)

    def chown(self, path, uid, gid):
        """Change owner."""
        self._log(f"chown: {path} uid={uid} gid={gid}")
        raise FuseOSError(errno.EROFS)

    def utimens(self, path, times=None):
        """Update timestamps."""
        self._log(f"utimens: {path}")
        # TODO: Implement timestamp updates
        pass

    # ============================================
    # FUSE Operations - File I/O
    # ============================================

    def open(self, path, flags):
        """Open file."""
        self._log(f"open: {path} flags={flags}")

        # TODO: Path lookup to get inode
        # For now, return dummy file handle
        self.fh_counter += 1
        fh = self.fh_counter
        self.open_files[fh] = (0, flags)  # (inode_num, flags)
        return fh

    def create(self, path, mode, fi=None):
        """Create and open file."""
        self._log(f"create: {path} mode={oct(mode)}")
        raise FuseOSError(errno.EROFS)

    def read(self, path, size, offset, fh):
        """Read from file."""
        self._log(f"read: {path} size={size} offset={offset} fh={fh}")

        # TODO: Implement actual read from data blocks
        return b''

    def write(self, path, data, offset, fh):
        """Write to file."""
        self._log(f"write: {path} len={len(data)} offset={offset} fh={fh}")
        raise FuseOSError(errno.EROFS)

    def truncate(self, path, length, fh=None):
        """Truncate file."""
        self._log(f"truncate: {path} length={length}")
        raise FuseOSError(errno.EROFS)

    def flush(self, path, fh):
        """Flush file."""
        self._log(f"flush: {path} fh={fh}")
        return 0

    def release(self, path, fh):
        """Close file."""
        self._log(f"release: {path} fh={fh}")
        if fh in self.open_files:
            del self.open_files[fh]
        return 0

    def fsync(self, path, datasync, fh):
        """Sync file."""
        self._log(f"fsync: {path} fh={fh}")
        self.device.sync()
        return 0

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
            'f_bsize': self.device.BLOCK_SIZE,
            'f_frsize': self.device.BLOCK_SIZE,
            'f_blocks': self.superblock.total_blocks,
            'f_bfree': self.superblock.free_blocks,
            'f_bavail': self.superblock.free_blocks,
            'f_files': self.superblock.total_inodes,
            'f_ffree': self.superblock.free_inodes,
            'f_favail': self.superblock.free_inodes,
            'f_namemax': 255,
        }


def mount_cognitivefs(device_path: str, mount_point: str, debug: bool = False):
    """
    Mount CognitiveFS.

    Args:
        device_path: Path to block device
        mount_point: Mount point directory
        debug: Enable debug output
    """
    # Ensure mount point exists
    os.makedirs(mount_point, exist_ok=True)

    # Create FUSE operations
    operations = CognitiveFS(device_path, debug=debug)

    # Mount
    print(f"Mounting {device_path} at {mount_point}...")

    fuse_kwargs = {
        'foreground': debug,
        'nothreads': True,  # Single-threaded for now
        'allow_other': False,
    }

    # Platform-specific options
    if sys.platform == 'win32':
        # WinFsp options
        fuse_kwargs.update({
            'volname': 'CognitiveFS',
            'uid': -1,
            'gid': -1,
        })

    FUSE(operations, mount_point, **fuse_kwargs)
