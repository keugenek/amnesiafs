"""
Dual-View Generators Module

Generates auto-generated files for virtual folders:
- _DASHBOARD.html - Rich visual interface for humans
- _manifest.md - Readable summary with YAML frontmatter
- _index.json - Machine-readable metadata for agents

These files are generated lazily on access and cached.
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import html
from .utils import format_bytes


@dataclass
class FolderStats:
    """Statistics for a folder."""
    path: str
    file_count: int
    total_bytes: int
    topics: Dict[str, float]  # topic -> weight
    entities: List[str]
    recent_files: List[Dict[str, Any]]
    updated: str


class DashboardGenerator:
    """
    Generates _DASHBOARD.html for virtual folders.

    The HTML is self-contained with embedded CSS (no external dependencies).
    Opens in any browser for rich visual experience.
    """

    CSS_STYLES = """
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117; color: #c9d1d9; padding: 20px; line-height: 1.5;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #58a6ff; margin-bottom: 8px; font-size: 24px; }
        h2 { color: #8b949e; font-size: 14px; font-weight: normal; margin-bottom: 20px; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .stat-card { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; }
        .stat-value { font-size: 28px; font-weight: bold; color: #58a6ff; }
        .stat-label { font-size: 12px; color: #8b949e; text-transform: uppercase; }
        .section { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; margin-bottom: 16px; }
        .section-title { font-size: 14px; font-weight: 600; color: #c9d1d9; margin-bottom: 12px; border-bottom: 1px solid #30363d; padding-bottom: 8px; }
        .file-list { list-style: none; }
        .file-item { padding: 8px 0; border-bottom: 1px solid #21262d; display: flex; justify-content: space-between; }
        .file-item:last-child { border-bottom: none; }
        .file-name { color: #58a6ff; text-decoration: none; }
        .file-name:hover { text-decoration: underline; }
        .file-meta { color: #8b949e; font-size: 12px; }
        .tag { display: inline-block; background: #388bfd26; color: #58a6ff; padding: 2px 8px; border-radius: 12px; font-size: 12px; margin: 2px; }
        .entity { display: inline-block; background: #23863626; color: #3fb950; padding: 2px 8px; border-radius: 12px; font-size: 12px; margin: 2px; }
        .chart-bar { height: 20px; background: #388bfd; border-radius: 3px; margin: 4px 0; }
        .chart-label { display: flex; justify-content: space-between; font-size: 12px; color: #8b949e; }
        .empty { color: #8b949e; font-style: italic; padding: 20px; text-align: center; }
        .timestamp { color: #8b949e; font-size: 11px; margin-top: 20px; text-align: center; }
    </style>
    """

    def __init__(self, knowledge_graph=None):
        """Initialize with optional knowledge graph reference."""
        self.kg = knowledge_graph

    def generate(self, stats: FolderStats, title: str = None,
                 extra_sections: List[Dict] = None) -> bytes:
        """
        Generate _DASHBOARD.html content.

        Args:
            stats: Folder statistics
            title: Optional custom title
            extra_sections: Additional HTML sections to include

        Returns:
            HTML content as bytes
        """
        title = title or f"Dashboard: {stats.path}"
        subtitle = f"{stats.file_count} files | {format_bytes(stats.total_bytes)}"

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    {self.CSS_STYLES}
</head>
<body>
    <div class="container">
        <h1>{html.escape(title)}</h1>
        <h2>{html.escape(subtitle)}</h2>

        {self._generate_stats_cards(stats)}
        {self._generate_topics_section(stats.topics)}
        {self._generate_entities_section(stats.entities)}
        {self._generate_files_section(stats.recent_files)}
        {self._generate_extra_sections(extra_sections)}

        <p class="timestamp">Generated: {stats.updated}</p>
    </div>
</body>
</html>
"""
        return html_content.encode('utf-8')

    def _generate_stats_cards(self, stats: FolderStats) -> str:
        """Generate stat cards HTML."""
        return f"""
        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">{stats.file_count}</div>
                <div class="stat-label">Files</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{format_bytes(stats.total_bytes)}</div>
                <div class="stat-label">Total Size</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(stats.topics)}</div>
                <div class="stat-label">Topics</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(stats.entities)}</div>
                <div class="stat-label">Entities</div>
            </div>
        </div>
        """

    def _generate_topics_section(self, topics: Dict[str, float]) -> str:
        """Generate topics bar chart."""
        if not topics:
            return '<div class="section"><div class="section-title">Topics</div><p class="empty">No topics detected</p></div>'

        max_weight = max(topics.values()) if topics else 1
        bars = ""
        for topic, weight in sorted(topics.items(), key=lambda x: -x[1])[:10]:
            pct = (weight / max_weight) * 100
            bars += f"""
            <div class="chart-label"><span>{html.escape(topic)}</span><span>{weight:.0%}</span></div>
            <div class="chart-bar" style="width: {pct}%"></div>
            """

        return f'<div class="section"><div class="section-title">Topics</div>{bars}</div>'

    def _generate_entities_section(self, entities: List[str]) -> str:
        """Generate entities tag cloud."""
        if not entities:
            return '<div class="section"><div class="section-title">Key Entities</div><p class="empty">No entities extracted</p></div>'

        tags = "".join(f'<span class="entity">{html.escape(e)}</span>' for e in entities[:20])
        return f'<div class="section"><div class="section-title">Key Entities</div>{tags}</div>'

    def _generate_files_section(self, files: List[Dict[str, Any]]) -> str:
        """Generate recent files list."""
        if not files:
            return '<div class="section"><div class="section-title">Recent Files</div><p class="empty">No files</p></div>'

        items = ""
        for f in files[:10]:
            name = f.get('name', 'unknown')
            size = format_bytes(f.get('size', 0))
            date = f.get('modified', '')
            items += f"""
            <li class="file-item">
                <span class="file-name">{html.escape(name)}</span>
                <span class="file-meta">{size} | {date}</span>
            </li>
            """

        return f'<div class="section"><div class="section-title">Recent Files</div><ul class="file-list">{items}</ul></div>'

    def _generate_extra_sections(self, sections: List[Dict]) -> str:
        """Generate additional custom sections."""
        if not sections:
            return ""

        result = ""
        for section in sections:
            title = section.get('title', '')
            content = section.get('content', '')
            result += f'<div class="section"><div class="section-title">{html.escape(title)}</div>{content}</div>'
        return result


class ManifestGenerator:
    """
    Generates _manifest.md for virtual folders.

    Markdown with YAML frontmatter, readable by both humans and agents.
    """

    def __init__(self, knowledge_graph=None):
        """Initialize with optional knowledge graph reference."""
        self.kg = knowledge_graph

    def generate(self, stats: FolderStats, summary: str = None,
                 insights: List[str] = None, navigation: Dict[str, str] = None) -> bytes:
        """
        Generate _manifest.md content.

        Args:
            stats: Folder statistics
            summary: Optional summary paragraph
            insights: Key insights as bullet points
            navigation: Dict of subfolder -> description

        Returns:
            Markdown content as bytes
        """
        # YAML frontmatter
        frontmatter = {
            'path': stats.path,
            'updated': stats.updated,
            'files': stats.file_count,
            'size_bytes': stats.total_bytes,
            'topics': list(stats.topics.keys())[:5],
            'entities': stats.entities[:10],
        }

        yaml_block = "---\n"
        for key, value in frontmatter.items():
            if isinstance(value, list):
                yaml_block += f"{key}: {json.dumps(value)}\n"
            else:
                yaml_block += f"{key}: {value}\n"
        yaml_block += "---\n\n"

        # Title
        folder_name = stats.path.split('/')[-1] or 'Root'
        content = f"# {folder_name}\n\n"

        # Summary
        if summary:
            content += f"{summary}\n\n"
        else:
            content += f"This folder contains {stats.file_count} files ({format_bytes(stats.total_bytes)}).\n\n"

        # Key Insights
        if insights:
            content += "## Key Insights\n"
            for insight in insights:
                content += f"* {insight}\n"
            content += "\n"

        # Topics
        if stats.topics:
            content += "## Topics\n"
            for topic, weight in sorted(stats.topics.items(), key=lambda x: -x[1])[:5]:
                content += f"* **{topic}** ({weight:.0%})\n"
            content += "\n"

        # Entities
        if stats.entities:
            content += "## Key Entities\n"
            content += ", ".join(stats.entities[:10])
            if len(stats.entities) > 10:
                content += f" (+{len(stats.entities) - 10} more)"
            content += "\n\n"

        # Navigation
        if navigation:
            content += "## Navigation\n"
            for folder, description in navigation.items():
                content += f"* **{folder}/** - {description}\n"
            content += "\n"

        # Top Files
        if stats.recent_files:
            content += "## Top Files\n"
            for i, f in enumerate(stats.recent_files[:5], 1):
                name = f.get('name', 'unknown')
                content += f"{i}. {name}\n"
            content += "\n"

        return (yaml_block + content).encode('utf-8')


class IndexGenerator:
    """
    Generates _index.json for virtual folders.

    Structured JSON for programmatic access by agents and tools.
    """

    def __init__(self, knowledge_graph=None):
        """Initialize with optional knowledge graph reference."""
        self.kg = knowledge_graph

    def generate(self, stats: FolderStats, query: str = None,
                 extra_fields: Dict[str, Any] = None) -> bytes:
        """
        Generate _index.json content.

        Args:
            stats: Folder statistics
            query: Optional query that generated this folder
            extra_fields: Additional fields to include

        Returns:
            JSON content as bytes
        """
        data = {
            'path': stats.path,
            'updated': stats.updated,
            'file_count': stats.file_count,
            'total_bytes': stats.total_bytes,
            'topics': stats.topics,
            'entities': stats.entities,
            'files': stats.recent_files,
        }

        if query:
            data['query'] = query

        if extra_fields:
            data.update(extra_fields)

        return json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')


class GeneratorFactory:
    """
    Factory for creating generators and generating all three file types.
    """

    def __init__(self, knowledge_graph=None):
        """Initialize factory with optional knowledge graph."""
        self.kg = knowledge_graph
        self.dashboard = DashboardGenerator(knowledge_graph)
        self.manifest = ManifestGenerator(knowledge_graph)
        self.index = IndexGenerator(knowledge_graph)

        # Cache for generated content
        self._cache: Dict[str, Tuple[float, bytes]] = {}  # path -> (timestamp, content)
        self._cache_ttl = 30  # seconds

    def get_stats_from_kg(self, path: str) -> FolderStats:
        """
        Build FolderStats from knowledge graph data.

        Args:
            path: Virtual path (e.g., '/.ai/inbox')

        Returns:
            FolderStats with data from knowledge graph
        """
        now = datetime.now().isoformat()

        if not self.kg:
            return FolderStats(
                path=path,
                file_count=0,
                total_bytes=0,
                topics={},
                entities=[],
                recent_files=[],
                updated=now
            )

        # Get stats from knowledge graph
        try:
            cursor = self.kg.conn.cursor()

            # File count and size
            cursor.execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM files")
            row = cursor.fetchone()
            file_count = row[0] if row else 0
            total_bytes = row[1] if row else 0

            # Top entities
            cursor.execute("""
                SELECT name FROM entities
                ORDER BY source_count DESC
                LIMIT 20
            """)
            entities = [row[0] for row in cursor.fetchall()]

            # Recent files
            cursor.execute("""
                SELECT path, size, modified_at FROM files
                ORDER BY modified_at DESC
                LIMIT 10
            """)
            recent_files = [
                {
                    'name': os.path.basename(row[0]) if row[0] else 'unknown',
                    'path': row[0],
                    'size': row[1],
                    'modified': datetime.fromtimestamp(row[2]).strftime('%Y-%m-%d %H:%M') if row[2] else ''
                }
                for row in cursor.fetchall()
            ]

            # Topic distribution (simplified - count entity types)
            cursor.execute("""
                SELECT entity_type, COUNT(*) as cnt FROM entities
                GROUP BY entity_type ORDER BY cnt DESC
            """)
            topics = {row[0]: row[1] / max(file_count, 1) for row in cursor.fetchall()}

            return FolderStats(
                path=path,
                file_count=file_count,
                total_bytes=total_bytes,
                topics=topics,
                entities=entities,
                recent_files=recent_files,
                updated=now
            )
        except Exception:
            return FolderStats(
                path=path,
                file_count=0,
                total_bytes=0,
                topics={},
                entities=[],
                recent_files=[],
                updated=now
            )

    def generate_all(self, path: str, stats: FolderStats = None,
                     title: str = None) -> Dict[str, bytes]:
        """
        Generate all three files for a virtual folder.

        Args:
            path: Virtual path
            stats: Optional pre-computed stats
            title: Optional custom title

        Returns:
            Dict with '_DASHBOARD.html', '_manifest.md', '_index.json' keys
        """
        if stats is None:
            stats = self.get_stats_from_kg(path)

        return {
            '_DASHBOARD.html': self.dashboard.generate(stats, title=title),
            '_manifest.md': self.manifest.generate(stats),
            '_index.json': self.index.generate(stats),
        }

    def get_cached_or_generate(self, path: str, filename: str,
                                cognitivefs=None) -> bytes:
        """
        Get cached content or generate new.

        Args:
            path: Virtual path
            filename: One of '_DASHBOARD.html', '_manifest.md', '_index.json'
            cognitivefs: Optional CognitiveFS instance for version control access

        Returns:
            File content as bytes
        """
        cache_key = f"{path}/{filename}"
        now = time.time()

        # Check cache
        if cache_key in self._cache:
            timestamp, content = self._cache[cache_key]
            if now - timestamp < self._cache_ttl:
                return content

        # Check if this is the versions path - use special generator
        if path == '/.ai/versions':
            content = self._generate_versions_file(filename, cognitivefs)
            self._cache[cache_key] = (now, content)
            return content

        # Generate fresh using standard stats
        stats = self.get_stats_from_kg(path)

        if filename == '_DASHBOARD.html':
            content = self.dashboard.generate(stats)
        elif filename == '_manifest.md':
            content = self.manifest.generate(stats)
        elif filename == '_index.json':
            content = self.index.generate(stats)
        else:
            content = b''

        # Cache it
        self._cache[cache_key] = (now, content)
        return content

    def _generate_versions_file(self, filename: str, cognitivefs=None) -> bytes:
        """Generate version-specific dashboard/manifest/index."""
        now = datetime.now()

        # Get version control stats
        vc_stats = {
            'enabled': False,
            'total_commits': 0,
            'tracked_files': 0,
            'repo_path': '',
            'lfs_available': False,
            'remotes': {},
        }
        commits = []

        if cognitivefs and hasattr(cognitivefs, 'version_control'):
            vc = cognitivefs.version_control
            if vc and vc.enabled:
                vc_stats = vc.get_stats()
                commits = vc.get_all_commits(limit=20)

        if filename == '_DASHBOARD.html':
            return self._generate_versions_dashboard(vc_stats, commits, now)
        elif filename == '_manifest.md':
            return self._generate_versions_manifest(vc_stats, commits, now)
        elif filename == '_index.json':
            return self._generate_versions_index(vc_stats, commits, now)
        return b''

    def _generate_versions_dashboard(self, stats: dict, commits: list,
                                     now: datetime) -> bytes:
        """Generate version history dashboard HTML."""
        # Build commit timeline
        commit_items = ""
        for c in commits[:15]:
            ts = datetime.fromtimestamp(c['timestamp']).strftime('%Y-%m-%d %H:%M')
            short_hash = c['hash'][:8]
            message = html.escape(c['message'][:50])
            commit_items += f"""
            <li class="file-item">
                <span class="file-name" title="{c['hash']}">{short_hash}</span>
                <span>{message}</span>
                <span class="file-meta">{ts}</span>
            </li>
            """

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Version Control Dashboard</title>
    {DashboardGenerator.CSS_STYLES}
</head>
<body>
    <div class="container">
        <h1>Version Control Dashboard</h1>
        <h2>Git-backed transparent versioning</h2>

        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">{stats.get('total_commits', 0)}</div>
                <div class="stat-label">Commits</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{stats.get('tracked_files', 0)}</div>
                <div class="stat-label">Tracked Files</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{'Yes' if stats.get('lfs_available') else 'No'}</div>
                <div class="stat-label">Git LFS</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(stats.get('remotes', {}))}</div>
                <div class="stat-label">Remotes</div>
            </div>
        </div>

        <div class="section">
            <div class="section-title">Recent Commits</div>
            {'<ul class="file-list">' + commit_items + '</ul>' if commit_items else '<p class="empty">No commits yet</p>'}
        </div>

        <div class="section">
            <div class="section-title">Usage</div>
            <ul class="file-list">
                <li class="file-item"><code>cat /.ai/versions/commits</code> - List all commits</li>
                <li class="file-item"><code>cat /.ai/versions/file/path.txt</code> - File history</li>
                <li class="file-item"><code>cat /.ai/versions/&lt;hash&gt;/_info.txt</code> - Commit details</li>
                <li class="file-item"><code>cat /.ai/versions/&lt;hash&gt;/_diff.txt</code> - Commit diff</li>
            </ul>
        </div>

        <p class="timestamp">Generated: {now.isoformat()}</p>
    </div>
</body>
</html>
"""
        return html_content.encode('utf-8')

    def _generate_versions_manifest(self, stats: dict, commits: list,
                                    now: datetime) -> bytes:
        """Generate version history manifest markdown."""
        frontmatter = f"""---
path: /.ai/versions
updated: {now.isoformat()}
total_commits: {stats.get('total_commits', 0)}
tracked_files: {stats.get('tracked_files', 0)}
lfs_available: {stats.get('lfs_available', False)}
remotes: {list(stats.get('remotes', {}).keys())}
---

# Version Control

Git-backed transparent versioning for all files.

## Statistics
* **Total Commits:** {stats.get('total_commits', 0)}
* **Tracked Files:** {stats.get('tracked_files', 0)}
* **Git LFS:** {'Available' if stats.get('lfs_available') else 'Not available'}
* **Repo Path:** {stats.get('repo_path', 'N/A')}

## Recent Commits
"""
        for c in commits[:10]:
            ts = datetime.fromtimestamp(c['timestamp']).strftime('%Y-%m-%d %H:%M')
            frontmatter += f"* `{c['hash'][:8]}` - {c['message'][:40]} ({ts})\n"

        frontmatter += """
## Usage

```
cat /.ai/versions/commits           # List all commits
cat /.ai/versions/file/path.txt     # File version history
cat /.ai/versions/<hash>/_info.txt  # Commit details
```
"""
        return frontmatter.encode('utf-8')

    def _generate_versions_index(self, stats: dict, commits: list,
                                 now: datetime) -> bytes:
        """Generate version history index JSON."""
        data = {
            'path': '/.ai/versions',
            'updated': now.isoformat(),
            'version_control': {
                'enabled': stats.get('enabled', False),
                'total_commits': stats.get('total_commits', 0),
                'tracked_files': stats.get('tracked_files', 0),
                'lfs_available': stats.get('lfs_available', False),
                'repo_path': stats.get('repo_path', ''),
                'remotes': stats.get('remotes', {}),
            },
            'recent_commits': [
                {
                    'hash': c['hash'],
                    'short_hash': c['hash'][:8],
                    'message': c['message'],
                    'author': c['author'],
                    'timestamp': c['timestamp'],
                    'date': datetime.fromtimestamp(c['timestamp']).isoformat(),
                }
                for c in commits[:20]
            ]
        }
        return json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')

    def invalidate_cache(self, path: str = None):
        """
        Invalidate cache for a path or all paths.

        Args:
            path: Specific path to invalidate, or None for all
        """
        if path is None:
            self._cache.clear()
        else:
            keys_to_remove = [k for k in self._cache if k.startswith(path)]
            for k in keys_to_remove:
                del self._cache[k]
