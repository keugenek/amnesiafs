"""
Knowledge Graph Module

Implements the SQLite-based knowledge graph for CognitiveFS.
Stores entities, relationships, embeddings, and semantic metadata
extracted from files.

The knowledge graph supports:
- Entity extraction and storage
- Relationship tracking
- Full-text search via FTS5
- Embedding storage for semantic search
- Temporal versioning
- Multi-hop reasoning queries
"""

import os
import sys
import time
import json
import sqlite3
import hashlib
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import struct


class EntityType(Enum):
    """Types of entities in the knowledge graph."""
    FILE = "file"
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    CONCEPT = "concept"
    DATE = "date"
    EVENT = "event"
    PROJECT = "project"
    TOPIC = "topic"
    TAG = "tag"


class RelationType(Enum):
    """Types of relationships between entities."""
    CONTAINS = "contains"           # File contains entity
    MENTIONS = "mentions"           # File mentions entity
    REFERENCES = "references"       # File references another file
    SIMILAR_TO = "similar_to"       # Semantic similarity
    RELATED_TO = "related_to"       # General relation
    PART_OF = "part_of"            # Hierarchical
    CAUSES = "causes"              # Causal
    PRECEDED_BY = "preceded_by"    # Temporal
    FOLLOWED_BY = "followed_by"    # Temporal
    CREATED_BY = "created_by"      # Authorship
    TAGGED_WITH = "tagged_with"    # User tags
    LINKED_TO = "linked_to"        # Explicit links


@dataclass
class Entity:
    """Represents an entity in the knowledge graph."""
    id: int = 0
    entity_type: EntityType = EntityType.CONCEPT
    name: str = ""
    normalized_name: str = ""  # Lowercase, normalized version for matching
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0
    updated_at: float = 0
    confidence: float = 1.0
    source_count: int = 0  # Number of files mentioning this entity


@dataclass
class Relationship:
    """Represents a relationship between entities."""
    id: int = 0
    source_id: int = 0
    target_id: int = 0
    relation_type: RelationType = RelationType.RELATED_TO
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0


@dataclass
class FileRecord:
    """Represents a file's knowledge graph metadata."""
    id: int = 0
    inode_num: int = 0
    path: str = ""
    content_hash: str = ""  # SHA-256 of content
    size: int = 0
    mime_type: str = ""
    created_at: float = 0
    modified_at: float = 0
    indexed_at: float = 0
    embedding_id: Optional[int] = None
    summary: str = ""
    extracted_text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Embedding:
    """Represents a vector embedding."""
    id: int = 0
    entity_id: Optional[int] = None
    file_id: Optional[int] = None
    model: str = ""  # e.g., "all-MiniLM-L6-v2"
    dimensions: int = 384
    vector: bytes = b""  # Packed float32 array
    created_at: float = 0


SCHEMA_VERSION = 1

# SQL schema for knowledge graph
SCHEMA_SQL = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    created_at REAL NOT NULL
);

-- Files indexed in the knowledge graph
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inode_num INTEGER NOT NULL,
    path TEXT NOT NULL UNIQUE,
    content_hash TEXT,
    size INTEGER DEFAULT 0,
    mime_type TEXT DEFAULT '',
    created_at REAL NOT NULL,
    modified_at REAL NOT NULL,
    indexed_at REAL NOT NULL,
    embedding_id INTEGER,
    summary TEXT DEFAULT '',
    extracted_text TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (embedding_id) REFERENCES embeddings(id)
);

CREATE INDEX IF NOT EXISTS idx_files_inode ON files(inode_num);
CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
CREATE INDEX IF NOT EXISTS idx_files_hash ON files(content_hash);
CREATE INDEX IF NOT EXISTS idx_files_modified ON files(modified_at);

-- Full-text search index for files
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    path,
    summary,
    extracted_text,
    content='files',
    content_rowid='id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, path, summary, extracted_text)
    VALUES (new.id, new.path, new.summary, new.extracted_text);
END;

CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, path, summary, extracted_text)
    VALUES ('delete', old.id, old.path, old.summary, old.extracted_text);
END;

CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, path, summary, extracted_text)
    VALUES ('delete', old.id, old.path, old.summary, old.extracted_text);
    INSERT INTO files_fts(rowid, path, summary, extracted_text)
    VALUES (new.id, new.path, new.summary, new.extracted_text);
END;

-- Entities in the knowledge graph
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    description TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    confidence REAL DEFAULT 1.0,
    source_count INTEGER DEFAULT 0,
    embedding_id INTEGER,
    FOREIGN KEY (embedding_id) REFERENCES embeddings(id),
    UNIQUE(entity_type, normalized_name)
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(normalized_name);

-- Full-text search for entities
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    name,
    description,
    content='entities',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS entities_ai AFTER INSERT ON entities BEGIN
    INSERT INTO entities_fts(rowid, name, description)
    VALUES (new.id, new.name, new.description);
END;

CREATE TRIGGER IF NOT EXISTS entities_ad AFTER DELETE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, name, description)
    VALUES ('delete', old.id, old.name, old.description);
END;

CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, name, description)
    VALUES ('delete', old.id, old.name, old.description);
    INSERT INTO entities_fts(rowid, name, description)
    VALUES (new.id, new.name, new.description);
END;

-- Relationships between entities
CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    metadata TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (source_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES entities(id) ON DELETE CASCADE,
    UNIQUE(source_id, target_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id);
CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(relation_type);

-- File-entity associations
CREATE TABLE IF NOT EXISTS file_entities (
    file_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    relation_type TEXT DEFAULT 'contains',
    confidence REAL DEFAULT 1.0,
    context TEXT DEFAULT '',  -- Surrounding text where entity was found
    position INTEGER DEFAULT 0,  -- Byte offset in file
    created_at REAL NOT NULL,
    PRIMARY KEY (file_id, entity_id, relation_type),
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fe_file ON file_entities(file_id);
CREATE INDEX IF NOT EXISTS idx_fe_entity ON file_entities(entity_id);

-- Vector embeddings
CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER,
    file_id INTEGER,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector BLOB NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_emb_entity ON embeddings(entity_id);
CREATE INDEX IF NOT EXISTS idx_emb_file ON embeddings(file_id);
CREATE INDEX IF NOT EXISTS idx_emb_model ON embeddings(model);

-- Topic clusters
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    parent_id INTEGER,
    level INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES topics(id) ON DELETE SET NULL
);

-- File-topic associations
CREATE TABLE IF NOT EXISTS file_topics (
    file_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    confidence REAL DEFAULT 1.0,
    created_at REAL NOT NULL,
    PRIMARY KEY (file_id, topic_id),
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
);

-- Chat/conversation history (episodic memory)
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_name TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,  -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    timestamp REAL NOT NULL,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);

-- Query history (for learning user patterns)
CREATE TABLE IF NOT EXISTS query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    results TEXT DEFAULT '[]',
    timestamp REAL NOT NULL,
    duration_ms REAL DEFAULT 0
);

-- Processing queue for async operations
CREATE TABLE IF NOT EXISTS processing_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER,
    operation TEXT NOT NULL,  -- 'index', 'embed', 'extract', 'summarize'
    priority INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed'
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    error_message TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON processing_queue(status, priority);
"""


class KnowledgeGraph:
    """
    SQLite-based knowledge graph for CognitiveFS.

    Provides storage and retrieval for:
    - File metadata and content hashes
    - Extracted entities (people, places, concepts, etc.)
    - Relationships between entities
    - Vector embeddings for semantic search
    - Topic clustering
    - Conversation/chat history
    """

    def __init__(self, db_path: str):
        """
        Initialize knowledge graph.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def open(self):
        """Open database connection and initialize schema."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def _init_schema(self):
        """Initialize database schema."""
        cursor = self.conn.cursor()

        # Check schema version
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='schema_version'
        """)
        if not cursor.fetchone():
            # Create schema
            cursor.executescript(SCHEMA_SQL)
            cursor.execute(
                "INSERT INTO schema_version (version, created_at) VALUES (?, ?)",
                (SCHEMA_VERSION, time.time())
            )
            self.conn.commit()

    # ==================== File Operations ====================

    def add_file(self, file: FileRecord) -> int:
        """Add or update a file record."""
        cursor = self.conn.cursor()
        now = time.time()

        cursor.execute("""
            INSERT INTO files (inode_num, path, content_hash, size, mime_type,
                             created_at, modified_at, indexed_at, summary,
                             extracted_text, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                content_hash = excluded.content_hash,
                size = excluded.size,
                mime_type = excluded.mime_type,
                modified_at = excluded.modified_at,
                indexed_at = excluded.indexed_at,
                summary = excluded.summary,
                extracted_text = excluded.extracted_text,
                metadata = excluded.metadata
        """, (
            file.inode_num, file.path, file.content_hash, file.size,
            file.mime_type, file.created_at, file.modified_at, now,
            file.summary, file.extracted_text, json.dumps(file.metadata)
        ))

        self.conn.commit()
        return cursor.lastrowid

    def get_file(self, path: str) -> Optional[FileRecord]:
        """Get file record by path."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM files WHERE path = ?", (path,))
        row = cursor.fetchone()
        if row:
            return self._row_to_file(row)
        return None

    def get_file_by_inode(self, inode_num: int) -> Optional[FileRecord]:
        """Get file record by inode number."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM files WHERE inode_num = ?", (inode_num,))
        row = cursor.fetchone()
        if row:
            return self._row_to_file(row)
        return None

    def delete_file(self, path: str):
        """Delete file record."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM files WHERE path = ?", (path,))
        self.conn.commit()

    def search_files(self, query: str, limit: int = 20) -> List[FileRecord]:
        """Full-text search for files."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT f.* FROM files f
            JOIN files_fts fts ON f.id = fts.rowid
            WHERE files_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        return [self._row_to_file(row) for row in cursor.fetchall()]

    def get_recent_files(self, limit: int = 20) -> List[FileRecord]:
        """Get recently modified files."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM files ORDER BY modified_at DESC LIMIT ?
        """, (limit,))
        return [self._row_to_file(row) for row in cursor.fetchall()]

    def _row_to_file(self, row: sqlite3.Row) -> FileRecord:
        """Convert database row to FileRecord."""
        return FileRecord(
            id=row['id'],
            inode_num=row['inode_num'],
            path=row['path'],
            content_hash=row['content_hash'] or '',
            size=row['size'],
            mime_type=row['mime_type'],
            created_at=row['created_at'],
            modified_at=row['modified_at'],
            indexed_at=row['indexed_at'],
            embedding_id=row['embedding_id'],
            summary=row['summary'],
            extracted_text=row['extracted_text'],
            metadata=json.loads(row['metadata'])
        )

    # ==================== Entity Operations ====================

    def add_entity(self, entity: Entity) -> int:
        """Add or update an entity."""
        cursor = self.conn.cursor()
        now = time.time()

        normalized = entity.name.lower().strip()

        cursor.execute("""
            INSERT INTO entities (entity_type, name, normalized_name, description,
                                metadata, created_at, updated_at, confidence, source_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_type, normalized_name) DO UPDATE SET
                name = CASE WHEN length(excluded.name) > length(entities.name)
                           THEN excluded.name ELSE entities.name END,
                description = CASE WHEN length(excluded.description) > 0
                                  THEN excluded.description ELSE entities.description END,
                updated_at = excluded.updated_at,
                source_count = entities.source_count + 1
        """, (
            entity.entity_type.value, entity.name, normalized,
            entity.description, json.dumps(entity.metadata),
            now, now, entity.confidence, 1
        ))

        self.conn.commit()
        return cursor.lastrowid

    def get_entity(self, entity_type: EntityType, name: str) -> Optional[Entity]:
        """Get entity by type and name."""
        cursor = self.conn.cursor()
        normalized = name.lower().strip()
        cursor.execute("""
            SELECT * FROM entities WHERE entity_type = ? AND normalized_name = ?
        """, (entity_type.value, normalized))
        row = cursor.fetchone()
        if row:
            return self._row_to_entity(row)
        return None

    def get_entity_by_id(self, entity_id: int) -> Optional[Entity]:
        """Get entity by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_entity(row)
        return None

    def search_entities(self, query: str, limit: int = 20) -> List[Entity]:
        """Full-text search for entities."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT e.* FROM entities e
            JOIN entities_fts fts ON e.id = fts.rowid
            WHERE entities_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        return [self._row_to_entity(row) for row in cursor.fetchall()]

    def get_entities_by_type(self, entity_type: EntityType, limit: int = 100) -> List[Entity]:
        """Get all entities of a specific type."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM entities WHERE entity_type = ?
            ORDER BY source_count DESC LIMIT ?
        """, (entity_type.value, limit))
        return [self._row_to_entity(row) for row in cursor.fetchall()]

    def _row_to_entity(self, row: sqlite3.Row) -> Entity:
        """Convert database row to Entity."""
        return Entity(
            id=row['id'],
            entity_type=EntityType(row['entity_type']),
            name=row['name'],
            normalized_name=row['normalized_name'],
            description=row['description'],
            metadata=json.loads(row['metadata']),
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            confidence=row['confidence'],
            source_count=row['source_count']
        )

    # ==================== Relationship Operations ====================

    def add_relationship(self, source_id: int, target_id: int,
                        relation_type: RelationType, weight: float = 1.0,
                        metadata: Dict = None) -> int:
        """Add or update a relationship."""
        cursor = self.conn.cursor()
        now = time.time()

        cursor.execute("""
            INSERT INTO relationships (source_id, target_id, relation_type,
                                      weight, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
                weight = excluded.weight,
                metadata = excluded.metadata
        """, (
            source_id, target_id, relation_type.value,
            weight, json.dumps(metadata or {}), now
        ))

        self.conn.commit()
        return cursor.lastrowid

    def get_relationships(self, entity_id: int,
                         direction: str = "both") -> List[Relationship]:
        """Get relationships for an entity."""
        cursor = self.conn.cursor()

        if direction == "outgoing":
            cursor.execute(
                "SELECT * FROM relationships WHERE source_id = ?", (entity_id,)
            )
        elif direction == "incoming":
            cursor.execute(
                "SELECT * FROM relationships WHERE target_id = ?", (entity_id,)
            )
        else:
            cursor.execute("""
                SELECT * FROM relationships
                WHERE source_id = ? OR target_id = ?
            """, (entity_id, entity_id))

        return [self._row_to_relationship(row) for row in cursor.fetchall()]

    def _row_to_relationship(self, row: sqlite3.Row) -> Relationship:
        """Convert database row to Relationship."""
        return Relationship(
            id=row['id'],
            source_id=row['source_id'],
            target_id=row['target_id'],
            relation_type=RelationType(row['relation_type']),
            weight=row['weight'],
            metadata=json.loads(row['metadata']),
            created_at=row['created_at']
        )

    # ==================== File-Entity Association ====================

    def link_file_entity(self, file_id: int, entity_id: int,
                        relation_type: str = "contains",
                        confidence: float = 1.0, context: str = ""):
        """Link a file to an entity."""
        cursor = self.conn.cursor()
        now = time.time()

        cursor.execute("""
            INSERT INTO file_entities (file_id, entity_id, relation_type,
                                      confidence, context, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_id, entity_id, relation_type) DO UPDATE SET
                confidence = MAX(file_entities.confidence, excluded.confidence),
                context = CASE WHEN length(excluded.context) > 0
                              THEN excluded.context ELSE file_entities.context END
        """, (file_id, entity_id, relation_type, confidence, context, now))

        self.conn.commit()

    def get_file_entities(self, file_id: int) -> List[Tuple[Entity, str, float]]:
        """Get entities associated with a file."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT e.*, fe.relation_type, fe.confidence
            FROM entities e
            JOIN file_entities fe ON e.id = fe.entity_id
            WHERE fe.file_id = ?
            ORDER BY fe.confidence DESC
        """, (file_id,))

        results = []
        for row in cursor.fetchall():
            entity = self._row_to_entity(row)
            results.append((entity, row['relation_type'], row['confidence']))
        return results

    def get_entity_files(self, entity_id: int) -> List[FileRecord]:
        """Get files associated with an entity."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT f.* FROM files f
            JOIN file_entities fe ON f.id = fe.file_id
            WHERE fe.entity_id = ?
            ORDER BY f.modified_at DESC
        """, (entity_id,))
        return [self._row_to_file(row) for row in cursor.fetchall()]

    # ==================== Embedding Operations ====================

    def add_embedding(self, embedding: Embedding) -> int:
        """Add an embedding vector."""
        cursor = self.conn.cursor()
        now = time.time()

        cursor.execute("""
            INSERT INTO embeddings (entity_id, file_id, model, dimensions,
                                   vector, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            embedding.entity_id, embedding.file_id, embedding.model,
            embedding.dimensions, embedding.vector, now
        ))

        self.conn.commit()
        return cursor.lastrowid

    def get_embedding(self, file_id: int = None, entity_id: int = None) -> Optional[Embedding]:
        """Get embedding by file or entity ID."""
        cursor = self.conn.cursor()

        if file_id:
            cursor.execute("SELECT * FROM embeddings WHERE file_id = ?", (file_id,))
        elif entity_id:
            cursor.execute("SELECT * FROM embeddings WHERE entity_id = ?", (entity_id,))
        else:
            return None

        row = cursor.fetchone()
        if row:
            return Embedding(
                id=row['id'],
                entity_id=row['entity_id'],
                file_id=row['file_id'],
                model=row['model'],
                dimensions=row['dimensions'],
                vector=row['vector'],
                created_at=row['created_at']
            )
        return None

    # ==================== Topic Operations ====================

    def add_topic(self, name: str, description: str = "",
                 parent_id: int = None) -> int:
        """Add a topic."""
        cursor = self.conn.cursor()
        now = time.time()

        level = 0
        if parent_id:
            cursor.execute("SELECT level FROM topics WHERE id = ?", (parent_id,))
            row = cursor.fetchone()
            if row:
                level = row['level'] + 1

        cursor.execute("""
            INSERT INTO topics (name, description, parent_id, level,
                              created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description = excluded.description,
                updated_at = excluded.updated_at
        """, (name, description, parent_id, level, now, now))

        self.conn.commit()
        return cursor.lastrowid

    def get_topics(self, parent_id: int = None) -> List[Dict]:
        """Get topics, optionally filtered by parent."""
        cursor = self.conn.cursor()

        if parent_id is None:
            cursor.execute("SELECT * FROM topics WHERE parent_id IS NULL")
        else:
            cursor.execute("SELECT * FROM topics WHERE parent_id = ?", (parent_id,))

        return [dict(row) for row in cursor.fetchall()]

    def link_file_topic(self, file_id: int, topic_id: int, confidence: float = 1.0):
        """Link a file to a topic."""
        cursor = self.conn.cursor()
        now = time.time()

        cursor.execute("""
            INSERT INTO file_topics (file_id, topic_id, confidence, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(file_id, topic_id) DO UPDATE SET
                confidence = excluded.confidence
        """, (file_id, topic_id, confidence, now))

        self.conn.commit()

    # ==================== Statistics ====================

    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge graph statistics."""
        cursor = self.conn.cursor()

        stats = {}

        cursor.execute("SELECT COUNT(*) as count FROM files")
        stats['files_indexed'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM entities")
        stats['entities'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM relationships")
        stats['relationships'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM embeddings")
        stats['embeddings'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM topics")
        stats['topics'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM conversations")
        stats['conversations'] = cursor.fetchone()['count']

        cursor.execute("""
            SELECT entity_type, COUNT(*) as count
            FROM entities GROUP BY entity_type
        """)
        stats['entities_by_type'] = {
            row['entity_type']: row['count']
            for row in cursor.fetchall()
        }

        return stats

    # ==================== Multi-hop Queries ====================

    def find_path(self, source_id: int, target_id: int,
                 max_hops: int = 3) -> List[List[int]]:
        """
        Find paths between two entities in the knowledge graph.

        Uses BFS to find shortest paths up to max_hops.
        """
        if source_id == target_id:
            return [[source_id]]

        visited = {source_id}
        queue = [[source_id]]
        paths = []

        while queue and len(paths) < 10:
            path = queue.pop(0)
            current = path[-1]

            if len(path) > max_hops + 1:
                continue

            # Get neighbors
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT DISTINCT target_id as neighbor FROM relationships
                WHERE source_id = ?
                UNION
                SELECT DISTINCT source_id as neighbor FROM relationships
                WHERE target_id = ?
            """, (current, current))

            for row in cursor.fetchall():
                neighbor = row['neighbor']
                if neighbor == target_id:
                    paths.append(path + [neighbor])
                elif neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        return paths

    def get_related_entities(self, entity_id: int, depth: int = 1) -> List[Entity]:
        """Get entities related to the given entity up to specified depth."""
        visited = {entity_id}
        current_level = [entity_id]
        results = []

        for _ in range(depth):
            next_level = []
            for eid in current_level:
                cursor = self.conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT e.* FROM entities e
                    JOIN relationships r ON (e.id = r.target_id OR e.id = r.source_id)
                    WHERE (r.source_id = ? OR r.target_id = ?) AND e.id != ?
                """, (eid, eid, eid))

                for row in cursor.fetchall():
                    if row['id'] not in visited:
                        visited.add(row['id'])
                        next_level.append(row['id'])
                        results.append(self._row_to_entity(row))

            current_level = next_level

        return results
