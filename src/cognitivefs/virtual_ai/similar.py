"""
Similar handler for /.ai/similar/ (embedding-based similarity search)
"""

import time
from typing import Optional, Dict, List
from .base import BaseHandler


class SimilarHandler(BaseHandler):
    """Handles /.ai/similar/ virtual paths for embedding similarity."""

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for similar paths."""
        now = int(time.time())

        # /.ai/similar/ - directory listing
        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files and editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        # /.ai/similar/<query> - placeholder size
        return self._make_file_stat(4096, now)

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """List files in /.ai/similar/."""
        if not target_path:
            return ["_help.txt"]
        return []

    def read(self, target_path: str, parts: List[str]) -> bytes:
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

1. Files are embedded using sentence-transformers (BAAI/bge-base-en-v1.5)
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
        from ..embedder import cosine_similarity

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
