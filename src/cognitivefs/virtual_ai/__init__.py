"""
Virtual AI Directory Handler

Implements the /.ai/ virtual directory that provides AI-native file system features.
"""

import time
from typing import Optional, Dict, List

from .base import VirtualNodeType, parse_ai_path
from .status import StatusHandler
from .search import SearchHandler
from .versions import VersionsHandler
from .entities import EntitiesHandler
from .similar import SimilarHandler
from .query import QueryHandler
from .graph import GraphHandler
from .topic import TopicHandler
from ..generators import GeneratorFactory


class VirtualAIHandler:
    """
    Handler for the virtual /.ai/ directory.

    Routes requests to specialized handlers based on path.
    """

    AI_ROOT = "/.ai"

    # Static subdirectories under /.ai/
    SUBDIRS = {
        "status": VirtualNodeType.DIRECTORY,
        "search": VirtualNodeType.DIRECTORY,
        "query": VirtualNodeType.QUERY,
        "entities": VirtualNodeType.DIRECTORY,
        "similar": VirtualNodeType.DIRECTORY,
        "versions": VirtualNodeType.DIRECTORY,
        "graph": VirtualNodeType.GRAPH,
        "by-topic": VirtualNodeType.DIRECTORY,
        # TODO: Re-enable when handlers are extracted
        # "summary": VirtualNodeType.SUMMARY,
        # "related": VirtualNodeType.RELATED,
        # "chat": VirtualNodeType.CHAT,
        # "by-date": VirtualNodeType.DIRECTORY,
    }

    # Auto-generated dual-view files
    GENERATED_FILES = ['_DASHBOARD.html', '_manifest.md', '_index.json']

    def __init__(self, cognitivefs=None):
        """Initialize virtual AI handler."""
        self.cognitivefs = cognitivefs
        self.knowledge_graph = None

        # Initialize handlers
        self.status = StatusHandler(cognitivefs, None)
        self.search = SearchHandler(cognitivefs, None)
        self.versions = VersionsHandler(cognitivefs, None)
        self.entities = EntitiesHandler(cognitivefs, None)
        self.similar = SimilarHandler(cognitivefs, None)
        self.query = QueryHandler(cognitivefs, None)
        self.graph = GraphHandler(cognitivefs, None)
        self.topic = TopicHandler(cognitivefs, None)

        # Generator factory for dual-view files
        self._generator_factory = GeneratorFactory(None)

    def set_knowledge_graph(self, kg):
        """Set the knowledge graph reference for all handlers."""
        self.knowledge_graph = kg
        self.status.knowledge_graph = kg
        self.search.knowledge_graph = kg
        self.versions.knowledge_graph = kg
        self.entities.knowledge_graph = kg
        self.similar.knowledge_graph = kg
        self.query.knowledge_graph = kg
        self.graph.knowledge_graph = kg
        self.topic.knowledge_graph = kg
        self._generator_factory.kg = kg

    def is_ai_path(self, path: str) -> bool:
        """Check if path is under /.ai/"""
        return path == self.AI_ROOT or path.startswith(self.AI_ROOT + "/")

    def parse_ai_path(self, path: str):
        """Parse an AI path into components (wrapper for compatibility)."""
        return parse_ai_path(path)

    def getattr(self, path: str) -> Optional[Dict]:
        """Get attributes for a virtual AI path."""
        subdir, target_path, parts = parse_ai_path(path)
        now = int(time.time())

        # Root /.ai/ directory
        if path == self.AI_ROOT or path == self.AI_ROOT + "/":
            return self._make_dir_stat(now)

        # First-level subdirectories
        if subdir in self.SUBDIRS and not target_path:
            return self._make_dir_stat(now)

        # Check for generated dual-view files
        filename = parts[-1] if parts else None
        if filename in self.GENERATED_FILES and subdir in self.SUBDIRS:
            virtual_path = f"/.ai/{subdir}"
            content = self._generator_factory.get_cached_or_generate(virtual_path, filename, self.cognitivefs)
            return self._make_file_stat(len(content), now)

        # Route to specific handler
        if subdir == "status":
            return self.status.getattr(target_path, parts)
        elif subdir == "search":
            return self.search.getattr(target_path, parts)
        elif subdir == "versions":
            return self.versions.getattr(target_path, parts)
        elif subdir == "entities":
            return self.entities.getattr(target_path, parts)
        elif subdir == "similar":
            return self.similar.getattr(target_path, parts)
        elif subdir == "query":
            return self.query.getattr(target_path, parts)
        elif subdir == "graph":
            return self.graph.getattr(target_path, parts)
        elif subdir == "by-topic":
            return self.topic.getattr(target_path, parts)

        return None

    def readdir(self, path: str) -> List[str]:
        """Read directory contents for a virtual AI path."""
        subdir, target_path, parts = parse_ai_path(path)

        # Root /.ai/ directory
        if path == self.AI_ROOT or path == self.AI_ROOT + "/":
            return list(self.SUBDIRS.keys())

        entries = []

        # Route to specific handler
        if subdir == "status":
            entries = self.status.readdir(target_path, parts)
        elif subdir == "search":
            entries = self.search.readdir(target_path, parts)
        elif subdir == "versions":
            entries = self.versions.readdir(target_path, parts)
        elif subdir == "entities":
            entries = self.entities.readdir(target_path, parts)
        elif subdir == "similar":
            entries = self.similar.readdir(target_path, parts)
        elif subdir == "query":
            entries = self.query.readdir(target_path, parts)
        elif subdir == "graph":
            entries = self.graph.readdir(target_path, parts)
        elif subdir == "by-topic":
            entries = self.topic.readdir(target_path, parts)

        # Add generated dual-view files to first-level subdirectories
        if subdir in self.SUBDIRS and not target_path:
            entries = list(entries) + self.GENERATED_FILES

        return entries

    def read(self, path: str, size: int, offset: int) -> bytes:
        """Read content from a virtual AI path."""
        subdir, target_path, parts = parse_ai_path(path)

        # Check for generated dual-view files first
        filename = parts[-1] if parts else None
        if filename in self.GENERATED_FILES and subdir in self.SUBDIRS:
            virtual_path = f"/.ai/{subdir}"
            content = self._generator_factory.get_cached_or_generate(virtual_path, filename, self.cognitivefs)
            return content[offset:offset + size]

        content = b""

        # Route to specific handler
        if subdir == "status":
            content = self.status.read(target_path, parts)
        elif subdir == "search":
            content = self.search.read(target_path, parts)
        elif subdir == "versions":
            content = self.versions.read(target_path, parts)
        elif subdir == "entities":
            content = self.entities.read(target_path, parts)
        elif subdir == "similar":
            content = self.similar.read(target_path, parts)
        elif subdir == "query":
            content = self.query.read(target_path, parts)
        elif subdir == "graph":
            content = self.graph.read(target_path, parts)
        elif subdir == "by-topic":
            content = self.topic.read(target_path, parts)

        return content[offset:offset + size]

    def _make_dir_stat(self, mtime: int) -> Dict:
        """Create stat dict for a directory."""
        import stat
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

    def _make_file_stat(self, size: int, mtime: int) -> Dict:
        """Create stat dict for a file."""
        import stat
        return {
            'st_mode': stat.S_IFREG | 0o644,
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


# Export main class
__all__ = ['VirtualAIHandler']
