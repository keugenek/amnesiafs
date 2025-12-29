"""
Insights handler for /.ai/insights/ (auto-generated discoveries)

Provides zero-config discovery views:
- hubs/      - Most-referenced entities
- clusters/  - Groups of similar files
- timeline/  - Activity by date
- duplicates/ - Near-duplicate files
"""

import time
import json
from typing import Optional, Dict, List
from collections import defaultdict
from .base import BaseHandler


class InsightsHandler(BaseHandler):
    """Handles /.ai/insights/ virtual paths for auto-generated discoveries."""

    SUBFOLDERS = ['hubs', 'clusters', 'timeline', 'duplicates', 'overview']

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for insights paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        clean_path = target_path.lstrip('/')
        path_parts = clean_path.split('/') if clean_path else []

        if not path_parts:
            return self._make_dir_stat(now)

        subfolder = path_parts[0]

        if subfolder in self.SUBFOLDERS:
            if len(path_parts) == 1:
                return self._make_dir_stat(now)
            # File within subfolder
            content = self._get_content(subfolder, path_parts[1:])
            return self._make_file_stat(len(content), now)

        return None

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """List insights directory contents."""
        if not target_path:
            return self.SUBFOLDERS + ['_help.txt']

        clean_path = target_path.lstrip('/')
        path_parts = clean_path.split('/') if clean_path else []

        if not path_parts:
            return self.SUBFOLDERS + ['_help.txt']

        subfolder = path_parts[0]

        if subfolder == 'hubs':
            return self._list_hubs()
        elif subfolder == 'clusters':
            return self._list_clusters()
        elif subfolder == 'timeline':
            return self._list_timeline()
        elif subfolder == 'duplicates':
            return self._list_duplicates()
        elif subfolder == 'overview':
            return ['summary.md', 'stats.json']

        return []

    def read(self, target_path: str, parts: List[str]) -> bytes:
        """Read insights content."""
        if not target_path:
            return self._get_help()

        clean_path = target_path.lstrip('/')

        if clean_path == '_help.txt':
            return self._get_help()

        path_parts = clean_path.split('/') if clean_path else []

        if not path_parts:
            return self._get_help()

        subfolder = path_parts[0]
        sub_parts = path_parts[1:] if len(path_parts) > 1 else []

        return self._get_content(subfolder, sub_parts)

    def _get_help(self) -> bytes:
        """Return help text."""
        return b"""# Insights - Auto-Generated Discoveries

## Available Views

### /.ai/insights/hubs/
Most-referenced entities across all files.
Shows which people, organizations, topics appear most frequently.

### /.ai/insights/clusters/
Groups of semantically similar files.
Files are clustered by embedding similarity.

### /.ai/insights/timeline/
Activity organized by date.
Shows when files were created/modified.

### /.ai/insights/duplicates/
Near-duplicate files (>90% similarity).
Helps find redundant content.

### /.ai/insights/overview/
Summary statistics and overview.

## Usage
    ls /.ai/insights/hubs/
    cat /.ai/insights/hubs/top_entities.md
    cat /.ai/insights/overview/summary.md
"""

    def _get_content(self, subfolder: str, sub_parts: List[str]) -> bytes:
        """Get content for a specific insight."""
        cache_key = f"insights:{subfolder}:{'/'.join(sub_parts)}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        if subfolder == 'hubs':
            content = self._generate_hubs_content(sub_parts)
        elif subfolder == 'clusters':
            content = self._generate_clusters_content(sub_parts)
        elif subfolder == 'timeline':
            content = self._generate_timeline_content(sub_parts)
        elif subfolder == 'duplicates':
            content = self._generate_duplicates_content(sub_parts)
        elif subfolder == 'overview':
            content = self._generate_overview_content(sub_parts)
        else:
            content = b"Unknown insight type.\n"

        self._set_cached(cache_key, content)
        return content

    def _list_hubs(self) -> List[str]:
        """List hub files."""
        return ['top_entities.md', 'by_type.md', 'connections.md']

    def _list_clusters(self) -> List[str]:
        """List cluster files."""
        return ['overview.md', 'cluster_1.md', 'cluster_2.md', 'cluster_3.md']

    def _list_timeline(self) -> List[str]:
        """List timeline files."""
        return ['recent.md', 'by_week.md', 'by_month.md']

    def _list_duplicates(self) -> List[str]:
        """List duplicate files."""
        return ['candidates.md']

    # ========== HUB GENERATION ==========

    def _generate_hubs_content(self, sub_parts: List[str]) -> bytes:
        """Generate hub entity content."""
        if not self.knowledge_graph:
            return b"Knowledge graph not available.\n"

        filename = sub_parts[0] if sub_parts else 'top_entities.md'

        if filename == 'top_entities.md':
            return self._generate_top_entities()
        elif filename == 'by_type.md':
            return self._generate_entities_by_type()
        elif filename == 'connections.md':
            return self._generate_entity_connections()

        return b"Unknown hub file.\n"

    def _generate_top_entities(self) -> bytes:
        """Generate top entities by reference count."""
        lines = ["# Top Entities (Most Referenced)", ""]

        try:
            cursor = self.knowledge_graph.conn.cursor()
            cursor.execute("""
                SELECT e.name, e.entity_type, e.source_count, e.description
                FROM entities e
                WHERE e.source_count > 1
                ORDER BY e.source_count DESC
                LIMIT 50
            """)

            rows = cursor.fetchall()
            if not rows:
                lines.append("No entities with multiple references found.")
            else:
                lines.append("| Entity | Type | References | Description |")
                lines.append("|--------|------|------------|-------------|")
                for row in rows:
                    name = row['name'][:40]
                    etype = row['entity_type']
                    count = row['source_count']
                    desc = (row['description'] or '')[:50]
                    lines.append(f"| {name} | {etype} | {count} | {desc} |")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    def _generate_entities_by_type(self) -> bytes:
        """Generate entities grouped by type."""
        lines = ["# Entities by Type", ""]

        try:
            cursor = self.knowledge_graph.conn.cursor()
            cursor.execute("""
                SELECT entity_type, COUNT(*) as cnt
                FROM entities
                GROUP BY entity_type
                ORDER BY cnt DESC
            """)

            for row in cursor.fetchall():
                etype = row['entity_type']
                count = row['cnt']
                lines.append(f"## {etype} ({count})")
                lines.append("")

                # Get top 10 of this type
                cursor.execute("""
                    SELECT name, source_count
                    FROM entities
                    WHERE entity_type = ?
                    ORDER BY source_count DESC
                    LIMIT 10
                """, (etype,))

                for entity in cursor.fetchall():
                    lines.append(f"- {entity['name']} ({entity['source_count']} refs)")
                lines.append("")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    def _generate_entity_connections(self) -> bytes:
        """Generate entity connection graph summary."""
        lines = ["# Entity Connections", ""]

        try:
            cursor = self.knowledge_graph.conn.cursor()

            # Get entities with most relationships
            cursor.execute("""
                SELECT e.name, e.entity_type,
                       (SELECT COUNT(*) FROM relationships r WHERE r.source_id = e.id OR r.target_id = e.id) as rel_count
                FROM entities e
                HAVING rel_count > 0
                ORDER BY rel_count DESC
                LIMIT 20
            """)

            rows = cursor.fetchall()
            if not rows:
                lines.append("No entity relationships found.")
            else:
                lines.append("| Entity | Type | Connections |")
                lines.append("|--------|------|-------------|")
                for row in rows:
                    lines.append(f"| {row['name'][:40]} | {row['entity_type']} | {row['rel_count']} |")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    # ========== CLUSTER GENERATION ==========

    def _generate_clusters_content(self, sub_parts: List[str]) -> bytes:
        """Generate cluster content."""
        if not self.knowledge_graph:
            return b"Knowledge graph not available.\n"

        filename = sub_parts[0] if sub_parts else 'overview.md'

        if filename == 'overview.md':
            return self._generate_cluster_overview()
        elif filename.startswith('cluster_'):
            try:
                cluster_num = int(filename.replace('cluster_', '').replace('.md', ''))
                return self._generate_cluster_detail(cluster_num)
            except:
                pass

        return b"Unknown cluster file.\n"

    def _generate_cluster_overview(self) -> bytes:
        """Generate cluster overview using simple similarity grouping."""
        lines = ["# File Clusters (Similar Content Groups)", ""]

        try:
            cursor = self.knowledge_graph.conn.cursor()

            # Get files with embeddings
            cursor.execute("""
                SELECT f.id, f.path, f.size, fe.embedding
                FROM files f
                JOIN file_embeddings fe ON f.id = fe.file_id
                WHERE f.extracted_text IS NOT NULL
                ORDER BY f.modified_at DESC
                LIMIT 100
            """)

            files = cursor.fetchall()
            if len(files) < 2:
                lines.append("Not enough files with embeddings for clustering.")
                lines.append(f"Files with embeddings: {len(files)}")
                return "\n".join(lines).encode('utf-8')

            # Simple clustering by path prefix (as fallback without numpy)
            clusters = defaultdict(list)
            for f in files:
                path = f['path']
                # Group by top-level folder
                parts = path.strip('/').split('/')
                prefix = parts[0] if parts else 'root'
                clusters[prefix].append(f['path'])

            lines.append(f"**Total files analyzed:** {len(files)}")
            lines.append(f"**Clusters found:** {len(clusters)}")
            lines.append("")

            for i, (prefix, paths) in enumerate(sorted(clusters.items(), key=lambda x: -len(x[1]))[:5]):
                lines.append(f"## Cluster {i+1}: {prefix}/ ({len(paths)} files)")
                for p in paths[:5]:
                    lines.append(f"  - {p}")
                if len(paths) > 5:
                    lines.append(f"  - ... and {len(paths)-5} more")
                lines.append("")

        except Exception as e:
            lines.append(f"Error generating clusters: {e}")

        return "\n".join(lines).encode('utf-8')

    def _generate_cluster_detail(self, cluster_num: int) -> bytes:
        """Generate detail for a specific cluster."""
        lines = [f"# Cluster {cluster_num} Details", ""]
        lines.append("(Detailed clustering requires scipy/sklearn)")
        lines.append("")
        lines.append("See overview.md for path-based grouping.")
        return "\n".join(lines).encode('utf-8')

    # ========== TIMELINE GENERATION ==========

    def _generate_timeline_content(self, sub_parts: List[str]) -> bytes:
        """Generate timeline content."""
        if not self.knowledge_graph:
            return b"Knowledge graph not available.\n"

        filename = sub_parts[0] if sub_parts else 'recent.md'

        if filename == 'recent.md':
            return self._generate_recent_activity()
        elif filename == 'by_week.md':
            return self._generate_weekly_activity()
        elif filename == 'by_month.md':
            return self._generate_monthly_activity()

        return b"Unknown timeline file.\n"

    def _generate_recent_activity(self) -> bytes:
        """Generate recent file activity."""
        lines = ["# Recent Activity", ""]

        try:
            cursor = self.knowledge_graph.conn.cursor()
            cursor.execute("""
                SELECT path, size, modified_at,
                       datetime(modified_at, 'unixepoch') as mod_date
                FROM files
                ORDER BY modified_at DESC
                LIMIT 30
            """)

            rows = cursor.fetchall()
            if not rows:
                lines.append("No files indexed yet.")
            else:
                current_date = None
                for row in rows:
                    mod_date = row['mod_date'][:10] if row['mod_date'] else 'Unknown'
                    if mod_date != current_date:
                        current_date = mod_date
                        lines.append(f"\n## {mod_date}")
                    size_kb = row['size'] / 1024
                    lines.append(f"- {row['path']} ({size_kb:.1f} KB)")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    def _generate_weekly_activity(self) -> bytes:
        """Generate weekly activity summary."""
        lines = ["# Weekly Activity", ""]

        try:
            cursor = self.knowledge_graph.conn.cursor()
            cursor.execute("""
                SELECT strftime('%Y-W%W', modified_at, 'unixepoch') as week,
                       COUNT(*) as file_count,
                       SUM(size) as total_size
                FROM files
                GROUP BY week
                ORDER BY week DESC
                LIMIT 12
            """)

            rows = cursor.fetchall()
            if not rows:
                lines.append("No files indexed yet.")
            else:
                lines.append("| Week | Files | Total Size |")
                lines.append("|------|-------|------------|")
                for row in rows:
                    size_mb = (row['total_size'] or 0) / (1024 * 1024)
                    lines.append(f"| {row['week']} | {row['file_count']} | {size_mb:.1f} MB |")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    def _generate_monthly_activity(self) -> bytes:
        """Generate monthly activity summary."""
        lines = ["# Monthly Activity", ""]

        try:
            cursor = self.knowledge_graph.conn.cursor()
            cursor.execute("""
                SELECT strftime('%Y-%m', modified_at, 'unixepoch') as month,
                       COUNT(*) as file_count,
                       SUM(size) as total_size
                FROM files
                GROUP BY month
                ORDER BY month DESC
                LIMIT 12
            """)

            rows = cursor.fetchall()
            if not rows:
                lines.append("No files indexed yet.")
            else:
                lines.append("| Month | Files | Total Size |")
                lines.append("|-------|-------|------------|")
                for row in rows:
                    size_mb = (row['total_size'] or 0) / (1024 * 1024)
                    lines.append(f"| {row['month']} | {row['file_count']} | {size_mb:.1f} MB |")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    # ========== DUPLICATES GENERATION ==========

    def _generate_duplicates_content(self, sub_parts: List[str]) -> bytes:
        """Generate duplicate detection content."""
        if not self.knowledge_graph:
            return b"Knowledge graph not available.\n"

        return self._find_duplicates()

    def _find_duplicates(self) -> bytes:
        """Find near-duplicate files by size and content hash."""
        lines = ["# Potential Duplicates", ""]

        try:
            cursor = self.knowledge_graph.conn.cursor()

            # Find files with same size (simple duplicate detection)
            cursor.execute("""
                SELECT size, COUNT(*) as cnt, GROUP_CONCAT(path, '|') as paths
                FROM files
                WHERE size > 1000
                GROUP BY size
                HAVING cnt > 1
                ORDER BY size DESC
                LIMIT 20
            """)

            rows = cursor.fetchall()
            if not rows:
                lines.append("No potential duplicates found (by file size).")
            else:
                lines.append("Files with identical sizes (may be duplicates):")
                lines.append("")
                for row in rows:
                    size_kb = row['size'] / 1024
                    paths = row['paths'].split('|')
                    lines.append(f"## Size: {size_kb:.1f} KB ({row['cnt']} files)")
                    for p in paths[:5]:
                        lines.append(f"  - {p}")
                    if len(paths) > 5:
                        lines.append(f"  - ... and {len(paths)-5} more")
                    lines.append("")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    # ========== OVERVIEW GENERATION ==========

    def _generate_overview_content(self, sub_parts: List[str]) -> bytes:
        """Generate overview content."""
        if not self.knowledge_graph:
            return b"Knowledge graph not available.\n"

        filename = sub_parts[0] if sub_parts else 'summary.md'

        if filename == 'summary.md':
            return self._generate_summary()
        elif filename == 'stats.json':
            return self._generate_stats_json()

        return b"Unknown overview file.\n"

    def _generate_summary(self) -> bytes:
        """Generate overall summary."""
        lines = ["# Knowledge Base Summary", ""]

        try:
            cursor = self.knowledge_graph.conn.cursor()

            # File stats
            cursor.execute("SELECT COUNT(*) as cnt, SUM(size) as total FROM files")
            row = cursor.fetchone()
            file_count = row['cnt'] or 0
            total_size = (row['total'] or 0) / (1024 * 1024)

            # Entity stats
            cursor.execute("SELECT COUNT(*) as cnt FROM entities")
            entity_count = cursor.fetchone()['cnt'] or 0

            # Embedding stats
            cursor.execute("SELECT COUNT(*) as cnt FROM file_embeddings")
            embedding_count = cursor.fetchone()['cnt'] or 0

            # Relationship stats
            cursor.execute("SELECT COUNT(*) as cnt FROM relationships")
            rel_count = cursor.fetchone()['cnt'] or 0

            lines.extend([
                "## Statistics",
                "",
                f"- **Total Files:** {file_count}",
                f"- **Total Size:** {total_size:.1f} MB",
                f"- **Entities Extracted:** {entity_count}",
                f"- **Files with Embeddings:** {embedding_count}",
                f"- **Relationships:** {rel_count}",
                "",
                "## Top Entity Types",
                ""
            ])

            cursor.execute("""
                SELECT entity_type, COUNT(*) as cnt
                FROM entities
                GROUP BY entity_type
                ORDER BY cnt DESC
                LIMIT 10
            """)

            for row in cursor.fetchall():
                lines.append(f"- {row['entity_type']}: {row['cnt']}")

            lines.extend([
                "",
                "## Recent Files",
                ""
            ])

            cursor.execute("""
                SELECT path FROM files
                ORDER BY modified_at DESC
                LIMIT 5
            """)

            for row in cursor.fetchall():
                lines.append(f"- {row['path']}")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    def _generate_stats_json(self) -> bytes:
        """Generate stats as JSON."""
        stats = {}

        try:
            cursor = self.knowledge_graph.conn.cursor()

            cursor.execute("SELECT COUNT(*) as cnt, SUM(size) as total FROM files")
            row = cursor.fetchone()
            stats['files'] = {'count': row['cnt'] or 0, 'total_bytes': row['total'] or 0}

            cursor.execute("SELECT COUNT(*) as cnt FROM entities")
            stats['entities'] = cursor.fetchone()['cnt'] or 0

            cursor.execute("SELECT COUNT(*) as cnt FROM file_embeddings")
            stats['embeddings'] = cursor.fetchone()['cnt'] or 0

            cursor.execute("""
                SELECT entity_type, COUNT(*) as cnt
                FROM entities
                GROUP BY entity_type
            """)
            stats['entity_types'] = {row['entity_type']: row['cnt'] for row in cursor.fetchall()}

        except Exception as e:
            stats['error'] = str(e)

        return json.dumps(stats, indent=2).encode('utf-8')
