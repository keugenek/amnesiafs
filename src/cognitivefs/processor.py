"""
Background Processor Module

Processes files asynchronously for knowledge extraction and embedding generation.
Runs as a background thread, polling the processing queue and handling files
without blocking filesystem operations.
"""

import os
import re
import time
import threading
import logging
from typing import Optional, Callable, Any, Set
from queue import Queue, Empty

from .knowledge_graph import KnowledgeGraph, FileRecord, Entity, EntityType, Embedding
from .extractor import ContentExtractor, EntityExtractor, extract_all, ExtractedEntityType
from .embedder import EmbeddingGenerator
from .relationship_detector import RelationshipDetector

logger = logging.getLogger(__name__)


# Map extractor entity types to knowledge graph entity types
ENTITY_TYPE_MAP = {
    ExtractedEntityType.PERSON: EntityType.PERSON,
    ExtractedEntityType.ORGANIZATION: EntityType.ORGANIZATION,
    ExtractedEntityType.EMAIL: EntityType.CONCEPT,
    ExtractedEntityType.URL: EntityType.CONCEPT,
    ExtractedEntityType.DATE: EntityType.DATE,
    ExtractedEntityType.HASHTAG: EntityType.TAG,
    ExtractedEntityType.CODE_CLASS: EntityType.CONCEPT,
    ExtractedEntityType.CODE_FUNCTION: EntityType.CONCEPT,
    ExtractedEntityType.FILE_PATH: EntityType.FILE,
    ExtractedEntityType.KEYWORD: EntityType.CONCEPT,
    # Structured data types
    ExtractedEntityType.FIELD: EntityType.FIELD,
    ExtractedEntityType.COLUMN: EntityType.COLUMN,
    ExtractedEntityType.SCHEMA_TYPE: EntityType.SCHEMA_TYPE,
}

# Directories to ignore during indexing (version control, build artifacts, etc.)
IGNORED_DIRECTORIES: Set[str] = {
    '.git',
    '.hg',
    '.svn',
    '.bzr',
    'node_modules',
    '__pycache__',
    '.pytest_cache',
    '.mypy_cache',
    '.tox',
    '.nox',
    '.eggs',
    '*.egg-info',
    '.venv',
    'venv',
    'env',
    '.env',
    'dist',
    'build',
    '.cache',
    '.idea',
    '.vscode',
    '.DS_Store',
}

# File patterns to ignore (compiled, temp, lock files)
IGNORED_FILE_PATTERNS: Set[str] = {
    r'\.pyc$',
    r'\.pyo$',
    r'\.class$',
    r'\.o$',
    r'\.so$',
    r'\.dll$',
    r'\.exe$',
    r'\.dylib$',
    r'\.lock$',
    r'-lock\.json$',
    r'\.log$',
    r'\.tmp$',
    r'\.temp$',
    r'\.swp$',
    r'\.swo$',
    r'~$',
    r'^\.#',
    r'#.*#$',
}

# Compiled regex patterns for file matching
_IGNORED_FILE_REGEXES = [re.compile(p) for p in IGNORED_FILE_PATTERNS]


def should_ignore_path(path: str) -> bool:
    """
    Check if a file path should be ignored for indexing.

    Args:
        path: File path to check

    Returns:
        True if the path should be ignored, False otherwise
    """
    # Normalize path separators
    normalized = path.replace('\\', '/')

    # Check each path component against ignored directories
    parts = normalized.split('/')
    for part in parts:
        if part in IGNORED_DIRECTORIES:
            return True

    # Check filename against ignored patterns
    filename = parts[-1] if parts else ''
    for regex in _IGNORED_FILE_REGEXES:
        if regex.search(filename):
            return True

    return False


class BackgroundProcessor:
    """
    Background worker for knowledge extraction.

    Processes files from the queue asynchronously:
    1. Extract text content
    2. Extract entities
    3. Generate embeddings
    4. Store in knowledge graph
    """

    def __init__(self, knowledge_graph: KnowledgeGraph,
                 content_extractor: Optional[ContentExtractor] = None,
                 entity_extractor: Optional[EntityExtractor] = None,
                 embedding_generator: Optional[EmbeddingGenerator] = None,
                 poll_interval: float = 1.0):
        """
        Initialize background processor.

        Args:
            knowledge_graph: KnowledgeGraph instance
            content_extractor: Optional ContentExtractor (created if not provided)
            entity_extractor: Optional EntityExtractor (created if not provided)
            embedding_generator: Optional EmbeddingGenerator (created if not provided)
            poll_interval: Seconds between queue polls
        """
        self.kg = knowledge_graph
        self.content_extractor = content_extractor or ContentExtractor()
        self.entity_extractor = entity_extractor or EntityExtractor()
        self.embedding_generator = embedding_generator or EmbeddingGenerator()
        self.poll_interval = poll_interval
        self.relationship_detector = RelationshipDetector(knowledge_graph)

        self.running = False
        self.thread: Optional[threading.Thread] = None

        # Internal queue for immediate processing
        self._internal_queue: Queue = Queue()

        # Callbacks
        self._on_file_processed: Optional[Callable[[str, bool], Any]] = None

    def start(self):
        """Start background processing thread."""
        if self.running:
            logger.warning("Processor already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        logger.info("Background processor started")

    def stop(self, timeout: float = 5.0):
        """
        Stop background processing.

        Args:
            timeout: Seconds to wait for thread to finish
        """
        if not self.running:
            return

        self.running = False

        # Signal thread to wake up
        self._internal_queue.put(None)

        if self.thread:
            self.thread.join(timeout=timeout)
            if self.thread.is_alive():
                logger.warning("Processor thread did not stop cleanly")
            self.thread = None

        logger.info("Background processor stopped")

    def queue_file(self, path: str, inode_num: int, data: bytes):
        """
        Queue file for processing.

        This is called from FUSE operations when a file is written.
        The file is added to both the internal queue (for immediate processing)
        and the database queue (for persistence).

        Files in ignored directories (.git, node_modules, etc.) or matching
        ignored patterns (.pyc, .log, etc.) are skipped.

        Args:
            path: File path
            inode_num: Inode number
            data: File content
        """
        # Skip ignored files (version control, build artifacts, etc.)
        if should_ignore_path(path):
            logger.debug(f"Skipping ignored file: {path}")
            return

        logger.debug(f"Queuing file for processing: {path}")

        # Add to internal queue for immediate processing
        self._internal_queue.put({
            'path': path,
            'inode_num': inode_num,
            'data': data,
        })

    def set_callback(self, on_file_processed: Callable[[str, bool], Any]):
        """Set callback for when a file is processed."""
        self._on_file_processed = on_file_processed

    def _worker_loop(self):
        """Main worker loop - process queue items."""
        logger.info("Worker loop started")

        while self.running:
            try:
                # Check internal queue first (new files)
                try:
                    item = self._internal_queue.get(timeout=self.poll_interval)
                    if item is None:
                        # Shutdown signal
                        continue
                    self._process_queued_item(item)
                except Empty:
                    pass

                # Check database queue for pending operations
                self._process_database_queue()

                # Retry files missing embeddings (BUG-013 fix)
                self._retry_missing_embeddings()

            except Exception as e:
                logger.error(f"Error in worker loop: {e}", exc_info=True)
                time.sleep(self.poll_interval)

        logger.info("Worker loop stopped")

    def _process_queued_item(self, item: dict):
        """Process a file from the internal queue."""
        path = item['path']
        inode_num = item['inode_num']
        data = item['data']

        logger.info(f"Processing file: {path}")
        success = False

        try:
            # Extract content and entities
            result = extract_all(path, data)

            if not result.text:
                logger.debug(f"No text content extracted from {path}")
                success = True  # Not an error, just no text
                return

            # Get or create file record
            file_record = self.kg.get_file(path)
            if not file_record:
                # Create new file record
                file_record = FileRecord(
                    inode_num=inode_num,
                    path=path,
                    content_hash=result.content_hash,
                    size=len(data),
                    mime_type=result.mime_type,
                    created_at=time.time(),
                    modified_at=time.time(),
                    extracted_text=result.text[:10000],  # Limit stored text
                    metadata=result.metadata
                )
                file_id = self.kg.add_file(file_record)
            else:
                # Update existing record
                file_id = file_record.id
                self.kg.update_file_extraction(
                    file_id,
                    extracted_text=result.text[:10000],
                    content_hash=result.content_hash
                )

            # Process entities
            self._process_entities(file_id, result.entities)

            # Detect relationships between entities in this file
            relationships = self._detect_relationships(file_id)

            # Generate embedding
            self._generate_embedding(file_id, result.text)

            success = True
            logger.info(f"Successfully processed {path}: "
                       f"{len(result.entities)} entities, "
                       f"{relationships} relationships, "
                       f"{len(result.keywords)} keywords")

        except Exception as e:
            logger.error(f"Failed to process {path}: {e}", exc_info=True)
            success = False

        finally:
            if self._on_file_processed:
                try:
                    self._on_file_processed(path, success)
                except:
                    pass

    def _process_entities(self, file_id: int, entities: list):
        """Extract and store entities from extraction result."""
        for extracted in entities:
            # Map entity type
            kg_type = ENTITY_TYPE_MAP.get(
                extracted.entity_type,
                EntityType.CONCEPT
            )

            # Create entity
            entity = Entity(
                entity_type=kg_type,
                name=extracted.value,
                confidence=extracted.confidence,
            )

            # Add to knowledge graph
            entity_id = self.kg.add_entity(entity)

            # Link file to entity
            if entity_id:
                self.kg.link_file_entity(
                    file_id=file_id,
                    entity_id=entity_id,
                    relation_type='contains',
                    confidence=extracted.confidence,
                    context=extracted.context[:200]  # Limit context
                )

    def _detect_relationships(self, file_id: int) -> int:
        """
        Detect relationships between entities in the file.

        Creates RELATED_TO relationships between entities that
        co-occur in the same file.

        Args:
            file_id: ID of the file to process

        Returns:
            Number of relationships created
        """
        try:
            relationships = self.relationship_detector.detect_for_file(file_id)
            for rel in relationships:
                self.relationship_detector._save_relationship(rel)
            return len(relationships)
        except Exception as e:
            logger.debug(f"Relationship detection failed: {e}")
            return 0

    def _generate_embedding(self, file_id: int, text: str):
        """Generate and store embedding for file."""
        if not self.embedding_generator.is_available:
            logger.debug("Embedding generator not available")
            return

        # Generate embedding
        vector = self.embedding_generator.generate(text)
        if not vector:
            return

        # Store embedding
        embedding = Embedding(
            file_id=file_id,
            model=self.embedding_generator.model_name if hasattr(
                self.embedding_generator, 'model_name'
            ) else 'unknown',
            dimensions=len(vector) // 4,  # float32 = 4 bytes
            vector=vector
        )

        embedding_id = self.kg.add_embedding(embedding)

        # Link to file
        if embedding_id:
            self.kg.set_file_embedding(file_id, embedding_id)

    def _process_database_queue(self):
        """Process pending items from database queue."""
        # Get pending operations
        pending = self.kg.get_pending_operations(limit=5)

        for item in pending:
            queue_id = item['id']
            file_id = item['file_id']
            operation = item['operation']

            try:
                # Mark as processing
                self.kg.mark_operation_processing(queue_id)

                # Get file record
                file_record = self.kg.get_file_by_id(file_id) if file_id else None

                if operation == 'embed' and file_record:
                    # Re-generate embedding
                    if file_record.extracted_text:
                        self._generate_embedding(file_id, file_record.extracted_text)

                # Mark completed
                self.kg.mark_operation_completed(queue_id)

            except Exception as e:
                logger.error(f"Failed to process queue item {queue_id}: {e}")
                self.kg.mark_operation_failed(queue_id, str(e))

    def _retry_missing_embeddings(self):
        """Retry embedding generation for files that were skipped (BUG-013 fix)."""
        if not self.embedding_generator.is_available:
            return

        cursor = self.kg.conn.cursor()
        cursor.execute("""
            SELECT id, extracted_text FROM files
            WHERE embedding_id IS NULL
            AND extracted_text IS NOT NULL
            AND extracted_text != ''
            LIMIT 5
        """)

        for row in cursor.fetchall():
            file_id = row['id']
            text = row['extracted_text']
            logger.debug(f"Retrying embedding for file_id={file_id}")
            self._generate_embedding(file_id, text)

    def get_stats(self) -> dict:
        """Get processor statistics."""
        return {
            'running': self.running,
            'internal_queue_size': self._internal_queue.qsize(),
            'embedding_available': self.embedding_generator.is_available,
            'queue_stats': self.kg.get_queue_stats() if self.kg else {}
        }


class SyncProcessor:
    """
    Synchronous processor for testing without threading.

    Processes files immediately instead of in background.
    """

    def __init__(self, knowledge_graph: KnowledgeGraph,
                 content_extractor: Optional[ContentExtractor] = None,
                 entity_extractor: Optional[EntityExtractor] = None,
                 embedding_generator: Optional[EmbeddingGenerator] = None):
        """Initialize synchronous processor."""
        self._processor = BackgroundProcessor(
            knowledge_graph,
            content_extractor,
            entity_extractor,
            embedding_generator
        )

    def process_file(self, path: str, inode_num: int, data: bytes):
        """Process file synchronously."""
        item = {
            'path': path,
            'inode_num': inode_num,
            'data': data,
        }
        self._processor._process_queued_item(item)

    def start(self):
        """No-op for sync processor."""
        pass

    def stop(self):
        """No-op for sync processor."""
        pass

    def queue_file(self, path: str, inode_num: int, data: bytes):
        """Process file immediately (skip ignored files)."""
        if should_ignore_path(path):
            return
        self.process_file(path, inode_num, data)
