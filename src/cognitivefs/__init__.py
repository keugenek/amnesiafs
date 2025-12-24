"""
CognitiveFS - AI-Native File System

A true FUSE-based file system with AI cognition built into every file operation.
"""

__version__ = "0.1.0"
__author__ = "CognitiveFS Project"

from .blockdev import BlockDevice, BlockDeviceError
from .diskformat import Superblock, Inode, BLOCK_SIZE
from .fuse_ops import CognitiveFS

__all__ = [
    "BlockDevice",
    "BlockDeviceError",
    "Superblock",
    "Inode",
    "BLOCK_SIZE",
    "CognitiveFS",
]
