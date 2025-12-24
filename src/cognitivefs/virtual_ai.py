"""
Virtual AI Directory Handler

Implements the /.ai/ virtual directory that provides AI-native file system features.
This directory doesn't exist on disk - it's computed on-the-fly by the FUSE layer.

Virtual Paths:
    /.ai/                   - AI interface root
    /.ai/query/             - Write query, read results
    /.ai/summary/<path>     - AI summary of any file
    /.ai/related/<path>     - Related files to any file
    /.ai/by-topic/          - Semantic topic clusters
    /.ai/by-date/           - Temporal organization
    /.ai/chat/<session>     - Conversation sessions
    /.ai/status             - System status and statistics
    /.ai/graph/             - Knowledge graph queries
"""

import os
import stat
import time
import json
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


class VirtualAIHandler:
    """
    Handler for the virtual /.ai/ directory.

    All operations on paths starting with /.ai/ are routed here.
    """

    AI_ROOT = "/.ai"

    # Static subdirectories under /.ai/
    SUBDIRS = {
        "query": VirtualNodeType.QUERY,
        "summary": VirtualNodeType.SUMMARY,
        "related": VirtualNodeType.RELATED,
        "by-topic": VirtualNodeType.DIRECTORY,
        "by-date": VirtualNodeType.DIRECTORY,
        "chat": VirtualNodeType.CHAT,
        "status": VirtualNodeType.STATUS,
        "graph": VirtualNodeType.GRAPH,
    }

    def __init__(self, cognitivefs: 'CognitiveFS' = None):
        """
        Initialize virtual AI handler.

        Args:
            cognitivefs: Reference to parent CognitiveFS instance
        """
        self.cognitivefs = cognitivefs
        self.knowledge_graph = None  # Will be set when KG module is loaded

        # Query/response buffers for /.ai/query/
        self.query_buffers: Dict[str, bytes] = {}  # session_id -> query
        self.response_buffers: Dict[str, bytes] = {}  # session_id -> response

        # Chat session state
        self.chat_sessions: Dict[str, List[Dict]] = {}  # session_name -> messages

        # Cache for generated content
        self._content_cache: Dict[str, Tuple[bytes, float]] = {}  # path -> (content, timestamp)
        self._cache_ttl = 60.0  # Cache TTL in seconds

    def is_ai_path(self, path: str) -> bool:
        """Check if path is under /.ai/"""
        return path == self.AI_ROOT or path.startswith(self.AI_ROOT + "/")

    def parse_ai_path(self, path: str) -> Tuple[str, str, List[str]]:
        """
        Parse an AI path into components.

        Returns:
            (subdir, target_path, path_parts)
            e.g., "/.ai/summary/docs/file.txt" -> ("summary", "/docs/file.txt", ["summary", "docs", "file.txt"])
        """
        if not self.is_ai_path(path):
            return None, None, []

        # Remove /.ai prefix
        rel_path = path[len(self.AI_ROOT):]
        if rel_path.startswith("/"):
            rel_path = rel_path[1:]

        if not rel_path:
            return "", "", []

        parts = rel_path.split("/")
        subdir = parts[0] if parts else ""
        target_path = "/" + "/".join(parts[1:]) if len(parts) > 1 else ""

        return subdir, target_path, parts

    def getattr(self, path: str) -> Optional[Dict]:
        """
        Get attributes for a virtual AI path.

        Returns:
            stat dict or None if not found
        """
        subdir, target_path, parts = self.parse_ai_path(path)

        now = int(time.time())

        # Root /.ai/ directory
        if path == self.AI_ROOT or path == self.AI_ROOT + "/":
            return self._make_dir_stat(now)

        # First-level subdirectories
        if subdir in self.SUBDIRS and not target_path:
            node_type = self.SUBDIRS[subdir]
            if node_type in (VirtualNodeType.DIRECTORY, VirtualNodeType.QUERY,
                           VirtualNodeType.CHAT, VirtualNodeType.GRAPH):
                return self._make_dir_stat(now)
            elif node_type == VirtualNodeType.STATUS:
                # Status is a file
                content = self._get_status_content()
                return self._make_file_stat(len(content), now)

        # Handle specific virtual paths
        if subdir == "query":
            return self._getattr_query(target_path, parts)
        elif subdir == "summary":
            return self._getattr_summary(target_path)
        elif subdir == "related":
            return self._getattr_related(target_path)
        elif subdir == "chat":
            return self._getattr_chat(target_path, parts)
        elif subdir == "by-topic":
            return self._getattr_by_topic(target_path, parts)
        elif subdir == "by-date":
            return self._getattr_by_date(target_path, parts)
        elif subdir == "graph":
            return self._getattr_graph(target_path, parts)

        return None

    def readdir(self, path: str) -> List[str]:
        """
        Read directory contents for a virtual AI path.

        Returns:
            List of entry names (without . and ..)
        """
        subdir, target_path, parts = self.parse_ai_path(path)

        # Root /.ai/ directory
        if path == self.AI_ROOT or path == self.AI_ROOT + "/":
            return list(self.SUBDIRS.keys())

        # Handle specific virtual directories
        if subdir == "query":
            return self._readdir_query(target_path)
        elif subdir == "chat":
            return self._readdir_chat(target_path)
        elif subdir == "by-topic":
            return self._readdir_by_topic(target_path)
        elif subdir == "by-date":
            return self._readdir_by_date(target_path)
        elif subdir == "graph":
            return self._readdir_graph(target_path)
        elif subdir in ("summary", "related"):
            # These mirror the real filesystem structure
            return self._readdir_mirror(target_path)

        return []

    def read(self, path: str, size: int, offset: int) -> bytes:
        """
        Read content from a virtual AI path.

        Returns:
            File content bytes
        """
        subdir, target_path, parts = self.parse_ai_path(path)

        content = b""

        if subdir == "status":
            content = self._get_status_content()
        elif subdir == "query":
            content = self._read_query(target_path, parts)
        elif subdir == "summary":
            content = self._read_summary(target_path)
        elif subdir == "related":
            content = self._read_related(target_path)
        elif subdir == "chat":
            content = self._read_chat(target_path, parts)
        elif subdir == "graph":
            content = self._read_graph(target_path, parts)

        return content[offset:offset + size]

    def write(self, path: str, data: bytes, offset: int) -> int:
        """
        Write content to a virtual AI path.

        Returns:
            Number of bytes written
        """
        subdir, target_path, parts = self.parse_ai_path(path)

        if subdir == "query":
            return self._write_query(target_path, parts, data, offset)
        elif subdir == "chat":
            return self._write_chat(target_path, parts, data, offset)

        # Most virtual paths are read-only
        return 0

    def create(self, path: str, mode: int) -> bool:
        """
        Create a virtual file (for query/chat sessions).

        Returns:
            True if created, False otherwise
        """
        subdir, target_path, parts = self.parse_ai_path(path)

        if subdir == "query" and len(parts) == 2:
            # Create a new query session
            session_id = parts[1]
            self.query_buffers[session_id] = b""
            self.response_buffers[session_id] = b""
            return True
        elif subdir == "chat" and len(parts) == 2:
            # Create a new chat session
            session_name = parts[1]
            if session_name not in self.chat_sessions:
                self.chat_sessions[session_name] = []
            return True

        return False

    def unlink(self, path: str) -> bool:
        """
        Delete a virtual file.

        Returns:
            True if deleted, False otherwise
        """
        subdir, target_path, parts = self.parse_ai_path(path)

        if subdir == "query" and len(parts) == 2:
            session_id = parts[1]
            self.query_buffers.pop(session_id, None)
            self.response_buffers.pop(session_id, None)
            return True
        elif subdir == "chat" and len(parts) == 2:
            session_name = parts[1]
            self.chat_sessions.pop(session_name, None)
            return True

        return False

    # ==================== Helper methods ====================

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

    def _make_file_stat(self, size: int, mtime: int) -> Dict:
        """Create stat dict for a file."""
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

    # ==================== Status ====================

    def _get_status_content(self) -> bytes:
        """Generate status content."""
        status = {
            "filesystem": "CognitiveFS",
            "version": "0.1.0",
            "status": "mounted",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        if self.cognitivefs and self.cognitivefs.superblock:
            sb = self.cognitivefs.superblock
            status.update({
                "uuid": sb.uuid.hex(),
                "total_blocks": sb.total_blocks,
                "free_blocks": sb.free_blocks,
                "total_inodes": sb.total_inodes,
                "free_inodes": sb.free_inodes,
                "capacity_bytes": sb.total_blocks * 4096,
                "used_bytes": (sb.total_blocks - sb.free_blocks) * 4096,
            })

        status.update({
            "active_query_sessions": len(self.query_buffers),
            "active_chat_sessions": len(self.chat_sessions),
            "knowledge_graph_loaded": self.knowledge_graph is not None,
        })

        return json.dumps(status, indent=2).encode('utf-8') + b"\n"

    # ==================== Query operations ====================

    def _getattr_query(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for query paths."""
        now = int(time.time())

        if not target_path:
            # /.ai/query/ directory
            return self._make_dir_stat(now)

        if len(parts) == 2:
            # /.ai/query/<session_id>
            session_id = parts[1]
            if session_id in self.query_buffers or session_id in self.response_buffers:
                response = self.response_buffers.get(session_id, b"")
                return self._make_file_stat(len(response), now)
            # Allow creation of new sessions
            return self._make_file_stat(0, now)

        return None

    def _readdir_query(self, target_path: str) -> List[str]:
        """List query sessions."""
        if not target_path:
            # List all active query sessions
            sessions = set(self.query_buffers.keys()) | set(self.response_buffers.keys())
            return list(sessions)
        return []

    def _read_query(self, target_path: str, parts: List[str]) -> bytes:
        """Read query response."""
        if len(parts) == 2:
            session_id = parts[1]
            return self.response_buffers.get(session_id, b"No response yet. Write a query first.\n")
        return b""

    def _write_query(self, target_path: str, parts: List[str], data: bytes, offset: int) -> int:
        """Write query and generate response."""
        if len(parts) == 2:
            session_id = parts[1]

            # Append or set query
            if offset == 0:
                self.query_buffers[session_id] = data
            else:
                existing = self.query_buffers.get(session_id, b"")
                self.query_buffers[session_id] = existing + data

            # Process query and generate response
            query_text = self.query_buffers[session_id].decode('utf-8', errors='replace').strip()
            response = self._process_query(query_text)
            self.response_buffers[session_id] = response.encode('utf-8')

            return len(data)
        return 0

    def _process_query(self, query: str) -> str:
        """
        Process a natural language query against the knowledge graph.

        This is a placeholder - full implementation requires the KG module.
        """
        if not query:
            return "Please enter a query.\n"

        # Placeholder response until KG is implemented
        response_lines = [
            f"Query: {query}",
            "",
            "Knowledge Graph Status: Not yet implemented",
            "",
            "This query interface will search:",
            "  - File contents and metadata",
            "  - Extracted entities and relationships",
            "  - Semantic embeddings",
            "",
            "Example queries:",
            "  'What do I know about machine learning?'",
            "  'Show files related to project X'",
            "  'Find documents from last week'",
            "",
        ]

        return "\n".join(response_lines)

    # ==================== Summary operations ====================

    def _getattr_summary(self, target_path: str) -> Optional[Dict]:
        """Get attributes for summary paths."""
        now = int(time.time())

        if not target_path:
            # /.ai/summary/ directory - mirrors root
            return self._make_dir_stat(now)

        # Check if the target file exists in real filesystem
        if self.cognitivefs:
            real_inode = self.cognitivefs._resolve_path(target_path)
            if real_inode:
                # Return file stat for the summary
                summary = self._generate_summary(target_path)
                return self._make_file_stat(len(summary), now)

        return None

    def _read_summary(self, target_path: str) -> bytes:
        """Read AI-generated summary of a file."""
        if not target_path:
            return b"Specify a file path to summarize.\n"

        # Check cache
        cache_key = f"summary:{target_path}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        summary = self._generate_summary(target_path)
        self._set_cached(cache_key, summary)
        return summary

    def _generate_summary(self, target_path: str) -> bytes:
        """
        Generate AI summary for a file.

        Placeholder until LLM integration is complete.
        """
        lines = [
            f"# Summary: {target_path}",
            "",
            "AI Summary generation not yet implemented.",
            "",
            "When implemented, this will:",
            "  - Read the file content",
            "  - Extract key points and themes",
            "  - Generate a concise summary",
            "  - Include semantic metadata",
            "",
        ]

        # Try to get basic file info
        if self.cognitivefs:
            inode = self.cognitivefs._resolve_path(target_path)
            if inode:
                lines.extend([
                    f"File Information:",
                    f"  Size: {inode.size} bytes",
                    f"  Modified: {time.ctime(inode.modified_at)}",
                    f"  Inode: {inode.inode_num}",
                    "",
                ])

        return "\n".join(lines).encode('utf-8')

    # ==================== Related operations ====================

    def _getattr_related(self, target_path: str) -> Optional[Dict]:
        """Get attributes for related paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # For now, related/<path> returns a file listing related files
        if self.cognitivefs:
            real_inode = self.cognitivefs._resolve_path(target_path)
            if real_inode:
                content = self._get_related_files(target_path)
                return self._make_file_stat(len(content), now)

        return None

    def _read_related(self, target_path: str) -> bytes:
        """Get files related to the target file."""
        if not target_path:
            return b"Specify a file path to find related files.\n"

        return self._get_related_files(target_path)

    def _get_related_files(self, target_path: str) -> bytes:
        """
        Find files related to the target.

        Placeholder until embedding search is implemented.
        """
        lines = [
            f"# Related Files: {target_path}",
            "",
            "Related file search not yet implemented.",
            "",
            "When implemented, this will find files that are:",
            "  - Semantically similar (via embeddings)",
            "  - Linked in the knowledge graph",
            "  - Referenced in content",
            "  - Created/modified together",
            "",
        ]

        return "\n".join(lines).encode('utf-8')

    # ==================== Chat operations ====================

    def _getattr_chat(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for chat paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        if len(parts) == 2:
            session_name = parts[1]
            # Get chat history content
            content = self._get_chat_content(session_name)
            return self._make_file_stat(len(content), now)

        return None

    def _readdir_chat(self, target_path: str) -> List[str]:
        """List chat sessions."""
        if not target_path:
            return list(self.chat_sessions.keys())
        return []

    def _read_chat(self, target_path: str, parts: List[str]) -> bytes:
        """Read chat session history."""
        if len(parts) == 2:
            session_name = parts[1]
            return self._get_chat_content(session_name)
        return b""

    def _write_chat(self, target_path: str, parts: List[str], data: bytes, offset: int) -> int:
        """Write to chat session (send message)."""
        if len(parts) == 2:
            session_name = parts[1]
            message = data.decode('utf-8', errors='replace').strip()

            if message:
                # Add user message
                if session_name not in self.chat_sessions:
                    self.chat_sessions[session_name] = []

                self.chat_sessions[session_name].append({
                    "role": "user",
                    "content": message,
                    "timestamp": time.time(),
                })

                # Generate AI response (placeholder)
                response = self._generate_chat_response(session_name, message)
                self.chat_sessions[session_name].append({
                    "role": "assistant",
                    "content": response,
                    "timestamp": time.time(),
                })

            return len(data)
        return 0

    def _get_chat_content(self, session_name: str) -> bytes:
        """Format chat session as readable text."""
        messages = self.chat_sessions.get(session_name, [])

        if not messages:
            return b"Chat session is empty. Write a message to start.\n"

        lines = [f"# Chat Session: {session_name}", ""]

        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            ts = msg.get("timestamp", 0)
            time_str = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else ""

            lines.append(f"[{time_str}] {role}:")
            lines.append(content)
            lines.append("")

        return "\n".join(lines).encode('utf-8')

    def _generate_chat_response(self, session_name: str, message: str) -> str:
        """
        Generate AI chat response.

        Placeholder until LLM integration is complete.
        """
        return (
            "AI chat responses not yet implemented.\n"
            "When complete, I'll be able to:\n"
            "  - Answer questions about your files\n"
            "  - Search the knowledge graph\n"
            "  - Help with file organization\n"
            "  - Provide summaries and insights\n"
        )

    # ==================== By-topic operations ====================

    def _getattr_by_topic(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for by-topic paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # Each topic is a directory containing symlinks to files
        if len(parts) == 2:
            return self._make_dir_stat(now)

        return None

    def _readdir_by_topic(self, target_path: str) -> List[str]:
        """List topics or files in a topic."""
        if not target_path:
            # Return discovered topics (placeholder)
            return ["uncategorized"]
        return []

    # ==================== By-date operations ====================

    def _getattr_by_date(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for by-date paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # Date hierarchy: year/month/day
        if len(parts) <= 4:
            return self._make_dir_stat(now)

        return None

    def _readdir_by_date(self, target_path: str) -> List[str]:
        """List date hierarchy or files."""
        if not target_path:
            # Return years with content (placeholder)
            return [time.strftime("%Y")]
        return []

    # ==================== Graph operations ====================

    def _getattr_graph(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for graph paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # Various graph query endpoints
        if len(parts) == 2:
            query_type = parts[1]
            if query_type in ("entities", "relationships", "stats"):
                content = self._get_graph_content(query_type)
                return self._make_file_stat(len(content), now)

        return None

    def _readdir_graph(self, target_path: str) -> List[str]:
        """List graph query endpoints."""
        if not target_path:
            return ["entities", "relationships", "stats"]
        return []

    def _read_graph(self, target_path: str, parts: List[str]) -> bytes:
        """Read graph query results."""
        if len(parts) == 2:
            return self._get_graph_content(parts[1])
        return b""

    def _get_graph_content(self, query_type: str) -> bytes:
        """Get knowledge graph data."""
        if query_type == "stats":
            stats = {
                "status": "not_initialized",
                "entities": 0,
                "relationships": 0,
                "files_indexed": 0,
            }
            return json.dumps(stats, indent=2).encode('utf-8') + b"\n"
        elif query_type == "entities":
            return b"# Entities\n\nNo entities indexed yet.\n"
        elif query_type == "relationships":
            return b"# Relationships\n\nNo relationships indexed yet.\n"
        return b""

    # ==================== Mirror operations ====================

    def _readdir_mirror(self, target_path: str) -> List[str]:
        """Mirror the real filesystem structure for summary/related."""
        if not self.cognitivefs:
            return []

        # Get the real directory contents
        path = target_path if target_path else "/"
        inode = self.cognitivefs._resolve_path(path)

        if not inode or inode.inode_type != 2:  # Not a directory
            return []

        entries = self.cognitivefs._read_directory_entries(inode)
        return [e.name for e in entries if e.name not in (".", "..")]
