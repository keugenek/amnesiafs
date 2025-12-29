"""
Entities handler for /.ai/entities/
"""

import time
from typing import Optional, Dict, List
from .base import BaseHandler


class EntitiesHandler(BaseHandler):
    """Handles /.ai/entities/ virtual paths for entity browsing."""

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for entities paths."""
        now = int(time.time())

        # /.ai/entities/ - directory listing
        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files and other editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        # /.ai/entities/<type>/ - entity type directory
        path_parts = target_path.strip('/').split('/')
        if len(path_parts) == 1:
            try:
                from ..knowledge_graph import EntityType
                EntityType(path_parts[0])
                return self._make_dir_stat(now)
            except (ValueError, ImportError):
                pass  # Not an entity type, might be a file path

        # /.ai/entities/<type>/<entity_name> or /.ai/entities/<filepath>
        return self._make_file_stat(4096, now)

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """Read directory for entities view."""
        if not target_path:
            # List entity types + help
            try:
                from ..knowledge_graph import EntityType
                return ["_help.txt"] + [et.value for et in EntityType]
            except ImportError:
                return ["_help.txt"]

        # List entities of a given type
        parts_list = target_path.strip('/').split('/')
        if len(parts_list) == 1 and self.knowledge_graph:
            try:
                from ..knowledge_graph import EntityType
                entity_type = EntityType(parts_list[0])
                entities = self.knowledge_graph.get_entities_by_type(entity_type, limit=100)
                return [e.name.replace(' ', '_').replace('/', '-') for e in entities]
            except (ValueError, ImportError):
                pass  # Invalid entity type

        return []

    def read(self, target_path: str, parts: List[str]) -> bytes:
        """
        Show entity details or entities extracted from a specific file.

        Usage:
            cat /.ai/entities/_help.txt              - Show help
            cat /.ai/entities/concept/FIELD          - Show details for FIELD entity
            cat /.ai/entities/path/to/file.md        - Show entities from file
        """
        if not target_path:
            return b""

        if target_path == "_help.txt":
            return self._get_entities_help()

        # Check if this is an entity type + entity name query
        path_parts = target_path.strip('/').split('/')
        if len(path_parts) == 2:
            try:
                from ..knowledge_graph import EntityType
                entity_type = EntityType(path_parts[0])
                raw_name = path_parts[1]
                # Try original name first (for dates like 2024-01-15)
                result = self._get_entity_details(entity_type, raw_name)
                if b"Entity not found" not in result:
                    return result
                # Try with underscore->space replacement (for names like "John_Doe")
                result = self._get_entity_details(entity_type, raw_name.replace('_', ' '))
                if b"Entity not found" not in result:
                    return result
                # Try with dash->slash replacement (for file paths like "src-file.py")
                return self._get_entity_details(entity_type, raw_name.replace('_', ' ').replace('-', '/'))
            except (ValueError, ImportError):
                pass  # Not a valid entity type, fall through to file entities

        return self._get_file_entities(target_path)

    def _get_entities_help(self) -> bytes:
        """Return help text for file entities view."""
        help_text = """# File Entity View

## Usage

Show entities extracted from a specific file:
    cat /.ai/entities/path/to/file.md
    cat /.ai/entities/profiles/geekyinventor/README.md

## What it shows

- Person entities (names mentioned in the file)
- Organization entities (companies, groups)
- Concept entities (technical terms, topics)
- Other entity types (dates, locations, etc.)

## How it works

1. When files are indexed, entities are extracted using NLP
2. Each entity has a confidence score
3. Context shows where the entity was found in the file

## Related commands

- cat /.ai/graph/entities       - List all entities
- cat /.ai/graph/context/<name> - Full context for an entity
- cat /.ai/search/<query>       - Search for entities/files
"""
        return help_text.encode('utf-8')

    def _get_entity_details(self, entity_type, entity_name: str) -> bytes:
        """Get details about a specific entity."""
        if not self.knowledge_graph:
            return b"Knowledge graph not initialized.\n"

        # Find the entity using correct API: get_entity(type, name)
        entity = self.knowledge_graph.get_entity(entity_type, entity_name)

        if not entity:
            return f"Entity not found: {entity_name}\n".encode('utf-8')

        lines = [
            f"# Entity: {entity.name}",
            f"Type: {entity.entity_type.value}",
            ""
        ]

        if entity.description:
            lines.extend(["## Description", entity.description, ""])

        # Get files that mention this entity (returns List[FileRecord])
        related_files = self.knowledge_graph.get_entity_files(entity.id)
        if related_files:
            lines.append(f"## Found in Files ({len(related_files)})")
            for file_record in related_files[:20]:
                lines.append(f"  - {file_record.path}")
            if len(related_files) > 20:
                lines.append(f"  ... and {len(related_files) - 20} more")
            lines.append("")

        # Get related entities (returns List[Entity])
        related = self.knowledge_graph.get_related_entities(entity.id, depth=1)
        if related:
            lines.append(f"## Related Entities ({len(related)})")
            for rel_entity in related[:10]:
                lines.append(f"  - {rel_entity.name} ({rel_entity.entity_type.value})")
            lines.append("")

        return "\n".join(lines).encode('utf-8')

    def _get_file_entities(self, file_path: str) -> bytes:
        """Get entities extracted from a specific file."""
        if not self.knowledge_graph:
            return b"Knowledge graph not initialized.\n"

        # Ensure file_path starts with /
        if not file_path.startswith("/"):
            file_path = "/" + file_path

        # Get file record
        file_record = self.knowledge_graph.get_file(file_path)
        if not file_record:
            return f"File not indexed: {file_path}\n\nTo index files, they must be written through CognitiveFS.\n".encode('utf-8')

        # Get entities for this file
        file_entities = self.knowledge_graph.get_file_entities(file_record.id)

        if not file_entities:
            return f"# Entities in {file_path}\n\nNo entities extracted from this file.\n".encode('utf-8')

        lines = [
            f"# Entities in {file_path}",
            f"Found {len(file_entities)} entities",
            ""
        ]

        # Group entities by type
        by_type = {}
        for entity, rel_type, confidence in file_entities:
            etype = entity.entity_type.value
            if etype not in by_type:
                by_type[etype] = []
            by_type[etype].append((entity, rel_type, confidence))

        # Display by type
        for etype, entities in sorted(by_type.items()):
            lines.append(f"## {etype.title()} ({len(entities)})")
            for entity, rel_type, confidence in sorted(entities, key=lambda x: x[2], reverse=True):
                lines.append(f"  - {entity.name} (confidence: {confidence:.2f})")
                if entity.description:
                    desc = entity.description[:80] + "..." if len(entity.description) > 80 else entity.description
                    lines.append(f"    {desc}")
            lines.append("")

        return "\n".join(lines).encode('utf-8')
