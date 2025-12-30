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
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import struct

logger = logging.getLogger(__name__)


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
    # Structured data types
    FIELD = "field"           # JSON/YAML keys
    COLUMN = "column"         # CSV headers
    SCHEMA_TYPE = "schema_type"  # Value type metadata


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
-- LLM-extracted facts (subject-predicate-object triples)
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL DEFAULT 0.8,
    source_file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    context TEXT,
    extracted_at INTEGER DEFAULT (strftime('%s', 'now')),
    UNIQUE(subject, predicate, object, source_file_id)
);

CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject);
CREATE INDEX IF NOT EXISTS idx_facts_predicate ON facts(predicate);
CREATE INDEX IF NOT EXISTS idx_facts_object ON facts(object);
CREATE INDEX IF NOT EXISTS idx_facts_file ON facts(source_file_id);

-- FTS5 for facts search
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    subject, predicate, object, context,
    content='facts',
    content_rowid='id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, subject, predicate, object, context)
    VALUES (new.id, new.subject, new.predicate, new.object, new.context);
END;

CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, subject, predicate, object, context)
    VALUES ('delete', old.id, old.subject, old.predicate, old.object, old.context);
END;
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

        # Ensure unique index on embeddings (file_id, model) - fixes BUG-014
        # SQLite partial indexes don't work with ON CONFLICT, so drop old partial
        # index if it exists and create a regular one
        cursor.execute("DROP INDEX IF EXISTS idx_emb_file_model")
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_emb_file_model_v2
            ON embeddings(file_id, model)
        """)
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

    def rename_file(self, old_path: str, new_path: str):
        """Update file path in knowledge graph after rename."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE files SET path = ? WHERE path = ?", (new_path, old_path))
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

    # ==================== Hybrid Search (Phase 1 RAG Improvement) ====================

    def bm25_search(self, query: str, limit: int = 20) -> List[Tuple[int, float]]:
        """
        BM25 keyword search using SQLite FTS5.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of (file_id, bm25_score) tuples, higher score = better match
        """
        cursor = self.conn.cursor()

        # FTS5 bm25() returns negative scores (closer to 0 = better match)
        # We negate it so higher = better
        try:
            cursor.execute("""
                SELECT f.id, -bm25(files_fts) as score
                FROM files f
                JOIN files_fts fts ON f.id = fts.rowid
                WHERE files_fts MATCH ?
                ORDER BY score DESC
                LIMIT ?
            """, (query, limit))
            return [(row['id'], row['score']) for row in cursor.fetchall()]
        except sqlite3.OperationalError as e:
            # Handle FTS5 query syntax errors gracefully
            logger.debug(f"BM25 search failed for query '{query}': {e}")
            return []

    def semantic_search(self, query_embedding: bytes, limit: int = 20,
                       threshold: float = 0.1) -> List[Tuple[int, float]]:
        """
        Semantic search using cosine similarity on embeddings.

        Args:
            query_embedding: Query vector as packed bytes
            limit: Maximum results
            threshold: Minimum similarity threshold

        Returns:
            List of (file_id, similarity) tuples, higher = better match
        """
        from .embedder import cosine_similarity

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT f.id, e.vector
            FROM files f
            JOIN embeddings e ON f.embedding_id = e.id
            WHERE e.vector IS NOT NULL
        """)

        results = []
        for row in cursor.fetchall():
            sim = cosine_similarity(query_embedding, row['vector'])
            if sim > threshold:
                results.append((row['id'], sim))

        # Sort by similarity descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def hybrid_search(self, query: str, query_embedding: bytes = None,
                     limit: int = 10, alpha: float = 0.5,
                     rrf_k: int = 60) -> List[Tuple[FileRecord, float]]:
        """
        Hybrid search combining BM25 keyword search with semantic search.

        Uses Reciprocal Rank Fusion (RRF) to combine results from both methods.
        RRF score = sum(1 / (k + rank)) for each result list.

        Args:
            query: Search query text
            query_embedding: Optional pre-computed query embedding
            limit: Maximum results to return
            alpha: Weight for semantic vs BM25 (0.5 = equal weight)
            rrf_k: RRF constant (default 60, higher = smoother fusion)

        Returns:
            List of (FileRecord, combined_score) tuples sorted by score
        """
        from collections import defaultdict

        # 1. BM25 keyword search
        bm25_results = self.bm25_search(query, limit * 2)

        # 2. Semantic search (if embedding provided)
        semantic_results = []
        if query_embedding:
            semantic_results = self.semantic_search(query_embedding, limit * 2)

        # 3. Reciprocal Rank Fusion
        rrf_scores = defaultdict(float)

        # Add BM25 scores with weight (1 - alpha)
        for rank, (file_id, _) in enumerate(bm25_results):
            rrf_scores[file_id] += (1 - alpha) * (1 / (rrf_k + rank + 1))

        # Add semantic scores with weight alpha
        for rank, (file_id, _) in enumerate(semantic_results):
            rrf_scores[file_id] += alpha * (1 / (rrf_k + rank + 1))

        # 4. Sort by combined RRF score
        sorted_ids = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        # 5. Fetch full file records
        results = []
        for file_id, score in sorted_ids[:limit]:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
            row = cursor.fetchone()
            if row:
                results.append((self._row_to_file(row), score))

        return results

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

        # Always query for actual ID - lastrowid behavior varies with ON CONFLICT
        cursor.execute("""
            SELECT id FROM entities
            WHERE entity_type = ? AND normalized_name = ?
        """, (entity.entity_type.value, normalized))
        row = cursor.fetchone()
        return row['id'] if row else 0

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


    # ==================== Facts Operations ====================

    def add_fact(self, subject: str, predicate: str, obj: str,
                 confidence: float = 0.8, source_file_id: int = None,
                 context: str = None) -> int:
        """
        Add a fact (subject-predicate-object triple).
        
        Args:
            subject: The subject entity
            predicate: The relationship type (e.g., 'works_at', 'created')
            obj: The object entity
            confidence: Confidence score (0-1)
            source_file_id: File this fact was extracted from
            context: Text context where fact was found
            
        Returns:
            Fact ID
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO facts (subject, predicate, object, confidence,
                                  source_file_id, context)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject, predicate, object, source_file_id) DO UPDATE SET
                    confidence = MAX(facts.confidence, excluded.confidence),
                    context = COALESCE(excluded.context, facts.context)
            """, (subject, predicate, obj, confidence, source_file_id, context))
            self.conn.commit()
            
            if cursor.lastrowid == 0:
                cursor.execute("""
                    SELECT id FROM facts
                    WHERE subject = ? AND predicate = ? AND object = ?
                    AND (source_file_id = ? OR (source_file_id IS NULL AND ? IS NULL))
                """, (subject, predicate, obj, source_file_id, source_file_id))
                row = cursor.fetchone()
                return row['id'] if row else 0
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to add fact: {e}")
            return 0

    def get_facts_for_file(self, file_id: int) -> List[Dict]:
        """Get all facts extracted from a specific file."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, subject, predicate, object, confidence, context, extracted_at
            FROM facts
            WHERE source_file_id = ?
            ORDER BY confidence DESC
        """, (file_id,))
        return [dict(row) for row in cursor.fetchall()]

    def search_facts(self, query: str, limit: int = 50) -> List[Dict]:
        """Search facts using FTS5."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT f.id, f.subject, f.predicate, f.object, f.confidence,
                       f.context, f.source_file_id, files.path as source_path
                FROM facts_fts fts
                JOIN facts f ON fts.rowid = f.id
                LEFT JOIN files ON f.source_file_id = files.id
                WHERE facts_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.debug(f"Facts FTS search failed: {e}")
            # Fallback to LIKE search
            like_pattern = f"%{query}%"
            cursor.execute("""
                SELECT f.id, f.subject, f.predicate, f.object, f.confidence,
                       f.context, f.source_file_id, files.path as source_path
                FROM facts f
                LEFT JOIN files ON f.source_file_id = files.id
                WHERE f.subject LIKE ? OR f.predicate LIKE ? OR f.object LIKE ?
                ORDER BY f.confidence DESC
                LIMIT ?
            """, (like_pattern, like_pattern, like_pattern, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_facts_by_subject(self, subject: str, limit: int = 50) -> List[Dict]:
        """Get all facts about a subject."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT f.id, f.subject, f.predicate, f.object, f.confidence,
                   f.context, f.source_file_id, files.path as source_path
            FROM facts f
            LEFT JOIN files ON f.source_file_id = files.id
            WHERE LOWER(f.subject) = LOWER(?)
            ORDER BY f.confidence DESC
            LIMIT ?
        """, (subject, limit))
        return [dict(row) for row in cursor.fetchall()]

    def get_facts_by_predicate(self, predicate: str, limit: int = 50) -> List[Dict]:
        """Get all facts with a specific predicate/relationship type."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT f.id, f.subject, f.predicate, f.object, f.confidence,
                   f.context, f.source_file_id, files.path as source_path
            FROM facts f
            LEFT JOIN files ON f.source_file_id = files.id
            WHERE LOWER(f.predicate) = LOWER(?)
            ORDER BY f.confidence DESC
            LIMIT ?
        """, (predicate, limit))
        return [dict(row) for row in cursor.fetchall()]

    def get_facts_about(self, entity: str, limit: int = 50) -> List[Dict]:
        """Get all facts mentioning an entity (as subject or object)."""
        cursor = self.conn.cursor()
        entity_lower = entity.lower()
        cursor.execute("""
            SELECT f.id, f.subject, f.predicate, f.object, f.confidence,
                   f.context, f.source_file_id, files.path as source_path
            FROM facts f
            LEFT JOIN files ON f.source_file_id = files.id
            WHERE LOWER(f.subject) = ? OR LOWER(f.object) = ?
            ORDER BY f.confidence DESC
            LIMIT ?
        """, (entity_lower, entity_lower, limit))
        return [dict(row) for row in cursor.fetchall()]

    def delete_facts_for_file(self, file_id: int) -> int:
        """Delete all facts from a specific file (for re-extraction)."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM facts WHERE source_file_id = ?", (file_id,))
        self.conn.commit()
        return cursor.rowcount

    def get_fact_stats(self) -> Dict:
        """Get statistics about extracted facts."""
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as total FROM facts")
        total = cursor.fetchone()['total']
        
        cursor.execute("""
            SELECT predicate, COUNT(*) as cnt
            FROM facts
            GROUP BY predicate
            ORDER BY cnt DESC
            LIMIT 20
        """)
        by_predicate = {row['predicate']: row['cnt'] for row in cursor.fetchall()}
        
        cursor.execute("SELECT COUNT(DISTINCT source_file_id) as files FROM facts")
        files_with_facts = cursor.fetchone()['files']
        
        return {
            'total_facts': total,
            'files_with_facts': files_with_facts,
            'by_predicate': by_predicate
        }

        # ==================== Embedding Operations ====================

    def add_embedding(self, embedding: Embedding) -> int:
        """Add or update an embedding vector."""
        cursor = self.conn.cursor()
        now = time.time()

        cursor.execute("""
            INSERT INTO embeddings (entity_id, file_id, model, dimensions,
                                   vector, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_id, model) DO UPDATE SET
                vector = excluded.vector,
                dimensions = excluded.dimensions,
                created_at = excluded.created_at
        """, (
            embedding.entity_id, embedding.file_id, embedding.model,
            embedding.dimensions, embedding.vector, now
        ))

        self.conn.commit()

        # Return the id (lastrowid is 0 on conflict, so query if needed)
        if cursor.lastrowid == 0 and embedding.file_id:
            cursor.execute(
                "SELECT id FROM embeddings WHERE file_id = ? AND model = ?",
                (embedding.file_id, embedding.model)
            )
            row = cursor.fetchone()
            return row['id'] if row else 0

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

    def get_similar_files(self, file_id: int, limit: int = 10) -> List[Tuple[FileRecord, float]]:
        """
        Find files similar to the given file based on embedding similarity.

        Args:
            file_id: ID of the file to find similar files for
            limit: Maximum number of similar files to return

        Returns:
            List of (FileRecord, similarity_score) tuples sorted by similarity
        """
        from .embedder import cosine_similarity

        # Get the source file's embedding
        source_embedding = self.get_embedding(file_id=file_id)
        if not source_embedding or not source_embedding.vector:
            return []

        cursor = self.conn.cursor()

        # Get all other files with embeddings
        cursor.execute("""
            SELECT f.*, e.vector
            FROM files f
            JOIN embeddings e ON f.embedding_id = e.id
            WHERE f.id != ? AND e.vector IS NOT NULL
        """, (file_id,))

        results = []
        for row in cursor.fetchall():
            similarity = cosine_similarity(source_embedding.vector, row['vector'])
            if similarity > 0.1:  # Only include files with meaningful similarity
                file_record = self._row_to_file(row)
                results.append((file_record, similarity))

        # Sort by similarity descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

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

    # ==================== Processing Queue Operations ====================

    def queue_operation(self, file_id: int, operation: str,
                       priority: int = 0) -> int:
        """
        Add operation to processing queue.

        Args:
            file_id: ID of file to process
            operation: Operation type ('index', 'embed', 'extract', 'summarize')
            priority: Higher priority = processed first

        Returns:
            Queue item ID
        """
        cursor = self.conn.cursor()
        now = time.time()

        cursor.execute("""
            INSERT INTO processing_queue (file_id, operation, priority, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
        """, (file_id, operation, priority, now))

        self.conn.commit()
        return cursor.lastrowid

    def get_pending_operations(self, limit: int = 10) -> List[Dict]:
        """
        Get pending operations from queue.

        Returns oldest pending items first, sorted by priority.

        Args:
            limit: Maximum items to return

        Returns:
            List of queue items as dicts
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM processing_queue
            WHERE status = 'pending'
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
        """, (limit,))

        return [dict(row) for row in cursor.fetchall()]

    def mark_operation_processing(self, queue_id: int):
        """Mark operation as being processed."""
        cursor = self.conn.cursor()
        now = time.time()

        cursor.execute("""
            UPDATE processing_queue
            SET status = 'processing', started_at = ?
            WHERE id = ?
        """, (now, queue_id))

        self.conn.commit()

    def mark_operation_completed(self, queue_id: int):
        """Mark operation as completed."""
        cursor = self.conn.cursor()
        now = time.time()

        cursor.execute("""
            UPDATE processing_queue
            SET status = 'completed', completed_at = ?
            WHERE id = ?
        """, (now, queue_id))

        self.conn.commit()

    def mark_operation_failed(self, queue_id: int, error: str):
        """Mark operation as failed with error message."""
        cursor = self.conn.cursor()
        now = time.time()

        cursor.execute("""
            UPDATE processing_queue
            SET status = 'failed', completed_at = ?, error_message = ?
            WHERE id = ?
        """, (now, error, queue_id))

        self.conn.commit()

    def update_file_extraction(self, file_id: int, extracted_text: str,
                              content_hash: str, summary: str = ""):
        """
        Update file with extraction results.

        Args:
            file_id: File ID to update
            extracted_text: Extracted text content
            content_hash: SHA-256 hash of content
            summary: Optional summary text
        """
        cursor = self.conn.cursor()
        now = time.time()

        cursor.execute("""
            UPDATE files
            SET extracted_text = ?, content_hash = ?, summary = ?,
                indexed_at = ?
            WHERE id = ?
        """, (extracted_text, content_hash, summary, now, file_id))

        self.conn.commit()

    def set_file_embedding(self, file_id: int, embedding_id: int):
        """Link file to its embedding."""
        cursor = self.conn.cursor()

        cursor.execute("""
            UPDATE files SET embedding_id = ? WHERE id = ?
        """, (embedding_id, file_id))

        self.conn.commit()

    def get_queue_stats(self) -> Dict[str, int]:
        """Get processing queue statistics."""
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM processing_queue
            GROUP BY status
        """)

        stats = {'pending': 0, 'processing': 0, 'completed': 0, 'failed': 0}
        for row in cursor.fetchall():
            stats[row['status']] = row['count']

        return stats

    def clear_completed_queue(self, older_than_hours: int = 24):
        """
        Clear completed queue items older than specified hours.

        Args:
            older_than_hours: Remove items completed more than this many hours ago
        """
        cursor = self.conn.cursor()
        cutoff = time.time() - (older_than_hours * 3600)

        cursor.execute("""
            DELETE FROM processing_queue
            WHERE status = 'completed' AND completed_at < ?
        """, (cutoff,))

        self.conn.commit()
        return cursor.rowcount

    def retry_failed_operations(self):
        """Reset failed operations to pending for retry."""
        cursor = self.conn.cursor()

        cursor.execute("""
            UPDATE processing_queue
            SET status = 'pending', error_message = NULL,
                started_at = NULL, completed_at = NULL
            WHERE status = 'failed'
        """)

        self.conn.commit()
        return cursor.rowcount
