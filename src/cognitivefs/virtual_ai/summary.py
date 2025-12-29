"""
Summary handler for /.ai/summary/ (file summaries)
"""

import time
from typing import Optional, Dict, List
from .base import BaseHandler


class SummaryHandler(BaseHandler):
    """Handles /.ai/summary/ virtual paths for file summaries."""

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for summary paths."""
        now = int(time.time())

        if not target_path:
            # /.ai/summary/ directory - mirrors root
            return self._make_dir_stat(now)

        # Reject temp files and editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        # Check if the target file exists in real filesystem
        if self.cognitivefs:
            file_path = target_path if target_path.startswith("/") else "/" + target_path
            real_inode = self.cognitivefs._resolve_path(file_path)
            if real_inode:
                # Return file stat for the summary
                summary = self._generate_summary(file_path)
                return self._make_file_stat(len(summary), now)

        return None

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """Mirror the real filesystem structure for summary."""
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
        """Read AI-generated summary of a file."""
        if not target_path:
            return b"Specify a file path to summarize.\n"

        # Check cache
        cache_key = f"summary:{target_path}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        file_path = target_path if target_path.startswith("/") else "/" + target_path
        summary = self._generate_summary(file_path)
        self._set_cached(cache_key, summary)
        return summary

    def _generate_summary(self, target_path: str) -> bytes:
        """Generate AI summary for a file using LLM."""
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
