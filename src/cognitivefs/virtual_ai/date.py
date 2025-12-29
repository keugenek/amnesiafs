"""
Date handler for /.ai/by-date/ (temporal file organization)
"""

import time
from typing import Optional, Dict, List
from datetime import datetime
from .base import BaseHandler
from ..utils import format_timestamp


class DateHandler(BaseHandler):
    """Handles /.ai/by-date/ virtual paths for temporal file organization."""

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for by-date paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files and editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        # Date hierarchy: year/month/day or year/month
        path_parts = target_path.strip('/').split('/')

        # Year directory
        if len(path_parts) == 1 and path_parts[0].isdigit() and len(path_parts[0]) == 4:
            return self._make_dir_stat(now)

        # Year/month directory
        if len(path_parts) == 2 and all(p.isdigit() for p in path_parts):
            return self._make_dir_stat(now)

        # Year/month/day directory
        if len(path_parts) == 3 and all(p.isdigit() for p in path_parts):
            return self._make_dir_stat(now)

        # File within date hierarchy - show file info
        if len(path_parts) >= 4:
            content = self._get_date_file_info(path_parts)
            if content:
                return self._make_file_stat(len(content), now)

        return None

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """List date hierarchy or files."""
        if not target_path:
            # Return years with content
            return self._get_years_with_files()

        path_parts = target_path.strip('/').split('/')

        # List months for a year
        if len(path_parts) == 1 and path_parts[0].isdigit():
            year = path_parts[0]
            return self._get_months_for_year(year)

        # List days for a year/month
        if len(path_parts) == 2 and all(p.isdigit() for p in path_parts):
            year, month = path_parts
            return self._get_days_for_month(year, month)

        # List files for a year/month/day
        if len(path_parts) == 3 and all(p.isdigit() for p in path_parts):
            year, month, day = path_parts
            return self._get_files_for_date(year, month, day)

        return []

    def read(self, target_path: str, parts: List[str]) -> bytes:
        """Read file info or help."""
        if not target_path:
            return self._get_by_date_help()

        path_parts = target_path.strip('/').split('/')

        # File within date hierarchy
        if len(path_parts) >= 4:
            return self._get_date_file_info(path_parts)

        return b""

    def _get_by_date_help(self) -> bytes:
        """Return help text for by-date directory."""
        years = self._get_years_with_files()

        lines = [
            "# Files Organized by Date",
            "",
            "Browse files by their modification date.",
            "",
            f"## Years ({len(years)} total)",
            ""
        ]

        for year in years:
            lines.append(f"  {year}/")

        lines.extend([
            "",
            "## Usage",
            "",
            "  ls /.ai/by-date/              # List years",
            "  ls /.ai/by-date/2024/         # List months in 2024",
            "  ls /.ai/by-date/2024/12/      # List days in Dec 2024",
            "  ls /.ai/by-date/2024/12/25/   # List files from Dec 25, 2024",
            ""
        ])

        return "\n".join(lines).encode('utf-8')

    def _get_years_with_files(self) -> List[str]:
        """Get list of years that have files."""
        if not self.knowledge_graph:
            # Return current year as placeholder
            return [str(datetime.now().year)]

        cursor = self.knowledge_graph.conn.cursor()
        cursor.execute("""
            SELECT DISTINCT strftime('%Y', datetime(modified_at, 'unixepoch')) as year
            FROM files
            WHERE modified_at IS NOT NULL
            ORDER BY year DESC
        """)

        years = [row['year'] for row in cursor.fetchall() if row['year']]
        return years if years else [str(datetime.now().year)]

    def _get_months_for_year(self, year: str) -> List[str]:
        """Get list of months that have files in a given year."""
        if not self.knowledge_graph:
            return []

        cursor = self.knowledge_graph.conn.cursor()
        cursor.execute("""
            SELECT DISTINCT strftime('%m', datetime(modified_at, 'unixepoch')) as month
            FROM files
            WHERE strftime('%Y', datetime(modified_at, 'unixepoch')) = ?
              AND modified_at IS NOT NULL
            ORDER BY month
        """, (year,))

        return [row['month'] for row in cursor.fetchall() if row['month']]

    def _get_days_for_month(self, year: str, month: str) -> List[str]:
        """Get list of days that have files in a given year/month."""
        if not self.knowledge_graph:
            return []

        cursor = self.knowledge_graph.conn.cursor()
        cursor.execute("""
            SELECT DISTINCT strftime('%d', datetime(modified_at, 'unixepoch')) as day
            FROM files
            WHERE strftime('%Y', datetime(modified_at, 'unixepoch')) = ?
              AND strftime('%m', datetime(modified_at, 'unixepoch')) = ?
              AND modified_at IS NOT NULL
            ORDER BY day
        """, (year, month))

        return [row['day'] for row in cursor.fetchall() if row['day']]

    def _get_files_for_date(self, year: str, month: str, day: str) -> List[str]:
        """Get list of files modified on a given date."""
        if not self.knowledge_graph:
            return []

        cursor = self.knowledge_graph.conn.cursor()
        cursor.execute("""
            SELECT path
            FROM files
            WHERE strftime('%Y', datetime(modified_at, 'unixepoch')) = ?
              AND strftime('%m', datetime(modified_at, 'unixepoch')) = ?
              AND strftime('%d', datetime(modified_at, 'unixepoch')) = ?
              AND modified_at IS NOT NULL
            ORDER BY modified_at DESC
        """, (year, month, day))

        # Return just filenames (not full paths) for directory listing
        files = []
        for row in cursor.fetchall():
            path = row['path']
            # Verify file still exists
            if self.cognitivefs and not self.cognitivefs._resolve_path(path):
                continue
            filename = path.split('/')[-1]
            files.append(filename)

        return files

    def _get_date_file_info(self, path_parts: List[str]) -> bytes:
        """Get info about a file in the date hierarchy."""
        if len(path_parts) < 4:
            return b""

        year, month, day = path_parts[0], path_parts[1], path_parts[2]
        filename = '/'.join(path_parts[3:])

        if not self.knowledge_graph:
            return f"File: {filename}\nKnowledge graph not initialized.\n".encode('utf-8')

        # Find the actual file path
        cursor = self.knowledge_graph.conn.cursor()
        cursor.execute("""
            SELECT path, summary, mime_type, modified_at
            FROM files
            WHERE strftime('%Y', datetime(modified_at, 'unixepoch')) = ?
              AND strftime('%m', datetime(modified_at, 'unixepoch')) = ?
              AND strftime('%d', datetime(modified_at, 'unixepoch')) = ?
              AND path LIKE ?
            LIMIT 1
        """, (year, month, day, f'%{filename}'))

        row = cursor.fetchone()
        if not row:
            return f"File not found: {filename}\n".encode('utf-8')

        lines = [
            f"# File: {filename}",
            "",
            f"Full path: {row['path']}",
            f"Type: {row['mime_type'] or 'unknown'}",
            f"Modified: {format_timestamp(row['modified_at'], 'full') if row['modified_at'] else 'unknown'}",
        ]

        if row['summary']:
            lines.extend(["", f"Summary: {row['summary']}"])

        lines.extend([
            "",
            f"To read full file: cat {row['path']}"
        ])

        return "\n".join(lines).encode('utf-8')
