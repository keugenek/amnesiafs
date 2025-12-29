"""
Status handler for /.ai/status/
"""

import json
import time
from typing import Optional, Dict, List
from .base import BaseHandler
from ..utils import format_timestamp


class StatusHandler(BaseHandler):
    """Handles /.ai/status/ virtual paths."""

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for status paths."""
        now = int(time.time())

        # /.ai/status/ itself
        if not target_path or target_path == "/":
            return self._make_dir_stat(now)

        # Status files
        if target_path in ("/index", "/overview", "index", "overview"):
            content = self.read(target_path, parts)
            return self._make_file_stat(len(content), now)

        return None

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """List files in /.ai/status/."""
        return ['index', 'overview']

    def read(self, target_path: str, parts: List[str]) -> bytes:
        """Read status information."""
        if not target_path or target_path == "/" or target_path in ("/overview", "overview"):
            return self._get_status_content()

        if target_path in ("/index", "index"):
            return self._get_index_status()

        return self._get_status_content()

    def _get_status_content(self) -> bytes:
        """Generate status content."""
        status = {
            "filesystem": "CognitiveFS",
            "version": "0.1.0",
            "status": "mounted",
            "timestamp": format_timestamp(time.time(), 'full'),
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

    def _get_index_status(self) -> bytes:
        """Get detailed indexing status."""
        lines = [
            "# Index Status",
            f"Timestamp: {format_timestamp(time.time(), 'full')}",
            ""
        ]

        if not self.knowledge_graph:
            lines.append("Knowledge graph not initialized.")
            return "\n".join(lines).encode('utf-8')

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
            last_indexed_time = format_timestamp(recent[1], 'full') if recent else "N/A"

            # Calculate embedding coverage
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
