"""
On-Disk Format Structures

Defines the custom filesystem format for CognitiveFS on raw block devices.

Layout:
    Block 0:         Superblock (4KB)
    Blocks 1-4095:   Allocation Bitmap (16MB for 128GB @ 4KB blocks)
    Blocks 4096-:    Inode Table (64MB)
    ...              Knowledge Graph Region (SQLite)
    ...              Embedding Store (FAISS)
    ...              Version Store (content-addressed)
    ...              Data Blocks
    ...              Journal
"""

import struct
import time
import hashlib
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import IntEnum


# Constants
BLOCK_SIZE = 4096  # 4KB blocks
MAGIC = b"COGFS001"  # 8-byte magic number
VERSION = 1

# Layout offsets (in blocks)
SUPERBLOCK_BLOCK = 0
BITMAP_START_BLOCK = 1
BITMAP_BLOCKS = 4095  # 16MB bitmap for ~128GB
INODE_TABLE_START_BLOCK = 4096
INODE_TABLE_BLOCKS = 16384  # 64MB for inodes
KNOWLEDGE_GRAPH_START_BLOCK = 20480  # After inode table
KNOWLEDGE_GRAPH_BLOCKS = 2097152  # 8GB for SQLite
EMBEDDING_STORE_START_BLOCK = 2117632
EMBEDDING_STORE_BLOCKS = 2097152  # 8GB for FAISS
VERSION_STORE_START_BLOCK = 4214784
VERSION_STORE_BLOCKS = 2621440  # 10GB for versions
DATA_BLOCKS_START_BLOCK = 6836224  # ~26.6GB used for metadata
# Remaining blocks for data + journal


class InodeType(IntEnum):
    """Inode type flags."""
    REGULAR_FILE = 1
    DIRECTORY = 2
    SYMLINK = 3
    VIRTUAL = 4  # Virtual files in /.ai/


class InodeFlags(IntEnum):
    """Inode flag bits."""
    NONE = 0
    COMPRESSED = 1 << 0  # Data is LZ4 compressed
    ENCRYPTED = 1 << 1   # Data is encrypted
    VERSIONED = 1 << 2   # Has version history
    AI_INDEXED = 1 << 3  # Has been AI-processed
    DIRTY = 1 << 4       # Needs knowledge extraction


@dataclass
class Superblock:
    """
    Superblock - First block of the filesystem.

    Contains filesystem metadata and pointers to major structures.
    """

    # Header
    magic: bytes = MAGIC
    version: int = VERSION
    block_size: int = BLOCK_SIZE
    total_blocks: int = 0

    # Timestamps
    created_at: int = 0  # Unix timestamp
    mounted_at: int = 0
    last_check: int = 0

    # Feature flags
    flags: int = 0

    # Layout pointers (block numbers)
    bitmap_start: int = BITMAP_START_BLOCK
    bitmap_blocks: int = BITMAP_BLOCKS
    inode_table_start: int = INODE_TABLE_START_BLOCK
    inode_table_blocks: int = INODE_TABLE_BLOCKS
    knowledge_graph_start: int = KNOWLEDGE_GRAPH_START_BLOCK
    knowledge_graph_blocks: int = KNOWLEDGE_GRAPH_BLOCKS
    embedding_store_start: int = EMBEDDING_STORE_START_BLOCK
    embedding_store_blocks: int = EMBEDDING_STORE_BLOCKS
    version_store_start: int = VERSION_STORE_START_BLOCK
    version_store_blocks: int = VERSION_STORE_BLOCKS
    data_blocks_start: int = DATA_BLOCKS_START_BLOCK
    journal_start: int = 0  # Set during format
    journal_blocks: int = 16384  # 64MB journal

    # Statistics
    free_blocks: int = 0
    free_inodes: int = 0
    total_inodes: int = 0

    # UUID
    uuid: bytes = b'\x00' * 16

    def pack(self) -> bytes:
        """Serialize superblock to bytes."""
        data = struct.pack(
            '<8sIIQ'  # magic, version, block_size, total_blocks
            'QQQ'     # created_at, mounted_at, last_check
            'Q'       # flags
            'QQQQQQQQQQQQQ'  # 13 layout pointers
            'QQQ'     # stats: free_blocks, free_inodes, total_inodes
            '16s',    # uuid
            self.magic,
            self.version,
            self.block_size,
            self.total_blocks,
            self.created_at,
            self.mounted_at,
            self.last_check,
            self.flags,
            self.bitmap_start,
            self.bitmap_blocks,
            self.inode_table_start,
            self.inode_table_blocks,
            self.knowledge_graph_start,
            self.knowledge_graph_blocks,
            self.embedding_store_start,
            self.embedding_store_blocks,
            self.version_store_start,
            self.version_store_blocks,
            self.data_blocks_start,
            self.journal_start,
            self.journal_blocks,
            self.free_blocks,
            self.free_inodes,
            self.total_inodes,
            self.uuid
        )

        # Pad to block size
        return data.ljust(BLOCK_SIZE, b'\x00')

    @classmethod
    def unpack(cls, data: bytes) -> 'Superblock':
        """Deserialize superblock from bytes."""
        # Format: 8s(8) + II(8) + 21 Q's(168) + 16s(16) = 200 bytes, 25 fields
        fields = struct.unpack('<8sIIQQQQQQQQQQQQQQQQQQQQQ16s', data[:200])

        return cls(
            magic=fields[0],
            version=fields[1],
            block_size=fields[2],
            total_blocks=fields[3],
            created_at=fields[4],
            mounted_at=fields[5],
            last_check=fields[6],
            flags=fields[7],
            bitmap_start=fields[8],
            bitmap_blocks=fields[9],
            inode_table_start=fields[10],
            inode_table_blocks=fields[11],
            knowledge_graph_start=fields[12],
            knowledge_graph_blocks=fields[13],
            embedding_store_start=fields[14],
            embedding_store_blocks=fields[15],
            version_store_start=fields[16],
            version_store_blocks=fields[17],
            data_blocks_start=fields[18],
            journal_start=fields[19],
            journal_blocks=fields[20],
            free_blocks=fields[21],
            free_inodes=fields[22],
            total_inodes=fields[23],
            uuid=fields[24]
        )

    def is_valid(self) -> bool:
        """Check if superblock is valid."""
        return (
            self.magic == MAGIC and
            self.version == VERSION and
            self.block_size == BLOCK_SIZE
        )


@dataclass
class Inode:
    """
    Inode - File metadata and semantic information.

    Enhanced beyond traditional inodes with AI-specific metadata.
    """

    # Basic metadata
    inode_num: int = 0
    inode_type: int = InodeType.REGULAR_FILE
    flags: int = InodeFlags.NONE
    mode: int = 0o644
    uid: int = 0
    gid: int = 0

    # Timestamps
    created_at: int = 0
    modified_at: int = 0
    accessed_at: int = 0

    # Size and blocks
    size: int = 0  # File size in bytes
    blocks_allocated: int = 0  # Number of data blocks

    # Block pointers (like ext4)
    direct_blocks: List[int] = field(default_factory=lambda: [0] * 12)
    indirect_block: int = 0
    double_indirect_block: int = 0
    triple_indirect_block: int = 0

    # AI-specific metadata
    content_hash: bytes = b'\x00' * 32  # SHA256 of content
    embedding_offset: int = 0  # Offset in embedding store
    embedding_dims: int = 0    # Embedding dimension
    knowledge_graph_id: int = 0  # ID in knowledge graph

    # Semantic metadata
    mime_type: bytes = b''  # Up to 64 bytes
    language: bytes = b''   # Language code (e.g., 'en')

    # Version control
    version_count: int = 0
    latest_version_hash: bytes = b'\x00' * 32

    # Link count (for hard links)
    nlinks: int = 1

    INODE_SIZE = 512  # Fixed size per inode

    def pack(self) -> bytes:
        """Serialize inode to bytes."""
        data = struct.pack(
            '<QHHHHH'  # inode_num, type, flags, mode, uid, gid
            'QQQ'      # timestamps
            'QQ'       # size, blocks
            '12Q'      # direct blocks
            'QQQ'      # indirect blocks
            '32s'      # content_hash
            'QQQ'      # embedding info
            '64s8s'    # mime_type, language
            'Q32s'     # version info
            'H',       # nlinks
            self.inode_num,
            self.inode_type,
            self.flags,
            self.mode,
            self.uid,
            self.gid,
            self.created_at,
            self.modified_at,
            self.accessed_at,
            self.size,
            self.blocks_allocated,
            *self.direct_blocks,
            self.indirect_block,
            self.double_indirect_block,
            self.triple_indirect_block,
            self.content_hash,
            self.embedding_offset,
            self.embedding_dims,
            self.knowledge_graph_id,
            self.mime_type.ljust(64, b'\x00')[:64],
            self.language.ljust(8, b'\x00')[:8],
            self.version_count,
            self.latest_version_hash,
            self.nlinks
        )

        # Pad to INODE_SIZE
        return data.ljust(self.INODE_SIZE, b'\x00')

    # Struct format size: 18+24+16+96+24+32+24+72+40+2 = 348 bytes
    STRUCT_SIZE = 348

    @classmethod
    def unpack(cls, data: bytes) -> 'Inode':
        """Deserialize inode from bytes."""
        fields = struct.unpack(
            '<QHHHHH'
            'QQQ'
            'QQ'
            '12Q'
            'QQQ'
            '32s'
            'QQQ'
            '64s8s'
            'Q32s'
            'H',
            data[:cls.STRUCT_SIZE]
        )

        return cls(
            inode_num=fields[0],
            inode_type=fields[1],
            flags=fields[2],
            mode=fields[3],
            uid=fields[4],
            gid=fields[5],
            created_at=fields[6],
            modified_at=fields[7],
            accessed_at=fields[8],
            size=fields[9],
            blocks_allocated=fields[10],
            direct_blocks=list(fields[11:23]),
            indirect_block=fields[23],
            double_indirect_block=fields[24],
            triple_indirect_block=fields[25],
            content_hash=fields[26],
            embedding_offset=fields[27],
            embedding_dims=fields[28],
            knowledge_graph_id=fields[29],
            mime_type=fields[30].rstrip(b'\x00'),
            language=fields[31].rstrip(b'\x00'),
            version_count=fields[32],
            latest_version_hash=fields[33],
            nlinks=fields[34]
        )

    def get_all_block_pointers(self) -> List[int]:
        """Get all block pointers for this inode."""
        blocks = [b for b in self.direct_blocks if b != 0]
        if self.indirect_block:
            blocks.append(self.indirect_block)
        if self.double_indirect_block:
            blocks.append(self.double_indirect_block)
        if self.triple_indirect_block:
            blocks.append(self.triple_indirect_block)
        return blocks

    def calculate_content_hash(self, content: bytes) -> bytes:
        """Calculate SHA256 hash of content."""
        return hashlib.sha256(content).digest()


class AllocationBitmap:
    """
    Allocation bitmap for tracking free/used blocks.

    Each bit represents one block (0=free, 1=used).
    """

    def __init__(self, total_blocks: int, bitmap_data: Optional[bytes] = None):
        """
        Initialize bitmap.

        Args:
            total_blocks: Total number of blocks in filesystem
            bitmap_data: Existing bitmap data, or None to create new
        """
        self.total_blocks = total_blocks
        self.bitmap_bytes = (total_blocks + 7) // 8  # Ceiling division

        if bitmap_data:
            self.data = bytearray(bitmap_data[:self.bitmap_bytes])
        else:
            self.data = bytearray(self.bitmap_bytes)

    def is_allocated(self, block_num: int) -> bool:
        """Check if a block is allocated."""
        byte_idx = block_num // 8
        bit_idx = block_num % 8
        return bool(self.data[byte_idx] & (1 << bit_idx))

    def allocate(self, block_num: int):
        """Mark a block as allocated."""
        byte_idx = block_num // 8
        bit_idx = block_num % 8
        self.data[byte_idx] |= (1 << bit_idx)

    def free(self, block_num: int):
        """Mark a block as free."""
        byte_idx = block_num // 8
        bit_idx = block_num % 8
        self.data[byte_idx] &= ~(1 << bit_idx)

    def find_free_block(self, start_block: int = 0) -> Optional[int]:
        """
        Find the next free block.

        Args:
            start_block: Block to start searching from

        Returns:
            Block number, or None if no free blocks
        """
        for block_num in range(start_block, self.total_blocks):
            if not self.is_allocated(block_num):
                return block_num
        return None

    def find_contiguous_blocks(self, count: int, start_block: int = 0) -> Optional[int]:
        """
        Find contiguous free blocks.

        Args:
            count: Number of contiguous blocks needed
            start_block: Block to start searching from

        Returns:
            Starting block number, or None if not found
        """
        current_run = 0
        run_start = start_block

        for block_num in range(start_block, self.total_blocks):
            if not self.is_allocated(block_num):
                if current_run == 0:
                    run_start = block_num
                current_run += 1
                if current_run >= count:
                    return run_start
            else:
                current_run = 0

        return None

    def count_free_blocks(self) -> int:
        """Count total free blocks."""
        count = 0
        for block_num in range(self.total_blocks):
            if not self.is_allocated(block_num):
                count += 1
        return count

    def to_bytes(self) -> bytes:
        """Convert bitmap to bytes for storage."""
        return bytes(self.data)

    @classmethod
    def from_bytes(cls, data: bytes, total_blocks: int) -> 'AllocationBitmap':
        """Create bitmap from stored bytes."""
        return cls(total_blocks, data)


@dataclass
class DirectoryEntry:
    """
    Directory entry linking name to inode.

    Stored in directory data blocks.
    """

    inode_num: int
    name: str
    file_type: int = InodeType.REGULAR_FILE

    ENTRY_SIZE = 256  # Fixed size per entry

    def pack(self) -> bytes:
        """Serialize directory entry."""
        name_bytes = self.name.encode('utf-8')[:243]  # Max 243 bytes for name
        data = struct.pack(
            '<QHB',  # inode_num, name_len, file_type
            self.inode_num,
            len(name_bytes),
            self.file_type
        )
        data += name_bytes
        return data.ljust(self.ENTRY_SIZE, b'\x00')

    @classmethod
    def unpack(cls, data: bytes) -> Optional['DirectoryEntry']:
        """Deserialize directory entry."""
        inode_num, name_len, file_type = struct.unpack('<QHB', data[:11])

        if inode_num == 0:  # Empty entry
            return None

        name_bytes = data[11:11 + name_len]
        name = name_bytes.decode('utf-8', errors='replace')

        return cls(
            inode_num=inode_num,
            name=name,
            file_type=file_type
        )


def calculate_layout(device_size: int) -> Dict[str, Any]:
    """
    Calculate filesystem layout for a given device size.

    Scales dynamically based on device size - designed for 128GB reference,
    but works with smaller images for testing.

    Args:
        device_size: Total device size in bytes

    Returns:
        Dictionary with layout information
    """
    total_blocks = device_size // BLOCK_SIZE
    REFERENCE_SIZE = 128 * 1024 * 1024 * 1024  # 128GB reference

    # Use fixed layout for devices >= 128GB, scale for smaller
    if device_size >= REFERENCE_SIZE:
        # Original fixed layout for full-size devices
        bitmap_blocks = BITMAP_BLOCKS
        inode_blocks = INODE_TABLE_BLOCKS
        kg_blocks = KNOWLEDGE_GRAPH_BLOCKS
        embed_blocks = EMBEDDING_STORE_BLOCKS
        version_blocks = VERSION_STORE_BLOCKS
    else:
        # Scale proportionally for smaller devices
        scale = device_size / REFERENCE_SIZE

        # Minimum sizes for each region (in blocks)
        bitmap_blocks = max(256, int(BITMAP_BLOCKS * scale))  # Min 1MB
        inode_blocks = max(256, int(INODE_TABLE_BLOCKS * scale))  # Min 1MB
        kg_blocks = max(256, int(KNOWLEDGE_GRAPH_BLOCKS * scale))  # Min 1MB
        embed_blocks = max(256, int(EMBEDDING_STORE_BLOCKS * scale))  # Min 1MB
        version_blocks = max(256, int(VERSION_STORE_BLOCKS * scale))  # Min 1MB

    # Calculate start positions
    bitmap_start = 1  # After superblock
    inode_start = bitmap_start + bitmap_blocks
    kg_start = inode_start + inode_blocks
    embed_start = kg_start + kg_blocks
    version_start = embed_start + embed_blocks
    data_start = version_start + version_blocks

    # Journal at the end (1% or min 256 blocks = 1MB)
    journal_blocks = max(256, total_blocks // 100)
    data_end = total_blocks - journal_blocks
    data_blocks = max(0, data_end - data_start)

    return {
        'device_size': device_size,
        'total_blocks': total_blocks,
        'block_size': BLOCK_SIZE,
        'superblock': (0, 1),
        'bitmap': (bitmap_start, bitmap_blocks),
        'inode_table': (inode_start, inode_blocks),
        'knowledge_graph': (kg_start, kg_blocks),
        'embedding_store': (embed_start, embed_blocks),
        'version_store': (version_start, version_blocks),
        'data_blocks': (data_start, data_blocks),
        'journal': (data_end, journal_blocks),
    }
