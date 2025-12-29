"""
Search handler for /.ai/search/
"""

import time
from typing import Optional, Dict, List
from .base import BaseHandler


class SearchHandler(BaseHandler):
    """Handles /.ai/search/ virtual paths for full-text search."""

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for search paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        return self._make_file_stat(4096, now)

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """List files in /.ai/search/."""
        if not target_path:
            return ["_help.txt"]
        return []

    def read(self, target_path: str, parts: List[str]) -> bytes:
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
