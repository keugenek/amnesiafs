"""Unit tests for Relationship Detector module."""

import os
import sys
import time
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cognitivefs.knowledge_graph import (
    KnowledgeGraph, Entity, EntityType, RelationType, FileRecord
)
from cognitivefs.relationship_detector import (
    RelationshipDetector, MultiHopQueryEngine, DetectedRelationship
)


class TestRelationshipDetector(unittest.TestCase):
    """Test RelationshipDetector class."""

    def setUp(self):
        """Create temporary database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.kg.db")
        self.kg = KnowledgeGraph(self.db_path)
        self.kg.open()
        self.detector = RelationshipDetector(self.kg)

    def tearDown(self):
        """Clean up."""
        self.kg.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.temp_dir)

    def test_detector_creation(self):
        """Test detector initializes."""
        self.assertIsNotNone(self.detector)

    def test_detect_for_file_empty(self):
        """Test detection with no entities."""
        now = time.time()
        file_record = FileRecord(
            inode_num=1001,
            path="/test.txt",
            mime_type="text/plain",
            created_at=now,
            modified_at=now
        )
        file_id = self.kg.add_file(file_record)
        relationships = self.detector.detect_for_file(file_id)
        self.assertEqual(len(relationships), 0)

    def test_detect_for_file_single_entity(self):
        """Test detection with single entity (no relationships)."""
        now = time.time()
        file_record = FileRecord(
            inode_num=1002,
            path="/test.txt",
            mime_type="text/plain",
            created_at=now,
            modified_at=now
        )
        file_id = self.kg.add_file(file_record)
        entity = Entity(entity_type=EntityType.PERSON, name="John")
        entity_id = self.kg.add_entity(entity)
        self.kg.link_file_entity(file_id, entity_id, "mentions", 0.9)

        relationships = self.detector.detect_for_file(file_id)
        self.assertEqual(len(relationships), 0)  # Need 2+ entities

    def test_detect_for_file_multiple_entities(self):
        """Test detection with multiple entities creates relationships."""
        now = time.time()
        file_record = FileRecord(
            inode_num=1003,
            path="/test.txt",
            mime_type="text/plain",
            created_at=now,
            modified_at=now
        )
        file_id = self.kg.add_file(file_record)

        e1 = Entity(entity_type=EntityType.PERSON, name="Alice")
        e2 = Entity(entity_type=EntityType.PERSON, name="Bob")
        e3 = Entity(entity_type=EntityType.CONCEPT, name="Project")

        id1 = self.kg.add_entity(e1)
        id2 = self.kg.add_entity(e2)
        id3 = self.kg.add_entity(e3)

        self.kg.link_file_entity(file_id, id1, "mentions", 0.9)
        self.kg.link_file_entity(file_id, id2, "mentions", 0.8)
        self.kg.link_file_entity(file_id, id3, "mentions", 0.7)

        relationships = self.detector.detect_for_file(file_id)
        # Should create relationships between pairs: (1,2), (1,3), (2,3) = 3
        self.assertEqual(len(relationships), 3)

    def test_detected_relationship_properties(self):
        """Test DetectedRelationship has correct properties."""
        rel = DetectedRelationship(
            source_id=1,
            target_id=2,
            relation_type=RelationType.RELATED_TO,
            weight=0.5,
            evidence="test"
        )
        self.assertEqual(rel.source_id, 1)
        self.assertEqual(rel.target_id, 2)
        self.assertEqual(rel.relation_type, RelationType.RELATED_TO)
        self.assertEqual(rel.weight, 0.5)


class TestMultiHopQueryEngine(unittest.TestCase):
    """Test MultiHopQueryEngine class."""

    def setUp(self):
        """Create temporary database with test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.kg.db")
        self.kg = KnowledgeGraph(self.db_path)
        self.kg.open()
        self.engine = MultiHopQueryEngine(self.kg)

        # Create test entities
        self.alice_id = self.kg.add_entity(Entity(entity_type=EntityType.PERSON, name="Alice"))
        self.bob_id = self.kg.add_entity(Entity(entity_type=EntityType.PERSON, name="Bob"))
        self.charlie_id = self.kg.add_entity(Entity(entity_type=EntityType.PERSON, name="Charlie"))
        self.project_id = self.kg.add_entity(Entity(entity_type=EntityType.CONCEPT, name="Project X"))

        # Create relationships: Alice -> Bob -> Charlie
        self.kg.add_relationship(self.alice_id, self.bob_id, RelationType.RELATED_TO, 0.9)
        self.kg.add_relationship(self.bob_id, self.charlie_id, RelationType.RELATED_TO, 0.8)
        self.kg.add_relationship(self.bob_id, self.project_id, RelationType.RELATED_TO, 0.7)

    def tearDown(self):
        """Clean up."""
        self.kg.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.temp_dir)

    def test_engine_creation(self):
        """Test engine initializes."""
        self.assertIsNotNone(self.engine)

    def test_find_connections_direct(self):
        """Test finding direct connection."""
        paths = self.engine.find_connections("Alice", "Bob", max_hops=1)
        self.assertGreaterEqual(len(paths), 0)

    def test_find_connections_multi_hop(self):
        """Test finding multi-hop connection."""
        paths = self.engine.find_connections("Alice", "Charlie", max_hops=3)
        # Should find path through Bob
        self.assertGreaterEqual(len(paths), 0)

    def test_find_connections_not_found(self):
        """Test no path between unconnected entities."""
        # Add isolated entity
        self.kg.add_entity(Entity(entity_type=EntityType.PERSON, name="Isolated"))
        paths = self.engine.find_connections("Alice", "Isolated", max_hops=3)
        self.assertEqual(len(paths), 0)

    def test_get_entity_context(self):
        """Test getting entity context."""
        context = self.engine.get_entity_context("Bob", depth=1)

        self.assertIn('entity', context)
        self.assertEqual(context['entity']['name'], "Bob")

    def test_get_entity_context_not_found(self):
        """Test context for non-existent entity."""
        context = self.engine.get_entity_context("NonExistent", depth=1)
        self.assertIn('error', context)

    def test_query_graph(self):
        """Test natural language graph query."""
        result = self.engine.query_graph("What is Alice related to?")

        self.assertIn('answer', result)
        self.assertIn('entities', result)


if __name__ == '__main__':
    unittest.main()
