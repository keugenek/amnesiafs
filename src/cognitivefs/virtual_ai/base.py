"""
Base classes and utilities for virtual AI handlers.
"""

import os
import stat
import time
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum


class VirtualNodeType(Enum):
    """Types of virtual nodes in /.ai/"""
    ROOT = "root"
    DIRECTORY = "directory"
    FILE = "file"
    QUERY = "query"
    SUMMARY = "summary"
    RELATED = "related"
    CHAT = "chat"
    STATUS = "status"
    GRAPH = "graph"


@dataclass
class VirtualNode:
    """Represents a virtual node in the /.ai/ directory."""
    name: str
    node_type: VirtualNodeType
    is_dir: bool
    size: int = 0
    content: bytes = b""
    children: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseHandler:
    """Base class for virtual AI path handlers."""

    AI_ROOT = "/.ai"

    def __init__(self, cognitivefs=None, knowledge_graph=None):
        """Initialize handler.

        Args:
            cognitivefs: Reference to parent CognitiveFS instance
            knowledge_graph: Reference to KnowledgeGraph instance
        """
        self.cognitivefs = cognitivefs
        self.knowledge_graph = knowledge_graph

        # Cache for generated content
        self._content_cache: Dict[str, Tuple[bytes, float]] = {}
        self._cache_ttl = 60.0  # Cache TTL in seconds

    def _make_dir_stat(self, mtime: int) -> Dict:
        """Create stat dict for a directory."""
        return {
            'st_mode': stat.S_IFDIR | 0o755,
            'st_ino': 0,
            'st_nlink': 2,
            'st_uid': 0,
            'st_gid': 0,
            'st_size': 4096,
            'st_atime': mtime,
            'st_mtime': mtime,
            'st_ctime': mtime,
            'st_blocks': 8,
            'st_blksize': 4096,
        }

    def _make_file_stat(self, size: int, mtime: int, writable: bool = False) -> Dict:
        """Create stat dict for a file."""
        mode = 0o666 if writable else 0o644
        return {
            'st_mode': stat.S_IFREG | mode,
            'st_ino': 0,
            'st_nlink': 1,
            'st_uid': 0,
            'st_gid': 0,
            'st_size': size,
            'st_atime': mtime,
            'st_mtime': mtime,
            'st_ctime': mtime,
            'st_blocks': (size + 511) // 512,
            'st_blksize': 4096,
        }

    def _get_cached(self, path: str) -> Optional[bytes]:
        """Get cached content if not expired."""
        if path in self._content_cache:
            content, timestamp = self._content_cache[path]
            if time.time() - timestamp < self._cache_ttl:
                return content
        return None

    def _set_cached(self, path: str, content: bytes):
        """Cache content."""
        self._content_cache[path] = (content, time.time())


def parse_ai_path(path: str) -> Tuple[str, str, List[str]]:
    """
    Parse an AI path into components.

    Returns:
        (subdir, target_path, path_parts)
        e.g., "/.ai/summary/docs/file.txt" -> ("summary", "/docs/file.txt", ["summary", "docs", "file.txt"])
    """
    AI_ROOT = "/.ai"

    if not (path == AI_ROOT or path.startswith(AI_ROOT + "/")):
        return None, None, []

    # Remove /.ai prefix
    rel_path = path[len(AI_ROOT):]
    if rel_path.startswith("/"):
        rel_path = rel_path[1:]

    if not rel_path:
        return "", "", []

    parts = rel_path.split("/")
    subdir = parts[0] if parts else ""
    target_path = "/" + "/".join(parts[1:]) if len(parts) > 1 else ""

    return subdir, target_path, parts
