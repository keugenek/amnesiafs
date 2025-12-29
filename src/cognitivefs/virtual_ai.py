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

# Import generators for dual-view files
from .generators import GeneratorFactory


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
        "entities": VirtualNodeType.DIRECTORY,  # Show entities extracted from a file
        "by-topic": VirtualNodeType.DIRECTORY,
        "by-date": VirtualNodeType.DIRECTORY,
        "chat": VirtualNodeType.CHAT,
        "status": VirtualNodeType.DIRECTORY,  # Status dir with index, etc.
        "graph": VirtualNodeType.GRAPH,
        "versions": VirtualNodeType.DIRECTORY,  # Git-backed version history
    }

    # Auto-generated dual-view files that appear in every virtual folder
    GENERATED_FILES = ['_DASHBOARD.html', '_manifest.md', '_index.json']

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

        # Async query system
        self._query_results: Dict[str, Dict] = {}  # query_id -> {status, result, query}
        self._query_counter = 0
        self._query_thread = None
        self._query_lock = __import__('threading').Lock()

        # Chat session state
        self.chat_sessions: Dict[str, List[Dict]] = {}  # session_name -> messages

        # Cache for generated content
        self._content_cache: Dict[str, Tuple[bytes, float]] = {}  # path -> (content, timestamp)
        self._cache_ttl = 60.0  # Cache TTL in seconds

        # Generator factory for dual-view files (_DASHBOARD.html, _manifest.md, _index.json)
        self._generator_factory = GeneratorFactory(None)  # KG will be set later

    def set_knowledge_graph(self, kg):
        """Set the knowledge graph reference for generators."""
        self.knowledge_graph = kg
        self._generator_factory.kg = kg

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

        # Check for generated dual-view files in any subdir
        filename = parts[-1] if parts else None
        if filename in self.GENERATED_FILES and subdir in self.SUBDIRS:
            virtual_path = f"/.ai/{subdir}"
            content = self._generator_factory.get_cached_or_generate(virtual_path, filename, self.cognitivefs)
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
        elif subdir == "entities":
            return self._getattr_entities(target_path, parts)
        elif subdir == "by-topic":
            return self._getattr_by_topic(target_path, parts)
        elif subdir == "by-date":
            return self._getattr_by_date(target_path, parts)
        elif subdir == "graph":
            return self._getattr_graph(target_path, parts)
        elif subdir == "status":
            # Status with subpath (e.g., /.ai/status/index)
            content = self._read_status(target_path, parts)
            return self._make_file_stat(len(content), now)
        elif subdir == "versions":
            return self._getattr_versions(target_path, parts)

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

        entries = []

        # Handle specific virtual directories
        if subdir == "query":
            entries = self._readdir_query(target_path)
        elif subdir == "chat":
            entries = self._readdir_chat(target_path)
        elif subdir == "by-topic":
            entries = self._readdir_by_topic(target_path)
        elif subdir == "by-date":
            entries = self._readdir_by_date(target_path)
        elif subdir == "graph":
            entries = self._readdir_graph(target_path)
        elif subdir == "search":
            entries = self._readdir_search(target_path)
        elif subdir == "similar":
            entries = self._readdir_similar(target_path)
        elif subdir == "entities":
            entries = self._readdir_entities(target_path)
        elif subdir in ("summary", "related"):
            # These mirror the real filesystem structure
            entries = self._readdir_mirror(target_path)
        elif subdir == "status":
            # List available status endpoints
            entries = ["index", "overview"]
        elif subdir == "versions":
            entries = self._readdir_versions(target_path, parts)

        # Add generated dual-view files to first-level subdirectories
        if subdir in self.SUBDIRS and not target_path:
            entries = list(entries) + self.GENERATED_FILES

        return entries

    def read(self, path: str, size: int, offset: int) -> bytes:
        """
        Read content from a virtual AI path.

        Returns:
            File content bytes
        """
        subdir, target_path, parts = self.parse_ai_path(path)

        content = b""

        # Check for generated dual-view files first
        filename = parts[-1] if parts else None
        if filename in self.GENERATED_FILES and subdir in self.SUBDIRS:
            virtual_path = f"/.ai/{subdir}"
            content = self._generator_factory.get_cached_or_generate(virtual_path, filename, self.cognitivefs)
            return content[offset:offset + size]

        if subdir == "status":
            content = self._read_status(target_path, parts)
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
        elif subdir == "entities":
            content = self._read_entities(target_path, parts)
        elif subdir == "by-topic":
            content = self._read_by_topic(target_path, parts)
        elif subdir == "versions":
            content = self._read_versions(target_path, parts)

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

    def _read_status(self, target_path: str, parts: List[str]) -> bytes:
        """Read status information with optional subpath."""
        if not target_path or target_path == "/":
            return self._get_status_content()

        # Handle /.ai/status/index - detailed indexing status
        if target_path in ("/index", "index"):
            return self._get_index_status()

        # Handle /.ai/status/overview - general status
        if target_path in ("/overview", "overview"):
            return self._get_status_content()

        return self._get_status_content()

    def _get_index_status(self) -> bytes:
        """Get detailed indexing status."""
        lines = [
            "# Index Status",
            f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            ""
        ]

        if not self.knowledge_graph:
            lines.append("Knowledge graph not initialized.")
            return "\n".join(lines).encode('utf-8')

        # Get file counts
        try:
            cursor = self.knowledge_graph.conn.cursor()

            # Total indexed files
            cursor.execute("SELECT COUNT(*) FROM files")
            total_files = cursor.fetchone()[0]

            # Files with embeddings
            cursor.execute("SELECT COUNT(*) FROM files WHERE embedding_id IS NOT NULL")
            files_with_embeddings = cursor.fetchone()[0]

            # Files with extracted text
            cursor.execute("SELECT COUNT(*) FROM files WHERE extracted_text IS NOT NULL AND extracted_text != ''")
            files_with_text = cursor.fetchone()[0]

            # Most recent file
            cursor.execute("SELECT path, updated_at FROM files ORDER BY updated_at DESC LIMIT 1")
            recent = cursor.fetchone()
            last_indexed_path = recent[0] if recent else "N/A"
            last_indexed_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(recent[1])) if recent else "N/A"

            # Calculate embedding coverage (BUG-004 fix)
            files_without_embeddings = total_files - files_with_embeddings
            coverage = (files_with_embeddings / total_files * 100) if total_files else 0

            lines.append("## Files")
            lines.append(f"  Total indexed: {total_files}")
            lines.append(f"  With embeddings: {files_with_embeddings}")
            lines.append(f"  Without embeddings: {files_without_embeddings}")
            lines.append(f"  Embedding coverage: {coverage:.1f}%")
            lines.append(f"  With extracted text: {files_with_text}")
            lines.append(f"  Last indexed: {last_indexed_path}")
            lines.append(f"  Last indexed at: {last_indexed_time}")
            lines.append("")

            # Entity counts
            cursor.execute("SELECT COUNT(*) FROM entities")
            total_entities = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM relationships")
            total_relationships = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM embeddings")
            total_embeddings = cursor.fetchone()[0]

            lines.append("## Knowledge Graph")
            lines.append(f"  Entities: {total_entities}")
            lines.append(f"  Relationships: {total_relationships}")
            lines.append(f"  Embeddings: {total_embeddings}")
            lines.append("")

            # Processing queue
            cursor.execute("SELECT COUNT(*) FROM processing_queue WHERE status = 'pending'")
            pending = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM processing_queue WHERE status = 'processing'")
            processing = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM processing_queue WHERE status = 'completed'")
            completed = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM processing_queue WHERE status = 'failed'")
            failed = cursor.fetchone()[0]

            lines.append("## Processing Queue")
            lines.append(f"  Pending: {pending}")
            lines.append(f"  Processing: {processing}")
            lines.append(f"  Completed: {completed}")
            lines.append(f"  Failed: {failed}")
            lines.append("")

            # Processor status
            if self.cognitivefs and self.cognitivefs.processor:
                proc_stats = self.cognitivefs.processor.get_stats()
                lines.append("## Processor")
                lines.append(f"  Running: {proc_stats.get('running', False)}")
                lines.append(f"  Embedding available: {proc_stats.get('embedding_available', False)}")
                lines.append("")

        except Exception as e:
            lines.append(f"Error getting index status: {e}")

        return "\n".join(lines).encode('utf-8')

    # ==================== Query operations ====================

    def _getattr_query(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for query paths."""
        now = int(time.time())

        if not target_path:
            # /.ai/query/ directory
            return self._make_dir_stat(now)

        # Reject temp files and editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        # Any path under /.ai/query/ is a valid query file
        # The query text is derived from the filename
        return self._make_file_stat(4096, now)  # Placeholder size

    def _readdir_query(self, target_path: str) -> List[str]:
        """List query help."""
        if not target_path:
            return ["_help.txt"]
        return []

    def _read_query(self, target_path: str, parts: List[str]) -> bytes:
        """
        Read query response.

        Usage: cat /.ai/query/<query_text>
        Replace spaces with underscores or + in the query.
        Example: cat /.ai/query/what_is_machine_learning
        """
        if not target_path:
            return b""

        if target_path == "/_help.txt":
            return self._get_query_help()

        # Convert path to query text
        query_text = target_path.lstrip("/").replace("_", " ").replace("+", " ").replace("-", " ")
        return self._process_query(query_text).encode('utf-8')

    def _get_query_help(self) -> bytes:
        """Return help text for query."""
        return b"""# Natural Language Query Interface (Async)

## Usage

Submit a query (returns immediately with ID):
    cat /.ai/query/what_is_machine_learning

Check results (poll until complete):
    cat /.ai/query/results/q1

List all queries:
    cat /.ai/query/pending

## How It Works

1. Query is queued and processed in background (non-blocking)
2. Returns query ID immediately
3. Poll results endpoint until status is 'complete'
4. LLM generates answer using indexed file context

## Tips

- Use underscores (_) for spaces in query path
- Queries run in background - won't freeze filesystem
- Results are cached until filesystem restart
"""

    def _write_query(self, target_path: str, parts: List[str], data: bytes, offset: int) -> int:
        """Write query - no longer used (query via path instead)."""
        return 0

    def _process_query(self, query: str) -> str:
        """
        Process a natural language query - queues for async processing.

        Returns immediately with query ID. Check results via:
          cat /.ai/query/results/<id>
        """
        if not query:
            return "Please enter a query.\n"

        # Check if this is a results request
        if query.startswith("results/"):
            query_id = query[8:]
            return self._get_query_result(query_id)

        # Check if this is a debug request (shows context used)
        if query.startswith("debug/"):
            query_id = query[6:]
            return self._get_query_debug(query_id)

        # Check if listing pending queries
        if query == "pending":
            return self._list_pending_queries()

        # Queue new query
        query_id = self._queue_async_query(query)
        return f"Query queued with ID: {query_id}\n\nCheck results:\n  cat /.ai/query/results/{query_id}\n\nView context used:\n  cat /.ai/query/debug/{query_id}\n\nList pending:\n  cat /.ai/query/pending\n"

    def _queue_async_query(self, query: str) -> str:
        """Queue a query for async processing."""
        import threading

        with self._query_lock:
            self._query_counter += 1
            query_id = f"q{self._query_counter}"
            self._query_results[query_id] = {
                'status': 'pending',
                'query': query,
                'result': None,
                'timestamp': time.time()
            }

        # Start background thread for this query
        thread = threading.Thread(
            target=self._run_async_query,
            args=(query_id, query),
            daemon=True
        )
        thread.start()

        return query_id

    def _run_async_query(self, query_id: str, query: str):
        """Run query in background thread."""
        try:
            from .llm import get_query_engine

            engine = get_query_engine(self.knowledge_graph)
            # Use query_with_context for full transparency
            result_data = engine.query_with_context(query)

            with self._query_lock:
                if query_id in self._query_results:
                    self._query_results[query_id]['status'] = 'complete'
                    self._query_results[query_id]['result'] = result_data.get('formatted_response', '')
                    # Store full context for debug endpoint
                    self._query_results[query_id]['context'] = {
                        'files_used': result_data.get('files_used', []),
                        'entities_used': result_data.get('entities_used', []),
                        'relationships_used': result_data.get('relationships_used', []),
                        'llm_available': result_data.get('llm_available', False)
                    }

        except Exception as e:
            with self._query_lock:
                if query_id in self._query_results:
                    self._query_results[query_id]['status'] = 'error'
                    self._query_results[query_id]['result'] = f"Error: {e}"

    def _get_query_result(self, query_id: str) -> str:
        """Get result of async query."""
        with self._query_lock:
            if query_id not in self._query_results:
                return f"Query ID not found: {query_id}\n"

            info = self._query_results[query_id]

            # Expire old results after 24 hours (BUG-002 fix)
            if time.time() - info.get('timestamp', 0) > 86400:
                del self._query_results[query_id]
                return f"Query {query_id} expired. Please rerun your query.\n"

            status = info['status']
            query = info['query']

            if status == 'pending':
                return f"Query '{query}' is still processing...\n\nTry again in a few seconds:\n  cat /.ai/query/results/{query_id}\n"
            elif status == 'complete':
                return info['result']
            else:
                return info['result']

    def _get_query_debug(self, query_id: str) -> str:
        """Get debug info showing context used for a query."""
        with self._query_lock:
            if query_id not in self._query_results:
                return f"Query ID not found: {query_id}\n"

            info = self._query_results[query_id]
            status = info['status']
            query = info['query']

            if status == 'pending':
                return f"Query '{query}' is still processing...\n\nTry again in a few seconds.\n"

            lines = [
                f"# Query Debug: {query_id}",
                f"Question: {query}",
                f"Status: {status}",
                ""
            ]

            context = info.get('context', {})

            # Files used
            files_used = context.get('files_used', [])
            lines.append(f"## Files Used ({len(files_used)})")
            if files_used:
                for f in files_used:
                    sim = f.get('similarity', 0)
                    lines.append(f"  - {f['path']} (similarity: {sim:.3f})")
            else:
                lines.append("  (none)")
            lines.append("")

            # Entities used
            entities_used = context.get('entities_used', [])
            lines.append(f"## Entities Used ({len(entities_used)})")
            if entities_used:
                for e in entities_used:
                    lines.append(f"  - {e['name']} ({e['type']}, {e['refs']} refs) [source: {e['source']}]")
            else:
                lines.append("  (none)")
            lines.append("")

            # Relationships used
            relationships_used = context.get('relationships_used', [])
            lines.append(f"## Relationships Used ({len(relationships_used)})")
            if relationships_used:
                for r in relationships_used:
                    lines.append(f"  - {r['source']} → {r['relation']} → {r['target']}")
            else:
                lines.append("  (none)")
            lines.append("")

            # LLM status
            llm_available = context.get('llm_available', False)
            lines.append(f"## LLM Status")
            lines.append(f"  Available: {llm_available}")
            lines.append("")

            return "\n".join(lines)

    def _list_pending_queries(self) -> str:
        """List all pending/completed queries."""
        lines = ["# Query Status", ""]

        with self._query_lock:
            if not self._query_results:
                lines.append("No queries.")
            else:
                for qid, info in sorted(self._query_results.items(), reverse=True):
                    status = info['status']
                    query = info['query'][:40]
                    lines.append(f"  {qid}: [{status}] {query}")

        lines.append("")
        return "\n".join(lines)

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
        Generate AI summary for a file using LLM.
        """
        lines = [f"# Summary: {target_path}", ""]

        # Get file content
        file_content = None
        file_info = None

        if self.cognitivefs:
            inode = self.cognitivefs._resolve_path(target_path)
            if inode:
                file_info = {
                    'size': inode.size,
                    'modified': time.ctime(inode.modified_at),
                    'inode': inode.inode_num,
                }
                # Read file content
                try:
                    file_content = self.cognitivefs._read_file_data(inode).decode('utf-8', errors='replace')
                except Exception:
                    pass

        # Try to get extracted text from knowledge graph
        if not file_content and self.knowledge_graph:
            file_record = self.knowledge_graph.get_file(target_path)
            if file_record and file_record.extracted_text:
                file_content = file_record.extracted_text

        if not file_content:
            lines.append("Cannot read file content for summarization.")
            lines.append("")
            if file_info:
                lines.extend([
                    "File Information:",
                    f"  Size: {file_info['size']} bytes",
                    f"  Modified: {file_info['modified']}",
                    "",
                ])
            return "\n".join(lines).encode('utf-8')

        # LLM summary disabled for stability - show file preview instead
        lines.append("(LLM summaries disabled for stability)")
        lines.append("")
        lines.append("## File Preview")
        lines.append(file_content[:1000] if len(file_content) > 1000 else file_content)
        if len(file_content) > 1000:
            lines.append(f"\n... ({len(file_content) - 1000} more characters)")
        lines.append("")

        if file_info:
            lines.extend([
                "---",
                f"Size: {file_info['size']} bytes | Modified: {file_info['modified']}",
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
            return self._make_file_stat(len(content), now, writable=True)

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

        # /.ai/by-topic/<topic> - directory listing files in topic
        if len(parts) == 2:
            topic_name = parts[1]
            topics = self._get_topic_clusters()
            if topic_name in topics:
                return self._make_dir_stat(now)
            return None

        # /.ai/by-topic/<topic>/<filename> - virtual file showing file info
        if len(parts) == 3:
            topic_name = parts[1]
            filename = parts[2]
            topics = self._get_topic_clusters()
            if topic_name in topics:
                for file_path, _ in topics[topic_name]:
                    if file_path.split('/')[-1] == filename:
                        content = self._get_topic_file_content(file_path)
                        return self._make_file_stat(len(content), now)
            return None

        return None

    def _readdir_by_topic(self, target_path: str) -> List[str]:
        """List topics or files in a topic."""
        if not target_path:
            topics = self._get_topic_clusters()
            return list(topics.keys())

        # List files in a specific topic
        parts = target_path.strip('/').split('/')
        if len(parts) == 1:
            topic_name = parts[0]
            topics = self._get_topic_clusters()
            if topic_name in topics:
                # Return just filenames (not full paths)
                return [path.split('/')[-1] for path, _ in topics[topic_name]]

        return []

    def _get_topic_clusters(self) -> Dict[str, List[Tuple[str, float]]]:
        """
        Cluster files into topics based on embedding similarity.

        Returns:
            Dict mapping topic_name -> [(file_path, similarity_score), ...]
        """
        cache_key = "topic_clusters"
        cached = self._get_cached(cache_key)
        if cached:
            import pickle
            return pickle.loads(cached)

        topics = self._compute_topic_clusters()

        # Cache the result
        import pickle
        self._set_cached(cache_key, pickle.dumps(topics))

        return topics

    def _compute_topic_clusters(self) -> Dict[str, List[Tuple[str, float]]]:
        """Compute topic clusters from file embeddings."""
        if not self.knowledge_graph:
            return {"uncategorized": []}

        from .embedder import cosine_similarity

        # Get all files with embeddings
        cursor = self.knowledge_graph.conn.cursor()
        cursor.execute("""
            SELECT f.id, f.path, f.summary, e.vector
            FROM files f
            JOIN embeddings e ON f.embedding_id = e.id
            WHERE e.vector IS NOT NULL
        """)

        files = []
        for row in cursor.fetchall():
            path = row['path']
            # Verify file still exists
            if self.cognitivefs and not self.cognitivefs._resolve_path(path):
                continue
            files.append({
                'id': row['id'],
                'path': path,
                'summary': row['summary'] or "",
                'vector': row['vector']
            })

        if not files:
            return {"uncategorized": []}

        # Simple clustering: group files with similarity > threshold
        SIMILARITY_THRESHOLD = 0.5
        clusters = []  # List of sets of file indices
        assigned = set()

        for i, file_i in enumerate(files):
            if i in assigned:
                continue

            # Start new cluster with this file
            cluster = {i}
            assigned.add(i)

            # Find all similar files
            for j, file_j in enumerate(files):
                if j in assigned:
                    continue

                sim = cosine_similarity(file_i['vector'], file_j['vector'])
                if sim >= SIMILARITY_THRESHOLD:
                    cluster.add(j)
                    assigned.add(j)

            clusters.append(cluster)

        # Name clusters based on common entities or keywords
        topics = {}
        for idx, cluster in enumerate(clusters):
            # Get files in this cluster
            cluster_files = [files[i] for i in cluster]

            # Get topic name from entities
            topic_name = self._get_cluster_topic_name(cluster_files, idx)

            # Add files with their "centrality" score
            topic_files = []
            for file in cluster_files:
                # Calculate average similarity to other files in cluster
                if len(cluster_files) > 1:
                    sims = []
                    for other in cluster_files:
                        if other['id'] != file['id']:
                            sims.append(cosine_similarity(file['vector'], other['vector']))
                    avg_sim = sum(sims) / len(sims) if sims else 1.0
                else:
                    avg_sim = 1.0
                topic_files.append((file['path'], avg_sim))

            # Sort by centrality
            topic_files.sort(key=lambda x: x[1], reverse=True)
            topics[topic_name] = topic_files

        # Add uncategorized for any remaining files
        if not topics:
            topics["uncategorized"] = [(f['path'], 1.0) for f in files]

        return topics

    def _get_cluster_topic_name(self, cluster_files: List[Dict], cluster_idx: int) -> str:
        """Generate a topic name for a cluster based on common entities."""
        if not cluster_files:
            return f"topic_{cluster_idx}"

        # Get entities from files in cluster
        file_ids = [f['id'] for f in cluster_files]

        if not self.knowledge_graph:
            return f"topic_{cluster_idx}"

        cursor = self.knowledge_graph.conn.cursor()
        placeholders = ",".join("?" * len(file_ids))

        # Get most common entities across cluster files
        cursor.execute(f"""
            SELECT e.name, e.entity_type, COUNT(*) as count
            FROM file_entities fe
            JOIN entities e ON fe.entity_id = e.id
            WHERE fe.file_id IN ({placeholders})
            GROUP BY e.id
            ORDER BY count DESC
            LIMIT 3
        """, file_ids)

        entities = cursor.fetchall()

        if entities:
            # Use top entity as topic name
            top_entity = entities[0]['name']
            # Clean up the name for use as directory name
            topic_name = top_entity.lower().replace(' ', '_').replace('/', '-')
            # Remove non-alphanumeric except underscore and hyphen
            topic_name = ''.join(c for c in topic_name if c.isalnum() or c in '_-')
            if topic_name:
                return topic_name[:50]  # Limit length

        # Fall back to path-based name if no entities
        if cluster_files:
            paths = [f['path'] for f in cluster_files]
            # Find common path prefix
            common_prefix = os.path.commonpath([p for p in paths if p])
            if common_prefix and common_prefix != '/':
                dir_name = os.path.basename(common_prefix)
                if dir_name:
                    return dir_name.lower().replace(' ', '_')

        return f"topic_{cluster_idx}"

    def _get_topic_file_content(self, file_path: str) -> bytes:
        """Get content for a file viewed through the topic browser."""
        lines = [
            f"# File: {file_path}",
            ""
        ]

        # Get file info from knowledge graph
        if self.knowledge_graph:
            file_record = self.knowledge_graph.get_file(file_path)
            if file_record:
                lines.append(f"Path: {file_record.path}")
                if file_record.mime_type:
                    lines.append(f"Type: {file_record.mime_type}")
                if file_record.summary:
                    lines.append(f"Summary: {file_record.summary}")
                lines.append("")

                # Get entities
                cursor = self.knowledge_graph.conn.cursor()
                cursor.execute("""
                    SELECT e.name, e.entity_type
                    FROM file_entities fe
                    JOIN entities e ON fe.entity_id = e.id
                    WHERE fe.file_id = ?
                    LIMIT 10
                """, (file_record.id,))

                entities = cursor.fetchall()
                if entities:
                    lines.append("Entities:")
                    for e in entities:
                        lines.append(f"  - {e['name']} ({e['entity_type']})")
                    lines.append("")

        lines.append(f"To read full file: cat {file_path}")
        lines.append("")

        return "\n".join(lines).encode('utf-8')

    def _read_by_topic(self, target_path: str, parts: List[str]) -> bytes:
        """Read content from by-topic virtual paths."""
        if not target_path:
            # Show help for by-topic directory
            return self._get_by_topic_help()

        # /.ai/by-topic/<topic> - show topic overview
        if len(parts) == 2:
            topic_name = parts[1]
            return self._get_topic_overview(topic_name)

        # /.ai/by-topic/<topic>/<filename> - show file info
        if len(parts) == 3:
            topic_name = parts[1]
            filename = parts[2]
            topics = self._get_topic_clusters()
            if topic_name in topics:
                for file_path, _ in topics[topic_name]:
                    if file_path.split('/')[-1] == filename:
                        return self._get_topic_file_content(file_path)

        return b""

    def _get_by_topic_help(self) -> bytes:
        """Return help text for by-topic directory."""
        topics = self._get_topic_clusters()

        lines = [
            "# Files Organized by Topic",
            "",
            "Files are automatically clustered by semantic similarity.",
            "Topics are named based on common entities in each cluster.",
            "",
            f"## Topics ({len(topics)} total)",
            ""
        ]

        for topic_name, files in topics.items():
            lines.append(f"  {topic_name}/ ({len(files)} files)")

        lines.extend([
            "",
            "## Usage",
            "",
            "  ls /.ai/by-topic/              # List all topics",
            "  ls /.ai/by-topic/<topic>/      # List files in topic",
            "  cat /.ai/by-topic/<topic>/file # View file info",
            ""
        ])

        return "\n".join(lines).encode('utf-8')

    def _get_topic_overview(self, topic_name: str) -> bytes:
        """Get overview of a topic cluster."""
        topics = self._get_topic_clusters()

        if topic_name not in topics:
            return f"Topic not found: {topic_name}\n".encode('utf-8')

        files = topics[topic_name]

        lines = [
            f"# Topic: {topic_name}",
            f"# Files: {len(files)}",
            ""
        ]

        # List files with their centrality scores
        lines.append("## Files (sorted by centrality)")
        for file_path, score in files:
            lines.append(f"  [{score:.2f}] {file_path}")

        lines.append("")

        # Get common entities across all files in topic
        if self.knowledge_graph and files:
            file_ids = []
            for file_path, _ in files:
                file_record = self.knowledge_graph.get_file(file_path)
                if file_record:
                    file_ids.append(file_record.id)

            if file_ids:
                cursor = self.knowledge_graph.conn.cursor()
                placeholders = ",".join("?" * len(file_ids))
                cursor.execute(f"""
                    SELECT e.name, e.entity_type, COUNT(*) as count
                    FROM file_entities fe
                    JOIN entities e ON fe.entity_id = e.id
                    WHERE fe.file_id IN ({placeholders})
                    GROUP BY e.id
                    ORDER BY count DESC
                    LIMIT 10
                """, file_ids)

                entities = cursor.fetchall()
                if entities:
                    lines.append("## Common Entities")
                    for e in entities:
                        lines.append(f"  - {e['name']} ({e['entity_type']}) [{e['count']} refs]")
                    lines.append("")

        return "\n".join(lines).encode('utf-8')

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

        # Static query endpoints
        if len(parts) == 2:
            query_type = parts[1]
            if query_type in ("entities", "relationships", "stats", "connections", "context", "query"):
                if query_type in ("connections", "context", "query"):
                    # These are directories with subpaths
                    return self._make_dir_stat(now)
                content = self._get_graph_content(query_type)
                return self._make_file_stat(len(content), now)

        # /.ai/graph/connections/<entity1>/<entity2>
        if len(parts) >= 3 and parts[1] == "connections":
            return self._make_file_stat(4096, now)

        # /.ai/graph/context/<entity_name>
        if len(parts) >= 3 and parts[1] == "context":
            return self._make_file_stat(4096, now)

        # /.ai/graph/query/<question>
        if len(parts) >= 3 and parts[1] == "query":
            return self._make_file_stat(4096, now)

        return None

    def _readdir_graph(self, target_path: str) -> List[str]:
        """List graph query endpoints (BUG-006 fix)."""
        if not target_path:
            return ["entities", "relationships", "stats", "connections", "context", "query", "_help.txt"]

        parts = target_path.strip('/').split('/')
        if len(parts) == 1:
            subdir = parts[0]
            if subdir == "entities":
                # List entity types for browsing
                from .knowledge_graph import EntityType
                return ["page", "_help.txt"] + [et.value for et in EntityType]
            elif subdir == "connections":
                return ["_help.txt"]
            elif subdir == "context":
                return ["_help.txt"]
            elif subdir == "query":
                return ["_help.txt"]

        return []

    def _read_graph(self, target_path: str, parts: List[str]) -> bytes:
        """Read graph query results."""
        if len(parts) == 2:
            query_type = parts[1]
            if query_type == "_help.txt":
                return self._get_graph_help()
            return self._get_graph_content(query_type)

        # /.ai/graph/entities/page/<N> - paginated entity list
        if len(parts) >= 4 and parts[1] == "entities" and parts[2] == "page":
            try:
                page = int(parts[3])
                return self._get_graph_content("entities", page=page)
            except ValueError:
                return b"Invalid page number. Use: cat /.ai/graph/entities/page/1\n"

        # /.ai/graph/connections/<entity1>/<entity2>
        if len(parts) >= 3 and parts[1] == "connections":
            if parts[2] == "_help.txt":
                return self._get_connections_help()
            if len(parts) >= 4:
                entity1 = parts[2].replace("_", " ")
                entity2 = parts[3].replace("_", " ")
                return self._find_entity_connections(entity1, entity2)
            # Just entity1 - list its connections
            entity1 = parts[2].replace("_", " ")
            return self._get_entity_connections(entity1)

        # /.ai/graph/context/<entity_name>
        if len(parts) >= 3 and parts[1] == "context":
            if parts[2] == "_help.txt":
                return self._get_context_help()
            entity_name = "/".join(parts[2:]).replace("_", " ")
            return self._get_entity_full_context(entity_name)

        # /.ai/graph/query/<question>
        if len(parts) >= 3 and parts[1] == "query":
            if parts[2] == "_help.txt":
                return self._get_graph_query_help()
            question = "/".join(parts[2:]).replace("_", " ").replace("+", " ")
            return self._execute_graph_query(question)

        return b""

    def _get_graph_content(self, query_type: str, page: int = 1) -> bytes:
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
            ITEMS_PER_PAGE = 50
            lines = ["# Entities in Knowledge Graph", ""]

            # Get all entities grouped by type
            from .knowledge_graph import EntityType
            all_entities = []
            for et in EntityType:
                entities = self.knowledge_graph.get_entities_by_type(et, limit=500)
                for e in entities:
                    all_entities.append((et, e))

            total_entities = len(all_entities)
            total_pages = max(1, (total_entities + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

            # Validate page number
            if page < 1:
                page = 1
            if page > total_pages:
                page = total_pages

            # Calculate slice
            start_idx = (page - 1) * ITEMS_PER_PAGE
            end_idx = start_idx + ITEMS_PER_PAGE
            page_entities = all_entities[start_idx:end_idx]

            if not page_entities:
                lines.append("No entities indexed yet.")
            else:
                lines.append(f"Page {page} of {total_pages} ({total_entities} total entities)")
                lines.append("")

                # Group page entities by type for display
                current_type = None
                for et, e in page_entities:
                    if et != current_type:
                        if current_type is not None:
                            lines.append("")
                        lines.append(f"## {et.value.title()}")
                        current_type = et
                    lines.append(f"  - {e.name} (refs: {e.source_count})")

                # Navigation footer
                lines.append("")
                lines.append("---")
                if page > 1:
                    lines.append(f"Previous: cat /.ai/graph/entities/page/{page - 1}")
                if page < total_pages:
                    lines.append(f"Next: cat /.ai/graph/entities/page/{page + 1}")

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

    def _get_graph_help(self) -> bytes:
        """Return help for the knowledge graph interface."""
        return b"""# Knowledge Graph Interface

## Available Endpoints

### Static Views
  cat /.ai/graph/stats         - Graph statistics (JSON)
  cat /.ai/graph/entities      - List all entities by type
  cat /.ai/graph/relationships - Relationship summary

### Multi-Hop Queries
  cat /.ai/graph/connections/<entity1>/<entity2>  - Find path between entities
  cat /.ai/graph/context/<entity>                 - Full context for entity
  cat /.ai/graph/query/<question>                 - Natural language query

## Examples

  cat /.ai/graph/connections/machine_learning/neural_networks
  cat /.ai/graph/context/John_Smith
  cat /.ai/graph/query/what_concepts_are_related_to_AI

## How It Works

The knowledge graph stores:
- Entities (people, places, concepts, etc.) extracted from files
- Relationships (co-occurrence, similarity, references)
- Embeddings for semantic search

Multi-hop queries traverse these relationships to find connections.
"""

    def _get_connections_help(self) -> bytes:
        """Return help for entity connections."""
        return b"""# Find Connections Between Entities

## Usage

Find path between two entities:
  cat /.ai/graph/connections/<entity1>/<entity2>

Get all connections for one entity:
  cat /.ai/graph/connections/<entity>

## Examples

  cat /.ai/graph/connections/machine_learning/neural_networks
  cat /.ai/graph/connections/John_Smith/Project_Alpha
  cat /.ai/graph/connections/Python

## Notes

- Use underscores for spaces in entity names
- Maximum 3 hops by default
- Returns all paths found between entities
"""

    def _get_context_help(self) -> bytes:
        """Return help for entity context."""
        return b"""# Get Full Context for an Entity

## Usage

  cat /.ai/graph/context/<entity_name>

## Returns

- Entity details (type, description)
- Related entities (2 hops)
- Files mentioning this entity
- Relationship types

## Examples

  cat /.ai/graph/context/machine_learning
  cat /.ai/graph/context/John_Smith
  cat /.ai/graph/context/Project_Alpha
"""

    def _get_graph_query_help(self) -> bytes:
        """Return help for graph queries."""
        return b"""# Natural Language Graph Query

## Usage

  cat /.ai/graph/query/<your_question>

## Examples

  cat /.ai/graph/query/what_concepts_are_related_to_machine_learning
  cat /.ai/graph/query/how_is_John_connected_to_Project_Alpha
  cat /.ai/graph/query/what_files_mention_neural_networks

## How It Works

1. Extracts entities from your question
2. Traverses the knowledge graph
3. Collects relevant context
4. Returns structured answer with evidence
"""

    def _find_entity_connections(self, entity1: str, entity2: str) -> bytes:
        """Find paths between two entities in the knowledge graph."""
        if not self.knowledge_graph:
            return b"Knowledge graph not initialized.\n"

        try:
            from .relationship_detector import MultiHopQueryEngine

            engine = MultiHopQueryEngine(self.knowledge_graph)
            paths = engine.find_connections(entity1, entity2, max_hops=3)

            lines = [
                f"# Connections: {entity1} -> {entity2}",
                ""
            ]

            if not paths:
                lines.append(f"No path found between '{entity1}' and '{entity2}'")
                lines.append("")
                lines.append("Possible reasons:")
                lines.append("  - Entities not in knowledge graph")
                lines.append("  - No connecting relationships within 3 hops")
                lines.append("")
                lines.append("Try:")
                lines.append(f"  cat /.ai/graph/context/{entity1.replace(' ', '_')}")
            else:
                lines.append(f"Found {len(paths)} path(s):")
                lines.append("")

                for i, path in enumerate(paths[:5], 1):
                    lines.append(f"## Path {i} ({len(path)-1} hops)")
                    path_str = " -> ".join(f"{e['name']} ({e['type']})" for e in path)
                    lines.append(f"  {path_str}")
                    lines.append("")

            return "\n".join(lines).encode('utf-8')

        except Exception as e:
            return f"Error finding connections: {e}\n".encode('utf-8')

    def _get_entity_connections(self, entity_name: str) -> bytes:
        """Get all connections for a single entity."""
        if not self.knowledge_graph:
            return b"Knowledge graph not initialized.\n"

        try:
            from .relationship_detector import MultiHopQueryEngine

            engine = MultiHopQueryEngine(self.knowledge_graph)
            context = engine.get_entity_context(entity_name, depth=1)

            if 'error' in context:
                return f"{context['error']}\n".encode('utf-8')

            entity = context['entity']
            related = context.get('related_entities', [])
            relationships = context.get('relationships', [])

            lines = [
                f"# Connections for: {entity['name']}",
                f"Type: {entity['type']}",
                f"Referenced in {entity['source_count']} files",
                ""
            ]

            if related:
                lines.append(f"## Related Entities ({len(related)})")
                for e in related[:20]:
                    lines.append(f"  - {e['name']} ({e['type']})")
                lines.append("")

            if relationships:
                lines.append(f"## Relationships ({len(relationships)})")
                for r in relationships[:20]:
                    rel_type = r['type']
                    target = self.knowledge_graph.get_entity_by_id(r['target_id'])
                    target_name = target.name if target else f"id:{r['target_id']}"
                    lines.append(f"  - {rel_type} -> {target_name}")
                lines.append("")

            return "\n".join(lines).encode('utf-8')

        except Exception as e:
            return f"Error getting connections: {e}\n".encode('utf-8')

    def _get_entity_full_context(self, entity_name: str) -> bytes:
        """Get full context for an entity including related entities and files."""
        if not self.knowledge_graph:
            return b"Knowledge graph not initialized.\n"

        try:
            from .relationship_detector import MultiHopQueryEngine

            engine = MultiHopQueryEngine(self.knowledge_graph)

            # Normalize entity name: underscores to spaces, lowercase for matching
            normalized_name = entity_name.lower().strip()

            context = engine.get_entity_context(entity_name, depth=2)

            if 'error' in context:
                # Entity not found - try fuzzy search and suggest alternatives
                return self._suggest_entity_alternatives(entity_name)

            entity = context['entity']
            related = context.get('related_entities', [])
            files = context.get('files', [])
            relationships = context.get('relationships', [])

            lines = [
                f"# Entity: {entity['name']}",
                f"Type: {entity['type']}",
                f"References: {entity['source_count']}",
                ""
            ]

            if files:
                lines.append(f"## Files ({len(files)})")
                for f in files:
                    lines.append(f"  - {f['path']}")
                    if f.get('summary'):
                        lines.append(f"    {f['summary'][:100]}...")
                lines.append("")

            if related:
                lines.append(f"## Related Entities ({len(related)})")
                # Group by type
                by_type = {}
                for e in related:
                    etype = e['type']
                    if etype not in by_type:
                        by_type[etype] = []
                    by_type[etype].append(e['name'])

                for etype, names in by_type.items():
                    lines.append(f"  {etype}:")
                    for name in names[:10]:
                        lines.append(f"    - {name}")
                    if len(names) > 10:
                        lines.append(f"    ... and {len(names)-10} more")
                lines.append("")

            if relationships:
                lines.append(f"## Direct Relationships ({len(relationships)})")
                for r in relationships[:10]:
                    target = self.knowledge_graph.get_entity_by_id(r['target_id'])
                    target_name = target.name if target else f"id:{r['target_id']}"
                    lines.append(f"  - {r['type']} -> {target_name} (weight: {r['weight']:.2f})")
                lines.append("")

            return "\n".join(lines).encode('utf-8')

        except Exception as e:
            return f"Error getting context: {e}\n".encode('utf-8')

    def _suggest_entity_alternatives(self, entity_name: str) -> bytes:
        """
        Suggest alternative entities when the requested one is not found.

        Uses FTS5 search to find similar entities and provides helpful suggestions.
        """
        lines = [
            f"Entity '{entity_name}' not found.",
            ""
        ]

        try:
            # Try FTS5 search for similar entities
            suggestions = self.knowledge_graph.search_entities(entity_name, limit=5)

            if suggestions:
                lines.append("Did you mean:")
                for entity in suggestions:
                    # Format: name (type, N references)
                    lines.append(f"  - {entity.name} ({entity.entity_type.value}, {entity.source_count} refs)")
                lines.append("")
                lines.append("Try:")
                # Suggest the first match with underscores for spaces
                first_suggestion = suggestions[0].name.replace(" ", "_")
                lines.append(f"  cat /.ai/graph/context/{first_suggestion}")
            else:
                # No FTS matches - try listing some entities
                lines.append("No similar entities found.")
                lines.append("")
                lines.append("To see available entities:")
                lines.append("  cat /.ai/graph/entities")
                lines.append("")
                lines.append("Or search for entities:")
                lines.append("  cat /.ai/search/<keyword>")

        except Exception as e:
            lines.append(f"Error searching for alternatives: {e}")

        return "\n".join(lines).encode('utf-8')

    def _execute_graph_query(self, question: str) -> bytes:
        """Execute a natural language query against the knowledge graph."""
        if not self.knowledge_graph:
            return b"Knowledge graph not initialized.\n"

        try:
            from .relationship_detector import MultiHopQueryEngine

            engine = MultiHopQueryEngine(self.knowledge_graph)
            result = engine.query_graph(question)

            lines = [
                f"# Graph Query: {question}",
                ""
            ]

            lines.append("## Answer")
            lines.append(result.get('answer', 'No answer found.'))
            lines.append("")

            entities = result.get('entities', [])
            if entities:
                lines.append("## Entities Found")
                for e in entities:
                    lines.append(f"  - {e['name']} ({e['type']})")
                lines.append("")

            related = result.get('related', [])
            if related:
                lines.append("## Related Entities")
                for e in related[:10]:
                    lines.append(f"  - {e['name']} ({e['type']})")
                lines.append("")

            evidence = result.get('evidence', [])
            if evidence:
                lines.append("## Evidence (from files)")
                for ev in evidence[:3]:
                    lines.append(f"  {ev['file']}:")
                    if ev.get('text'):
                        lines.append(f"    {ev['text'][:200]}...")
                    lines.append("")

            return "\n".join(lines).encode('utf-8')

        except Exception as e:
            return f"Error executing query: {e}\n".encode('utf-8')

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

        # Handle help file
        stripped = target_path.lstrip("/")
        if stripped == "_help.txt":
            return self._get_search_help()

        # Convert path to search query
        query = stripped.replace("_", " ").replace("-", " ").replace("+", " ")
        return self._execute_search(query)

    def _get_search_help(self) -> bytes:
        """Return help for search."""
        return b"""# Full-Text Search with Entities

## Usage

Search for terms (use _ or + for spaces):
    cat /.ai/search/machine_learning
    cat /.ai/search/meeting+notes+project

## Returns

- Matching entities (people, organizations, concepts)
- Matching files with relevance scores
- Content snippets showing where matches occur

## Example

    cat /.ai/search/neural_networks

Output:
    ## Entities (3)
      - Neural Networks (concept, 12 refs)
      - Deep Learning (concept, 8 refs)

    ## Files (2)
      === /ai_research.txt (relevance: 2.5) ===
        ...Machine learning and NEURAL NETWORKS are transforming...
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

        # Also search for matching entities
        entity_results = self._search_entities(query, cursor)

        if not results and not entity_results:
            return f"No results found for: {query}\n".encode('utf-8')

        # Format results with snippets
        lines = [
            f"# Search results for: {query}",
            ""
        ]

        # Show matching entities first
        if entity_results:
            lines.append(f"## Entities ({len(entity_results)})")
            for entity in entity_results:
                name = entity['name']
                etype = entity['type']
                refs = entity['ref_count']
                lines.append(f"  - {name} ({etype}, {refs} refs)")
            lines.append("")

        # Show matching files
        if results:
            lines.append(f"## Files ({len(results)})")
            for row in results:
                path = row['path']
                text = row['extracted_text'] or ""
                summary = row['summary'] or ""
                score = abs(row['score']) if row['score'] else 0

                lines.append(f"  ═══ {path} (relevance: {score:.1f}) ═══")

                # Find and show snippets containing the query terms
                snippets = self._extract_snippets(text, query, max_snippets=3)
                if snippets:
                    for snippet in snippets:
                        lines.append(f"    ...{snippet}...")
                elif summary:
                    lines.append(f"    Summary: {summary[:200]}")
                elif text:
                    lines.append(f"    {text[:200]}...")

                lines.append("")

        return "\n".join(lines).encode('utf-8')

    def _search_entities(self, query: str, cursor) -> List[Dict]:
        """Search for entities matching the query."""
        # Search entity names that contain the query
        like_pattern = f"%{query}%"
        try:
            cursor.execute("""
                SELECT e.name, e.type, COUNT(fe.file_id) as ref_count
                FROM entities e
                LEFT JOIN file_entities fe ON e.id = fe.entity_id
                WHERE e.name LIKE ?
                GROUP BY e.id
                ORDER BY ref_count DESC
                LIMIT 10
            """, (like_pattern,))
            return [{'name': row['name'], 'type': row['type'], 'ref_count': row['ref_count']}
                    for row in cursor.fetchall()]
        except Exception:
            return []

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
        # target_path already starts with / from parse_ai_path
        if self.cognitivefs:
            file_path = target_path if target_path.startswith("/") else "/" + target_path
            inode = self.cognitivefs._resolve_path(file_path)
            if inode:
                return self._find_similar_to_file(file_path)

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

    # ==================== Entities (file entity view) operations ====================

    def _getattr_entities(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for entities paths (BUG-005 fix)."""
        now = int(time.time())

        # /.ai/entities/ - directory listing
        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files and other editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        # /.ai/entities/<type>/ - entity type directory
        path_parts = target_path.strip('/').split('/')
        if len(path_parts) == 1:
            from .knowledge_graph import EntityType
            try:
                EntityType(path_parts[0])
                return self._make_dir_stat(now)
            except ValueError:
                pass  # Not an entity type, might be a file path

        # /.ai/entities/<type>/<entity_name> or /.ai/entities/<filepath>
        return self._make_file_stat(4096, now)

    def _readdir_entities(self, target_path: str) -> List[str]:
        """Read directory for entities view (BUG-005 fix)."""
        if not target_path:
            # List entity types + help
            from .knowledge_graph import EntityType
            return ["_help.txt"] + [et.value for et in EntityType]

        # List entities of a given type
        parts = target_path.strip('/').split('/')
        if len(parts) == 1 and self.knowledge_graph:
            try:
                from .knowledge_graph import EntityType
                entity_type = EntityType(parts[0])
                entities = self.knowledge_graph.get_entities_by_type(entity_type, limit=100)
                return [e.name.replace(' ', '_').replace('/', '-') for e in entities]
            except ValueError:
                pass  # Invalid entity type

        return []

    def _read_entities(self, target_path: str, parts: List[str]) -> bytes:
        """
        Show entities extracted from a specific file.

        Usage:
            cat /.ai/entities/_help.txt              - Show help
            cat /.ai/entities/path/to/file.md        - Show entities from file
        """
        if not target_path:
            return b""

        if target_path == "_help.txt":
            return self._get_entities_help()

        return self._get_file_entities(target_path)

    def _get_entities_help(self) -> bytes:
        """Return help text for file entities view."""
        help_text = """# File Entity View

## Usage

Show entities extracted from a specific file:
    cat /.ai/entities/path/to/file.md
    cat /.ai/entities/profiles/geekyinventor/README.md

## What it shows

- Person entities (names mentioned in the file)
- Organization entities (companies, groups)
- Concept entities (technical terms, topics)
- Other entity types (dates, locations, etc.)

## How it works

1. When files are indexed, entities are extracted using NLP
2. Each entity has a confidence score
3. Context shows where the entity was found in the file

## Related commands

- cat /.ai/graph/entities       - List all entities
- cat /.ai/graph/context/<name> - Full context for an entity
- cat /.ai/search/<query>       - Search for entities/files
"""
        return help_text.encode('utf-8')

    def _get_file_entities(self, file_path: str) -> bytes:
        """Get entities extracted from a specific file."""
        if not self.knowledge_graph:
            return b"Knowledge graph not initialized.\n"

        # Ensure file_path starts with /
        if not file_path.startswith("/"):
            file_path = "/" + file_path

        # Get file record
        file_record = self.knowledge_graph.get_file(file_path)
        if not file_record:
            return f"File not indexed: {file_path}\n\nTo index files, they must be written through CognitiveFS.\n".encode('utf-8')

        # Get entities for this file
        file_entities = self.knowledge_graph.get_file_entities(file_record.id)

        if not file_entities:
            return f"# Entities in {file_path}\n\nNo entities extracted from this file.\n".encode('utf-8')

        lines = [
            f"# Entities in {file_path}",
            f"Found {len(file_entities)} entities",
            ""
        ]

        # Group entities by type
        by_type = {}
        for entity, rel_type, confidence in file_entities:
            etype = entity.entity_type.value
            if etype not in by_type:
                by_type[etype] = []
            by_type[etype].append((entity, rel_type, confidence))

        # Display by type
        for etype, entities in sorted(by_type.items()):
            lines.append(f"## {etype.title()} ({len(entities)})")
            for entity, rel_type, confidence in sorted(entities, key=lambda x: x[2], reverse=True):
                lines.append(f"  - {entity.name} (confidence: {confidence:.2f})")
                if entity.description:
                    desc = entity.description[:80] + "..." if len(entity.description) > 80 else entity.description
                    lines.append(f"    {desc}")
            lines.append("")

        return "\n".join(lines).encode('utf-8')

    # ==================== Versions (git history) operations ====================

    def _getattr_versions(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for version paths."""
        now = int(time.time())

        # /.ai/versions/ - directory listing
        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files and editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        # Check for special files: _help.txt, commits, etc.
        stripped = target_path.strip('/')
        if stripped in ('_help.txt', 'commits', 'log', 'stats'):
            content = self._read_versions(target_path, parts)
            return self._make_file_stat(len(content), now)

        # /.ai/versions/<commit_hash> - commit details
        if len(parts) == 2 and len(parts[1]) >= 7:
            # Looks like a commit hash - check if it's a directory or file
            return self._make_dir_stat(now)

        # /.ai/versions/file/<path> - file version history
        if len(parts) >= 2 and parts[1] == 'file':
            if len(parts) == 2:
                return self._make_dir_stat(now)
            # Return file stat for version history
            content = self._get_file_version_history('/' + '/'.join(parts[2:]))
            return self._make_file_stat(len(content), now)

        # /.ai/versions/<commit_hash>/<path> - file at specific version
        if len(parts) >= 3 and len(parts[1]) >= 7:
            commit_hash = parts[1]
            file_path = '/' + '/'.join(parts[2:])
            content = self._get_file_at_version(file_path, commit_hash)
            if content is not None:
                return self._make_file_stat(len(content), now)

        return self._make_file_stat(4096, now)

    def _readdir_versions(self, target_path: str, parts: List[str]) -> List[str]:
        """Read directory for versions paths."""
        if not target_path:
            # Root of versions - show help, commits file, and recent commits
            entries = ['_help.txt', 'commits', 'log', 'stats', 'file']

            # Add recent commit hashes as directories
            vc = self._get_version_control()
            if vc and vc.enabled:
                commits = vc.get_all_commits(limit=10)
                for commit in commits:
                    short_hash = commit['hash'][:8]
                    entries.append(short_hash)

            return entries

        stripped = target_path.strip('/')
        path_parts = stripped.split('/')

        # /.ai/versions/file/ - mirror real filesystem
        if path_parts[0] == 'file':
            if len(path_parts) == 1:
                return self._readdir_mirror('')
            else:
                return self._readdir_mirror('/' + '/'.join(path_parts[1:]))

        # /.ai/versions/<commit_hash>/ - list files changed in commit
        if len(path_parts) == 1 and len(path_parts[0]) >= 7:
            commit_hash = path_parts[0]
            vc = self._get_version_control()
            if vc and vc.enabled:
                files = vc.get_commit_files(commit_hash)
                # Use just the filename for directory listing (paths with / handled as subdirs)
                return ['_info.txt', '_diff.txt'] + [f['path'].lstrip('/') for f in files]

        return []

    def _read_versions(self, target_path: str, parts: List[str]) -> bytes:
        """Read version control content."""
        if not target_path:
            return self._get_versions_help()

        stripped = target_path.strip('/')

        if stripped == '_help.txt':
            return self._get_versions_help()

        if stripped == 'commits' or stripped == 'log':
            return self._get_commits_list()

        if stripped == 'stats':
            return self._get_version_stats()

        path_parts = stripped.split('/')

        # /.ai/versions/file/<path> - file version history
        if path_parts[0] == 'file' and len(path_parts) > 1:
            file_path = '/' + '/'.join(path_parts[1:])
            return self._get_file_version_history(file_path)

        # /.ai/versions/<commit_hash>/_info.txt - commit info
        if len(path_parts) >= 2 and path_parts[1] == '_info.txt':
            commit_hash = path_parts[0]
            return self._get_commit_info(commit_hash)

        # /.ai/versions/<commit_hash>/_diff.txt - commit diff
        if len(path_parts) >= 2 and path_parts[1] == '_diff.txt':
            commit_hash = path_parts[0]
            return self._get_commit_diff(commit_hash)

        # /.ai/versions/<commit_hash>/<filepath> - file at version
        if len(path_parts) >= 2 and len(path_parts[0]) >= 7:
            commit_hash = path_parts[0]
            # Keep the path as-is, just join with /
            file_path = '/' + '/'.join(path_parts[1:])
            content = self._get_file_at_version(file_path, commit_hash)
            if content is not None:
                return content
            return f"File not found at version {commit_hash}: {file_path}\n".encode('utf-8')

        return b""

    def _get_version_control(self):
        """Get version control instance from cognitivefs."""
        if self.cognitivefs and hasattr(self.cognitivefs, 'version_control'):
            return self.cognitivefs.version_control
        return None

    def _get_versions_help(self) -> bytes:
        """Return help for versions interface."""
        vc = self._get_version_control()
        vc_status = "enabled" if (vc and vc.enabled) else "disabled"

        return f"""# Version Control Interface

## Status: {vc_status}

All files written to CognitiveFS are automatically versioned using git.

## Usage

### View commit history
    cat /.ai/versions/commits         # List recent commits
    cat /.ai/versions/log             # Same as commits
    cat /.ai/versions/stats           # Version control statistics

### Browse commits
    ls /.ai/versions/<commit_hash>/   # List files changed in commit
    cat /.ai/versions/<hash>/_info.txt    # Commit details
    cat /.ai/versions/<hash>/_diff.txt    # Full diff

### View file history
    cat /.ai/versions/file/path/to/file.txt   # Version history for file

### View file at specific version
    cat /.ai/versions/<hash>/path/to/file.txt # File content at version

## Examples

    cat /.ai/versions/commits
    cat /.ai/versions/abc1234/_info.txt
    cat /.ai/versions/file/docs/notes.md

## Notes

- Version control is transparent - no manual commits needed
- Large files (>10MB) use Git LFS if available
- Remote sync available via git commands in the .vcs directory
""".encode('utf-8')

    def _get_commits_list(self) -> bytes:
        """Get list of recent commits."""
        vc = self._get_version_control()
        if not vc or not vc.enabled:
            return b"Version control not enabled.\n"

        commits = vc.get_all_commits(limit=50)

        if not commits:
            return b"No commits yet.\n"

        lines = [
            "# Commit History",
            f"# Total: {len(commits)} commits shown",
            ""
        ]

        for commit in commits:
            ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(commit['timestamp']))
            short_hash = commit['hash'][:8]
            message = commit['message'][:60]
            lines.append(f"{short_hash}  {ts}  {message}")

        lines.extend([
            "",
            "---",
            "View commit: cat /.ai/versions/<hash>/_info.txt",
            "View diff: cat /.ai/versions/<hash>/_diff.txt"
        ])

        return "\n".join(lines).encode('utf-8')

    def _get_version_stats(self) -> bytes:
        """Get version control statistics."""
        vc = self._get_version_control()
        if not vc or not vc.enabled:
            return json.dumps({'enabled': False}, indent=2).encode('utf-8')

        stats = vc.get_stats()
        return json.dumps(stats, indent=2).encode('utf-8')

    def _get_commit_info(self, commit_hash: str) -> bytes:
        """Get detailed info about a commit."""
        vc = self._get_version_control()
        if not vc or not vc.enabled:
            return b"Version control not enabled.\n"

        # Get commit details
        commits = vc.get_all_commits(limit=100)
        commit_info = None
        for c in commits:
            if c['hash'].startswith(commit_hash):
                commit_info = c
                break

        if not commit_info:
            return f"Commit not found: {commit_hash}\n".encode('utf-8')

        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(commit_info['timestamp']))

        # Get files changed
        files = vc.get_commit_files(commit_info['hash'])

        lines = [
            f"# Commit: {commit_info['hash']}",
            "",
            f"Author:  {commit_info['author']}",
            f"Date:    {ts}",
            f"Message: {commit_info['message']}",
            "",
            f"## Files Changed ({len(files)})",
            ""
        ]

        for f in files:
            status_icon = {'added': '+', 'modified': '~', 'deleted': '-'}.get(f['status'], '?')
            lines.append(f"  {status_icon} {f['path']}")

        lines.extend([
            "",
            f"View diff: cat /.ai/versions/{commit_hash}/_diff.txt"
        ])

        return "\n".join(lines).encode('utf-8')

    def _get_commit_diff(self, commit_hash: str) -> bytes:
        """Get diff for a commit."""
        vc = self._get_version_control()
        if not vc or not vc.enabled:
            return b"Version control not enabled.\n"

        diff = vc.get_diff(commit_hash)
        if not diff:
            return f"No diff available for commit: {commit_hash}\n".encode('utf-8')

        return diff.encode('utf-8')

    def _get_file_version_history(self, file_path: str) -> bytes:
        """Get version history for a specific file."""
        vc = self._get_version_control()
        if not vc or not vc.enabled:
            return b"Version control not enabled.\n"

        commits = vc.get_file_history(file_path, limit=30)

        if not commits:
            return f"No version history for: {file_path}\n".encode('utf-8')

        lines = [
            f"# Version History: {file_path}",
            f"# {len(commits)} versions",
            ""
        ]

        for i, commit in enumerate(commits):
            ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(commit['timestamp']))
            short_hash = commit['hash'][:8]
            message = commit['message'][:50]
            version_label = "current" if i == 0 else f"v{len(commits) - i}"
            lines.append(f"[{version_label}] {short_hash}  {ts}  {message}")

        lines.extend([
            "",
            "---",
            f"View specific version: cat /.ai/versions/<hash>{file_path}"
        ])

        return "\n".join(lines).encode('utf-8')

    def _get_file_at_version(self, file_path: str, commit_hash: str) -> Optional[bytes]:
        """Get file content at a specific version."""
        vc = self._get_version_control()
        if not vc or not vc.enabled:
            return None

        return vc.get_file_at_version(file_path, commit_hash)
