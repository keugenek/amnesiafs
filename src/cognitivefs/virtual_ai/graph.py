"""
Graph handler for /.ai/graph/ (knowledge graph navigation)
"""

import json
import time
from typing import Optional, Dict, List
from .base import BaseHandler


class GraphHandler(BaseHandler):
    """Handles /.ai/graph/ virtual paths for knowledge graph queries."""

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for graph paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files and editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        # /.ai/graph/<endpoint> or /.ai/graph/<endpoint>/<args>
        stripped = target_path.strip('/')
        path_parts = stripped.split('/')

        # Directories: connections/, context/, query/, entities/page/
        if path_parts[0] in ('connections', 'context', 'query'):
            if len(path_parts) == 1:
                return self._make_dir_stat(now)
            return self._make_file_stat(4096, now)

        if path_parts[0] == 'entities' and len(path_parts) >= 2 and path_parts[1] == 'page':
            return self._make_file_stat(4096, now)

        # Files: stats, entities, relationships, _help.txt
        return self._make_file_stat(4096, now)

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """List graph endpoints."""
        if not target_path:
            return [
                "_help.txt",
                "stats",
                "entities",
                "relationships",
                "connections",
                "context",
                "query"
            ]
        return []

    def read(self, target_path: str, parts: List[str]) -> bytes:
        """Read graph query results."""
        if not target_path:
            return self._get_graph_help()

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
            from ..knowledge_graph import EntityType
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
            from ..relationship_detector import MultiHopQueryEngine

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
            from ..relationship_detector import MultiHopQueryEngine

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
            from ..relationship_detector import MultiHopQueryEngine

            engine = MultiHopQueryEngine(self.knowledge_graph)
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
            from ..relationship_detector import MultiHopQueryEngine

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
