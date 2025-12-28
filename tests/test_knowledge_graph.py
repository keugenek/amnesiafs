"""Unit tests for Knowledge Graph module."""

import os
import sys
import time
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cognitivefs.knowledge_graph import (
    KnowledgeGraph, Entity, EntityType, FileRecord, Embedding, RelationType
)


class TestKnowledgeGraph(unittest.TestCase):
    """Test KnowledgeGraph basic operations."""

    def setUp(self):
        """Create temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.kg.db")
        self.kg = KnowledgeGraph(self.db_path)
        self.kg.open()

    def tearDown(self):
        """Clean up temporary database."""
        self.kg.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.temp_dir)

    def test_create_database(self):
        """Test database creation."""
        self.assertTrue(os.path.exists(self.db_path))
        stats = self.kg.get_stats()
        self.assertEqual(stats['files_indexed'], 0)
        self.assertEqual(stats['entities'], 0)

    def test_add_file(self):
        """Test adding a file record."""
        now = time.time()
        file_record = FileRecord(
            inode_num=12345,
            path="/test/file.txt",
            mime_type="text/plain",
            created_at=now,
            modified_at=now
        )
        file_id = self.kg.add_file(file_record)
        self.assertIsNotNone(file_id)
        self.assertGreater(file_id, 0)

        # Retrieve file
        record = self.kg.get_file("/test/file.txt")
        self.assertIsNotNone(record)
        self.assertEqual(record.path, "/test/file.txt")
        self.assertEqual(record.mime_type, "text/plain")

    def test_add_entity(self):
        """Test adding an entity."""
        entity = Entity(
            entity_type=EntityType.PERSON,
            name="John Doe",
            description="Test person"
        )
        entity_id = self.kg.add_entity(entity)
        self.assertIsNotNone(entity_id)
        self.assertGreater(entity_id, 0)

        # Retrieve entity
        retrieved = self.kg.get_entity(EntityType.PERSON, "John Doe")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "John Doe")

    def test_entity_upsert(self):
        """Test entity upsert updates existing."""
        entity1 = Entity(entity_type=EntityType.CONCEPT, name="Machine Learning")
        id1 = self.kg.add_entity(entity1)

        entity2 = Entity(entity_type=EntityType.CONCEPT, name="machine learning")
        id2 = self.kg.add_entity(entity2)

        # Should return same ID (upsert)
        self.assertEqual(id1, id2)

        # Source count should be incremented
        retrieved = self.kg.get_entity(EntityType.CONCEPT, "Machine Learning")
        self.assertEqual(retrieved.source_count, 2)

    def test_link_file_entity(self):
        """Test linking file to entity."""
        now = time.time()
        file_record = FileRecord(
            inode_num=1001,
            path="/doc.txt",
            mime_type="text/plain",
            created_at=now,
            modified_at=now
        )
        file_id = self.kg.add_file(file_record)

        entity = Entity(entity_type=EntityType.PERSON, name="Jane")
        entity_id = self.kg.add_entity(entity)

        self.kg.link_file_entity(file_id, entity_id, "mentions", 0.9, "context")

        # Get file entities
        entities = self.kg.get_file_entities(file_id)
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0][0].name, "Jane")

    def test_add_relationship(self):
        """Test adding relationship between entities."""
        e1 = Entity(entity_type=EntityType.PERSON, name="Alice")
        e2 = Entity(entity_type=EntityType.PERSON, name="Bob")
        id1 = self.kg.add_entity(e1)
        id2 = self.kg.add_entity(e2)

        self.kg.add_relationship(id1, id2, RelationType.RELATED_TO, 0.8)

        # Get relationships
        rels = self.kg.get_relationships(id1)
        self.assertGreaterEqual(len(rels), 1)

    def test_add_embedding(self):
        """Test storing embeddings."""
        now = time.time()
        file_record = FileRecord(
            inode_num=2001,
            path="/embed.txt",
            mime_type="text/plain",
            created_at=now,
            modified_at=now
        )
        file_id = self.kg.add_file(file_record)
        vector = b'\x00' * 384 * 4  # 384 floats

        embedding = Embedding(
            file_id=file_id,
            model="test-model",
            dimensions=384,
            vector=vector
        )
        emb_id = self.kg.add_embedding(embedding)
        self.assertIsNotNone(emb_id)

        # Retrieve embedding
        emb = self.kg.get_embedding(file_id=file_id)
        self.assertIsNotNone(emb)
        self.assertEqual(emb.model, "test-model")

    def test_search_entities(self):
        """Test entity search."""
        self.kg.add_entity(Entity(entity_type=EntityType.CONCEPT, name="Neural Networks"))
        self.kg.add_entity(Entity(entity_type=EntityType.CONCEPT, name="Deep Learning"))
        self.kg.add_entity(Entity(entity_type=EntityType.PERSON, name="Network Admin"))

        results = self.kg.search_entities("network", limit=10)
        self.assertGreaterEqual(len(results), 1)

    def test_get_stats(self):
        """Test statistics retrieval."""
        now = time.time()
        self.kg.add_file(FileRecord(inode_num=3001, path="/f1.txt", mime_type="text/plain", created_at=now, modified_at=now))
        self.kg.add_file(FileRecord(inode_num=3002, path="/f2.txt", mime_type="text/plain", created_at=now, modified_at=now))
        self.kg.add_entity(Entity(entity_type=EntityType.PERSON, name="Test"))

        stats = self.kg.get_stats()
        self.assertEqual(stats['files_indexed'], 2)
        self.assertEqual(stats['entities'], 1)


class TestEntityTypes(unittest.TestCase):
    """Test EntityType enum."""

    def test_all_types_exist(self):
        """Verify all expected entity types."""
        expected = ['person', 'organization', 'location', 'concept',
                   'date', 'file', 'tag', 'topic']
        for name in expected:
            self.assertTrue(hasattr(EntityType, name.upper()))


if __name__ == '__main__':
    unittest.main()
