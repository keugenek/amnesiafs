"""
Related handler for /.ai/related/ (related files via embeddings and entities)
"""

import time
from typing import Optional, Dict, List, Tuple
from .base import BaseHandler


class RelatedHandler(BaseHandler):
    """Handles /.ai/related/ virtual paths for finding related files."""

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for related paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files and editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        # For related/<path> returns a file listing related files
        if self.cognitivefs:
            file_path = target_path if target_path.startswith("/") else "/" + target_path
            real_inode = self.cognitivefs._resolve_path(file_path)
            if real_inode:
                content = self._get_related_files(file_path)
                return self._make_file_stat(len(content), now)

        return None

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """Mirror the real filesystem structure for related."""
        if not target_path:
            return self._readdir_mirror("")
        return self._readdir_mirror(target_path)

    def _readdir_mirror(self, path: str) -> List[str]:
        """Mirror the real filesystem directory listing."""
        if not self.cognitivefs:
            return []

        real_path = path if path else "/"
        inode = self.cognitivefs._resolve_path(real_path)

        if not inode or inode.inode_type != 2:  # Not a directory
            return []

        entries = self.cognitivefs._read_directory(inode)
        return [e.name for e in entries if e.name not in (".", "..")]

    def read(self, target_path: str, parts: List[str]) -> bytes:
        """Get files related to the target file."""
        if not target_path:
            return b"Specify a file path to find related files.\n"

        file_path = target_path if target_path.startswith("/") else "/" + target_path
        return self._get_related_files(file_path)

    def _get_related_files(self, target_path: str) -> bytes:
        """
        Find files related to the target using multiple signals:
        1. Embedding similarity (semantic relatedness)
        2. Shared entities (knowledge graph connections)
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
                lines.append(f"    shared: {entity_list}")
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
        from ..embedder import cosine_similarity

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
