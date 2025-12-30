"""
Facts handler for /.ai/facts/

Provides access to LLM-extracted facts (subject-predicate-object triples).

Paths:
- /.ai/facts/                    - Overview and stats
- /.ai/facts/all.md              - All facts
- /.ai/facts/by-subject/<name>   - Facts about subject
- /.ai/facts/by-predicate/<pred> - Facts by relationship type
- /.ai/facts/about/<entity>      - Facts mentioning entity
- /.ai/facts/search/<query>      - Search facts
"""

import time
import json
from typing import Optional, Dict, List
from urllib.parse import unquote
from .base import BaseHandler


class FactsHandler(BaseHandler):
    """Handles /.ai/facts/ virtual paths."""

    SUBFOLDERS = ['by-subject', 'by-predicate', 'about', 'search']
    FILES = ['_help.txt', 'all.md', 'stats.json', 'predicates.md']

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for facts paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        clean_path = target_path.lstrip('/')
        path_parts = clean_path.split('/') if clean_path else []

        if not path_parts:
            return self._make_dir_stat(now)

        first = path_parts[0]

        # Root level files
        if first in self.FILES:
            content = self._get_file_content(first)
            return self._make_file_stat(len(content), now)

        # Subfolders
        if first in self.SUBFOLDERS:
            if len(path_parts) == 1:
                return self._make_dir_stat(now)
            # File within subfolder
            content = self._get_subfolder_content(first, path_parts[1:])
            return self._make_file_stat(len(content), now)

        return None

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """List facts directory contents."""
        if not target_path:
            return self.SUBFOLDERS + self.FILES

        clean_path = target_path.lstrip('/')
        path_parts = clean_path.split('/') if clean_path else []

        if not path_parts:
            return self.SUBFOLDERS + self.FILES

        first = path_parts[0]

        if first == 'by-subject':
            return self._list_subjects()
        elif first == 'by-predicate':
            return self._list_predicates()
        elif first == 'about':
            return self._list_entities()
        elif first == 'search':
            return ['_help.txt']

        return []

    def read(self, target_path: str, parts: List[str]) -> bytes:
        """Read facts content."""
        if not target_path:
            return self._get_help()

        clean_path = target_path.lstrip('/')
        path_parts = clean_path.split('/') if clean_path else []

        if not path_parts:
            return self._get_help()

        first = path_parts[0]

        # Root level files
        if first in self.FILES:
            return self._get_file_content(first)

        # Subfolders
        if first in self.SUBFOLDERS:
            if len(path_parts) == 1:
                return self._get_subfolder_help(first)
            return self._get_subfolder_content(first, path_parts[1:])

        return b"Not found.\n"

    def _get_help(self) -> bytes:
        """Return help text."""
        return b"""# Facts - LLM-Extracted Knowledge

## Overview
Facts are structured triples: (Subject) --[Predicate]--> (Object)
Extracted automatically from indexed files using LLM.

## Paths

### Browse by Subject
    ls /.ai/facts/by-subject/
    cat /.ai/facts/by-subject/Evgenii

### Browse by Predicate (Relationship Type)
    ls /.ai/facts/by-predicate/
    cat /.ai/facts/by-predicate/created

### Find All Facts About an Entity
    cat /.ai/facts/about/reactor

### Search Facts
    cat /.ai/facts/search/python+dependencies

### View All Facts
    cat /.ai/facts/all.md

### Statistics
    cat /.ai/facts/stats.json

## Common Predicates
- created, authored_by, founded
- works_at, located_in, part_of
- depends_on, uses, imports
- mentions, discusses, describes
- related_to, similar_to
"""

    def _get_file_content(self, filename: str) -> bytes:
        """Get content of root level files."""
        if filename == '_help.txt':
            return self._get_help()
        elif filename == 'all.md':
            return self._get_all_facts()
        elif filename == 'stats.json':
            return self._get_stats_json()
        elif filename == 'predicates.md':
            return self._get_predicates_summary()
        return b"Unknown file.\n"

    def _get_subfolder_help(self, subfolder: str) -> bytes:
        """Get help for subfolder."""
        if subfolder == 'by-subject':
            return b"# Facts by Subject\n\nList files to see available subjects.\ncat /.ai/facts/by-subject/<subject_name>\n"
        elif subfolder == 'by-predicate':
            return b"# Facts by Predicate\n\nList files to see relationship types.\ncat /.ai/facts/by-predicate/<predicate>\n"
        elif subfolder == 'about':
            return b"# Facts About Entity\n\nFind all facts mentioning an entity.\ncat /.ai/facts/about/<entity_name>\n"
        elif subfolder == 'search':
            return b"# Search Facts\n\nSearch facts by keyword.\ncat /.ai/facts/search/<query>\n"
        return b"Unknown subfolder.\n"

    def _get_subfolder_content(self, subfolder: str, sub_parts: List[str]) -> bytes:
        """Get content within subfolder."""
        if not sub_parts:
            return self._get_subfolder_help(subfolder)

        query = unquote(sub_parts[0].replace('+', ' ').replace('.md', ''))

        if subfolder == 'by-subject':
            return self._get_facts_by_subject(query)
        elif subfolder == 'by-predicate':
            return self._get_facts_by_predicate(query)
        elif subfolder == 'about':
            return self._get_facts_about(query)
        elif subfolder == 'search':
            return self._search_facts(query)

        return b"Unknown query.\n"

    def _list_subjects(self) -> List[str]:
        """List unique subjects."""
        if not self.knowledge_graph:
            return []
        try:
            cursor = self.knowledge_graph.conn.cursor()
            cursor.execute("""
                SELECT DISTINCT subject FROM facts
                ORDER BY subject
                LIMIT 100
            """)
            return [row['subject'].replace('/', '_') + '.md' for row in cursor.fetchall()]
        except:
            return []

    def _list_predicates(self) -> List[str]:
        """List unique predicates."""
        if not self.knowledge_graph:
            return []
        try:
            cursor = self.knowledge_graph.conn.cursor()
            cursor.execute("""
                SELECT DISTINCT predicate FROM facts
                ORDER BY predicate
            """)
            return [row['predicate'] + '.md' for row in cursor.fetchall()]
        except:
            return []

    def _list_entities(self) -> List[str]:
        """List entities that appear in facts."""
        if not self.knowledge_graph:
            return []
        try:
            cursor = self.knowledge_graph.conn.cursor()
            cursor.execute("""
                SELECT DISTINCT entity FROM (
                    SELECT subject as entity FROM facts
                    UNION
                    SELECT object as entity FROM facts
                )
                ORDER BY entity
                LIMIT 100
            """)
            return [row['entity'].replace('/', '_') + '.md' for row in cursor.fetchall()]
        except:
            return []

    def _get_all_facts(self) -> bytes:
        """Get all facts as markdown."""
        if not self.knowledge_graph:
            return b"Knowledge graph not available.\n"

        lines = ["# All Extracted Facts", ""]

        try:
            cursor = self.knowledge_graph.conn.cursor()
            cursor.execute("""
                SELECT f.subject, f.predicate, f.object, f.confidence,
                       files.path as source_path
                FROM facts f
                LEFT JOIN files ON f.source_file_id = files.id
                ORDER BY f.confidence DESC
                LIMIT 200
            """)

            rows = cursor.fetchall()
            if not rows:
                lines.append("No facts extracted yet.")
                lines.append("")
                lines.append("Facts are extracted when files are processed.")
                lines.append("Make sure LLM (Ollama) is running.")
            else:
                lines.append(f"**Total: {len(rows)} facts** (showing max 200)")
                lines.append("")
                lines.append("| Subject | Predicate | Object | Confidence | Source |")
                lines.append("|---------|-----------|--------|------------|--------|")
                for row in rows:
                    subj = (row['subject'] or '')[:30]
                    pred = row['predicate'] or ''
                    obj = (row['object'] or '')[:30]
                    conf = f"{row['confidence']:.2f}" if row['confidence'] else ''
                    src = (row['source_path'] or '')[-30:]
                    lines.append(f"| {subj} | {pred} | {obj} | {conf} | {src} |")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    def _get_stats_json(self) -> bytes:
        """Get facts statistics as JSON."""
        if not self.knowledge_graph:
            return b'{"error": "Knowledge graph not available"}\n'

        try:
            stats = self.knowledge_graph.get_fact_stats()
            return json.dumps(stats, indent=2).encode('utf-8')
        except Exception as e:
            return json.dumps({"error": str(e)}).encode('utf-8')

    def _get_predicates_summary(self) -> bytes:
        """Get summary of predicates."""
        if not self.knowledge_graph:
            return b"Knowledge graph not available.\n"

        lines = ["# Predicate Summary", ""]

        try:
            cursor = self.knowledge_graph.conn.cursor()
            cursor.execute("""
                SELECT predicate, COUNT(*) as cnt
                FROM facts
                GROUP BY predicate
                ORDER BY cnt DESC
            """)

            rows = cursor.fetchall()
            if not rows:
                lines.append("No facts extracted yet.")
            else:
                lines.append("| Predicate | Count |")
                lines.append("|-----------|-------|")
                for row in rows:
                    lines.append(f"| {row['predicate']} | {row['cnt']} |")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    def _get_facts_by_subject(self, subject: str) -> bytes:
        """Get facts about a subject."""
        if not self.knowledge_graph:
            return b"Knowledge graph not available.\n"

        lines = [f"# Facts about: {subject}", ""]

        try:
            facts = self.knowledge_graph.get_facts_by_subject(subject)
            if not facts:
                lines.append(f"No facts found for subject '{subject}'.")
            else:
                for f in facts:
                    lines.append(f"- **{f['predicate']}** → {f['object']} [{f['confidence']:.2f}]")
                    if f.get('source_path'):
                        lines.append(f"  - Source: {f['source_path']}")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    def _get_facts_by_predicate(self, predicate: str) -> bytes:
        """Get facts with a predicate."""
        if not self.knowledge_graph:
            return b"Knowledge graph not available.\n"

        lines = [f"# Facts with predicate: {predicate}", ""]

        try:
            facts = self.knowledge_graph.get_facts_by_predicate(predicate)
            if not facts:
                lines.append(f"No facts found for predicate '{predicate}'.")
            else:
                for f in facts:
                    lines.append(f"- {f['subject']} → **{f['predicate']}** → {f['object']}")
                    if f.get('source_path'):
                        lines.append(f"  - Source: {f['source_path']}")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    def _get_facts_about(self, entity: str) -> bytes:
        """Get all facts mentioning an entity."""
        if not self.knowledge_graph:
            return b"Knowledge graph not available.\n"

        lines = [f"# Facts about: {entity}", ""]

        try:
            facts = self.knowledge_graph.get_facts_about(entity)
            if not facts:
                lines.append(f"No facts found mentioning '{entity}'.")
            else:
                lines.append("## As Subject")
                as_subject = [f for f in facts if f['subject'].lower() == entity.lower()]
                if as_subject:
                    for f in as_subject:
                        lines.append(f"- **{f['predicate']}** → {f['object']}")
                else:
                    lines.append("- (none)")

                lines.append("")
                lines.append("## As Object")
                as_object = [f for f in facts if f['object'].lower() == entity.lower()]
                if as_object:
                    for f in as_object:
                        lines.append(f"- {f['subject']} **{f['predicate']}** →")
                else:
                    lines.append("- (none)")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')

    def _search_facts(self, query: str) -> bytes:
        """Search facts."""
        if not self.knowledge_graph:
            return b"Knowledge graph not available.\n"

        lines = [f"# Search results: {query}", ""]

        try:
            facts = self.knowledge_graph.search_facts(query)
            if not facts:
                lines.append(f"No facts found matching '{query}'.")
            else:
                lines.append(f"Found {len(facts)} matching facts:")
                lines.append("")
                for f in facts:
                    lines.append(f"- ({f['subject']}) --[{f['predicate']}]--> ({f['object']})")
                    if f.get('source_path'):
                        lines.append(f"  - Source: {f['source_path']}")

        except Exception as e:
            lines.append(f"Error: {e}")

        return "\n".join(lines).encode('utf-8')
