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
        "search": VirtualNodeType.DIRECTORY,  # Full-text search with content snippets
        "summary": VirtualNodeType.SUMMARY,
        "related": VirtualNodeType.RELATED,
        "similar": VirtualNodeType.DIRECTORY,  # Embedding-based similarity search
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
        elif subdir == "search":
            return self._getattr_search(target_path, parts)
        elif subdir == "similar":
            return self._getattr_similar(target_path, parts)
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
        elif subdir == "search":
            return self._readdir_search(target_path)
        elif subdir == "similar":
            return self._readdir_similar(target_path)
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
        elif subdir == "search":
            content = self._read_search(target_path, parts)
        elif subdir == "similar":
            content = self._read_similar(target_path, parts)

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

        # Add knowledge graph statistics if available
        if self.knowledge_graph:
            kg_stats = self.knowledge_graph.get_stats()
            status["knowledge_graph"] = kg_stats

            # Add processing queue stats
            queue_stats = self.knowledge_graph.get_queue_stats()
            status["processing_queue"] = queue_stats

        # Add processor status if available
        if self.cognitivefs and self.cognitivefs.processor:
            proc_stats = self.cognitivefs.processor.get_stats()
            status["processor"] = {
                "running": proc_stats.get("running", False),
                "embedding_available": proc_stats.get("embedding_available", False),
            }

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
        Find files related to the target using multiple signals:
        1. Embedding similarity (semantic relatedness)
        2. Shared entities (knowledge graph connections)
        3. Co-references (files that mention each other)
        """
        if not self.knowledge_graph:
            return b"Knowledge graph not initialized.\n"

        # Normalize path
        if not target_path.startswith("/"):
            target_path = "/" + target_path

        # Get file record
        file_record = self.knowledge_graph.get_file(target_path)
        if not file_record:
            return f"File not indexed: {target_path}\nTry writing to the file first.\n".encode('utf-8')

        lines = [
            f"# Files Related to: {target_path}",
            ""
        ]

        similar = []  # Initialize for later reference

        # 1. Embedding-based similarity
        if file_record.embedding_id:
            file_emb = self.knowledge_graph.get_embedding(file_id=file_record.id)
            if file_emb and file_emb.vector:
                lines.append("## Semantically Similar (by content)")
                similar = self._get_similar_files_for_embedding(
                    file_emb.vector,
                    exclude_path=target_path,
                    limit=10
                )
                if similar:
                    for sim, path, summary in similar:
                        lines.append(f"  [{sim:.3f}] {path}")
                else:
                    lines.append("  No similar files found.")
                lines.append("")

        # 2. Shared entities (knowledge graph)
        shared_entity_files = self._get_files_sharing_entities(file_record.id, target_path)
        if shared_entity_files:
            lines.append("## Share Common Entities")
            for path, shared_entities in shared_entity_files[:10]:
                entity_list = ", ".join(shared_entities[:3])
                if len(shared_entities) > 3:
                    entity_list += f" (+{len(shared_entities)-3} more)"
                lines.append(f"  {path}")
                lines.append(f"    └─ shared: {entity_list}")
            lines.append("")

        # 3. Summary
        total_related = len(similar) + len(shared_entity_files)

        if total_related == 0:
            lines.append("No related files found yet.")
            lines.append("Related files are discovered through:")
            lines.append("  - Semantic similarity (embeddings)")
            lines.append("  - Shared entities (people, places, concepts)")
            lines.append("")

        return "\n".join(lines).encode('utf-8')

    def _get_similar_files_for_embedding(self, query_vec: bytes, exclude_path: str = None,
                                          limit: int = 10) -> List[Tuple[float, str, str]]:
        """Get files similar to a given embedding vector."""
        from .embedder import cosine_similarity

        cursor = self.knowledge_graph.conn.cursor()
        cursor.execute("""
            SELECT f.path, f.summary, e.vector
            FROM files f
            JOIN embeddings e ON f.embedding_id = e.id
            WHERE e.vector IS NOT NULL
        """)

        results = []
        for row in cursor.fetchall():
            path = row['path']
            if exclude_path and path == exclude_path:
                continue

            # Verify file still exists on disk
            if self.cognitivefs and not self.cognitivefs._resolve_path(path):
                continue

            summary = row['summary'] or ""
            file_vec = row['vector']
            sim = cosine_similarity(query_vec, file_vec)
            if sim > 0.1:  # Threshold for relevance
                results.append((sim, path, summary))

        results.sort(reverse=True, key=lambda x: x[0])
        return results[:limit]

    def _get_files_sharing_entities(self, file_id: int, exclude_path: str) -> List[Tuple[str, List[str]]]:
        """Find files that share entities with the given file."""
        cursor = self.knowledge_graph.conn.cursor()

        # Get entities for this file
        cursor.execute("""
            SELECT DISTINCT e.name, e.entity_type
            FROM file_entities fe
            JOIN entities e ON fe.entity_id = e.id
            WHERE fe.file_id = ?
        """, (file_id,))

        file_entities = [(row['name'], row['entity_type']) for row in cursor.fetchall()]
        if not file_entities:
            return []

        # Find other files with same entities
        entity_names = [e[0] for e in file_entities]
        placeholders = ",".join("?" * len(entity_names))

        cursor.execute(f"""
            SELECT f.path, GROUP_CONCAT(DISTINCT e.name) as shared_entities
            FROM files f
            JOIN file_entities fe ON f.id = fe.file_id
            JOIN entities e ON fe.entity_id = e.id
            WHERE e.name IN ({placeholders})
              AND f.path != ?
            GROUP BY f.id
            ORDER BY COUNT(DISTINCT e.id) DESC
            LIMIT 20
        """, (*entity_names, exclude_path))

        results = []
        for row in cursor.fetchall():
            path = row['path']
            # Verify file still exists on disk
            if self.cognitivefs and not self.cognitivefs._resolve_path(path):
                continue
            shared = row['shared_entities'].split(",") if row['shared_entities'] else []
            results.append((path, shared))

        return results

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
        if not self.knowledge_graph:
            if query_type == "stats":
                return json.dumps({"status": "not_initialized"}, indent=2).encode('utf-8') + b"\n"
            return b"Knowledge graph not initialized.\n"

        if query_type == "stats":
            stats = self.knowledge_graph.get_stats()
            stats["status"] = "initialized"
            return json.dumps(stats, indent=2).encode('utf-8') + b"\n"

        elif query_type == "entities":
            lines = ["# Entities in Knowledge Graph", ""]

            # Get entities by type
            from .knowledge_graph import EntityType
            for et in EntityType:
                entities = self.knowledge_graph.get_entities_by_type(et, limit=50)
                if entities:
                    lines.append(f"## {et.value.title()} ({len(entities)})")
                    for e in entities[:20]:
                        lines.append(f"  - {e.name} (refs: {e.source_count})")
                    if len(entities) > 20:
                        lines.append(f"  ... and {len(entities) - 20} more")
                    lines.append("")

            if len(lines) == 2:
                lines.append("No entities indexed yet.")

            return "\n".join(lines).encode('utf-8')

        elif query_type == "relationships":
            lines = ["# Relationships in Knowledge Graph", ""]

            # Get stats by relationship type
            stats = self.knowledge_graph.get_stats()
            rel_count = stats.get('relationships', 0)

            if rel_count == 0:
                lines.append("No relationships indexed yet.")
            else:
                lines.append(f"Total relationships: {rel_count}")
                lines.append("")
                lines.append("Relationship types are discovered through:")
                lines.append("  - Entity co-occurrence in files")
                lines.append("  - Explicit references and links")
                lines.append("  - Semantic similarity")

            return "\n".join(lines).encode('utf-8')

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

        entries = self.cognitivefs._read_directory(inode)
        return [e.name for e in entries if e.name not in (".", "..")]

    # ==================== Search (full-text with snippets) operations ====================

    def _getattr_search(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for search paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        return self._make_file_stat(4096, now)

    def _readdir_search(self, target_path: str) -> List[str]:
        """Read directory for search."""
        if not target_path:
            return ["_help.txt"]
        return []

    def _read_search(self, target_path: str, parts: List[str]) -> bytes:
        """
        Full-text search returning content snippets.

        Usage:
            cat /.ai/search/neural_networks     - Search for "neural networks"
            cat /.ai/search/meeting+notes       - Search for "meeting notes"
        """
        if not target_path:
            return b""

        if target_path == "_help.txt":
            return self._get_search_help()

        # Convert path to search query (strip leading /)
        query = target_path.lstrip("/").replace("_", " ").replace("-", " ").replace("+", " ")
        return self._execute_search(query)

    def _get_search_help(self) -> bytes:
        """Return help for search."""
        return b"""# Full-Text Search with Content Snippets

## Usage

Search for terms (use _ or + for spaces):
    cat /.ai/search/machine_learning
    cat /.ai/search/meeting+notes+project

## Returns

- Matching files with relevance scores
- Content snippets showing where matches occur
- Context around each match

## Example

    cat /.ai/search/neural_networks

Output:
    === /ai_research.txt (score: 2.5) ===
    ...Machine learning and NEURAL NETWORKS are transforming...
    ...Deep learning models can recognize patterns...
"""

    def _execute_search(self, query: str) -> bytes:
        """Execute full-text search and return snippets."""
        if not self.knowledge_graph:
            return b"Knowledge graph not initialized.\n"

        # Use FTS5 full-text search
        cursor = self.knowledge_graph.conn.cursor()

        try:
            # Search in files_fts (path, summary, extracted_text)
            cursor.execute("""
                SELECT f.path, f.extracted_text, f.summary,
                       bm25(files_fts) as score
                FROM files_fts
                JOIN files f ON files_fts.rowid = f.id
                WHERE files_fts MATCH ?
                ORDER BY score
                LIMIT 10
            """, (query,))

            results = cursor.fetchall()
        except Exception as e:
            # FTS query error - try simple LIKE search
            like_pattern = f"%{query}%"
            cursor.execute("""
                SELECT path, extracted_text, summary, 0 as score
                FROM files
                WHERE extracted_text LIKE ? OR path LIKE ?
                ORDER BY modified_at DESC
                LIMIT 10
            """, (like_pattern, like_pattern))
            results = cursor.fetchall()

        if not results:
            return f"No results found for: {query}\n".encode('utf-8')

        # Format results with snippets
        lines = [
            f"# Search results for: {query}",
            f"# Found {len(results)} matching files",
            ""
        ]

        for row in results:
            path = row['path']
            text = row['extracted_text'] or ""
            summary = row['summary'] or ""
            score = abs(row['score']) if row['score'] else 0

            lines.append(f"═══ {path} (relevance: {score:.1f}) ═══")

            # Find and show snippets containing the query terms
            snippets = self._extract_snippets(text, query, max_snippets=3)
            if snippets:
                for snippet in snippets:
                    lines.append(f"  ...{snippet}...")
            elif summary:
                lines.append(f"  Summary: {summary[:200]}")
            elif text:
                lines.append(f"  {text[:200]}...")

            lines.append("")

        return "\n".join(lines).encode('utf-8')

    def _extract_snippets(self, text: str, query: str, max_snippets: int = 3,
                          context_chars: int = 80) -> List[str]:
        """Extract text snippets around query matches."""
        if not text:
            return []

        snippets = []
        query_lower = query.lower()
        text_lower = text.lower()
        query_terms = query_lower.split()

        # Find positions of query terms
        positions = []
        for term in query_terms:
            pos = 0
            while True:
                pos = text_lower.find(term, pos)
                if pos == -1:
                    break
                positions.append((pos, len(term)))
                pos += 1

        # Sort by position and deduplicate nearby matches
        positions.sort()
        used_ranges = []

        for pos, term_len in positions:
            if len(snippets) >= max_snippets:
                break

            # Check if this position overlaps with already used ranges
            overlaps = False
            for start, end in used_ranges:
                if start - context_chars <= pos <= end + context_chars:
                    overlaps = True
                    break

            if overlaps:
                continue

            # Extract snippet
            start = max(0, pos - context_chars)
            end = min(len(text), pos + term_len + context_chars)

            snippet = text[start:end].replace('\n', ' ').strip()

            # Highlight the match (uppercase)
            match_start = pos - start
            match_end = match_start + term_len
            if 0 <= match_start < len(snippet):
                snippet = (snippet[:match_start] +
                          snippet[match_start:match_end].upper() +
                          snippet[match_end:])

            snippets.append(snippet)
            used_ranges.append((start, end))

        return snippets

    # ==================== Similar (embedding-based) operations ====================

    def _getattr_similar(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for similar paths (embedding-based similarity search)."""
        now = int(time.time())

        # /.ai/similar/ - directory listing available queries
        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files and other editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None  # File not found

        # /.ai/similar/<query> - return a placeholder size (actual content computed on read)
        # Don't compute embeddings here - too expensive for getattr
        return self._make_file_stat(4096, now)  # Placeholder size

    def _readdir_similar(self, target_path: str) -> List[str]:
        """Read directory for similar searches."""
        if not target_path:
            # Return recent queries or example searches
            return ["_help.txt"]
        return []

    def _read_similar(self, target_path: str, parts: List[str]) -> bytes:
        """
        Read similar files based on embedding similarity.

        Usage:
            cat /.ai/similar/_help.txt          - Show help
            cat /.ai/similar/<query>            - Find files similar to query text
            cat /.ai/similar/path/to/file.txt   - Find files similar to given file
        """
        if not target_path:
            return b""

        if target_path == "_help.txt":
            return self._get_similar_help()

        # Check if it's a query for similar files to an existing file
        if self.cognitivefs:
            inode = self.cognitivefs._resolve_path("/" + target_path)
            if inode:
                return self._find_similar_to_file("/" + target_path)

        # Otherwise treat as a query string
        query_text = target_path.replace("_", " ").replace("-", " ")
        return self._find_similar_to_query(query_text)

    def _get_similar_help(self) -> bytes:
        """Return help text for similarity search."""
        help_text = """# Embedding-Based Similarity Search

## Usage

Find files similar to a query:
    cat /.ai/similar/machine_learning
    cat /.ai/similar/neural-networks

Find files similar to an existing file:
    cat /.ai/similar/path/to/file.txt

## How it works

1. Files are embedded using sentence-transformers (all-MiniLM-L6-v2)
2. Your query is also embedded
3. Cosine similarity finds the most similar files

## Notes

- Embeddings are generated when files are written
- Query words separated by _ or - become spaces
- Results show similarity scores (0-1, higher = more similar)
"""
        return help_text.encode('utf-8')

    def _find_similar_to_query(self, query: str) -> bytes:
        """Find files similar to a text query using embeddings."""
        if not self.knowledge_graph:
            return b"Knowledge graph not initialized.\n"

        # Check if processor is available for embedding generation
        if not self.cognitivefs or not self.cognitivefs.processor:
            return b"Processor not available for embedding generation.\n"

        if not self.cognitivefs.processor.embedding_generator.is_available:
            return b"Embeddings not available. Install sentence-transformers.\n"

        # Generate query embedding
        query_vec = self.cognitivefs.processor.embedding_generator.generate(query)
        if not query_vec:
            return b"Failed to generate query embedding.\n"

        # Get all file embeddings and compute similarity
        return self._compute_similarities(query, query_vec)

    def _find_similar_to_file(self, file_path: str) -> bytes:
        """Find files similar to an existing file."""
        if not self.knowledge_graph:
            return b"Knowledge graph not initialized.\n"

        # Get file record
        file_record = self.knowledge_graph.get_file(file_path)
        if not file_record:
            return f"File not indexed: {file_path}\n".encode('utf-8')

        if not file_record.embedding_id:
            return f"No embedding for file: {file_path}\n".encode('utf-8')

        # Get file embedding
        file_emb = self.knowledge_graph.get_embedding(file_id=file_record.id)
        if not file_emb or not file_emb.vector:
            return f"Embedding not found for: {file_path}\n".encode('utf-8')

        return self._compute_similarities(f"files similar to {file_path}", file_emb.vector)

    def _compute_similarities(self, query_desc: str, query_vec: bytes) -> bytes:
        """Compute similarities between query vector and all file embeddings."""
        from .embedder import cosine_similarity

        # Get all files with embeddings
        cursor = self.knowledge_graph.conn.cursor()
        cursor.execute("""
            SELECT f.path, f.summary, e.vector
            FROM files f
            JOIN embeddings e ON f.embedding_id = e.id
            WHERE e.vector IS NOT NULL
        """)

        results = []
        for row in cursor.fetchall():
            path = row['path']

            # Verify file still exists on disk
            if self.cognitivefs and not self.cognitivefs._resolve_path(path):
                continue

            summary = row['summary'] or ""
            file_vec = row['vector']

            # Compute similarity
            sim = cosine_similarity(query_vec, file_vec)
            results.append((sim, path, summary))

        # Sort by similarity (descending)
        results.sort(reverse=True, key=lambda x: x[0])

        # Format output
        lines = [
            f"# Files similar to: {query_desc}",
            f"# Found {len(results)} files with embeddings",
            ""
        ]

        if not results:
            lines.append("No files with embeddings found.")
            lines.append("Write some files to generate embeddings.")
        else:
            for sim, path, summary in results[:20]:  # Top 20
                lines.append(f"[{sim:.3f}] {path}")
                if summary:
                    lines.append(f"        {summary[:80]}")

        return "\n".join(lines).encode('utf-8')
