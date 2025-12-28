"""Unit tests for Extractor module."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cognitivefs.extractor import (
    ContentExtractor, EntityExtractor, ExtractedEntity, ExtractedEntityType,
    extract_all
)


class TestContentExtractor(unittest.TestCase):
    """Test ContentExtractor class."""

    def setUp(self):
        self.extractor = ContentExtractor()

    def test_extract_text_from_plain(self):
        """Test extracting text from plain text."""
        content = b"Hello, this is plain text content."
        result = self.extractor.extract("/test.txt", content)

        self.assertIsNotNone(result)
        self.assertEqual(result.text, "Hello, this is plain text content.")

    def test_extract_text_from_markdown(self):
        """Test extracting text from markdown."""
        content = b"# Header\n\nThis is **bold** text."
        result = self.extractor.extract("/test.md", content)

        self.assertIsNotNone(result)
        self.assertIn("Header", result.text)
        self.assertIn("bold", result.text)

    def test_extract_generates_hash(self):
        """Test content hash generation."""
        content = b"Test content for hashing."
        result = self.extractor.extract("/test.txt", content)

        self.assertIsNotNone(result.content_hash)
        self.assertEqual(len(result.content_hash), 64)  # SHA-256 hex

    def test_extract_empty_content(self):
        """Test extracting from empty content."""
        result = self.extractor.extract("/empty.txt", b"")
        self.assertIsNotNone(result)
        self.assertEqual(result.text, "")

    def test_extract_binary_content(self):
        """Test extracting from binary content."""
        content = b"\x00\x01\x02\x03\xff\xfe"
        result = self.extractor.extract("/binary.bin", content)
        self.assertIsNotNone(result)

    def test_extract_detects_mime_type(self):
        """Test MIME type detection."""
        result = self.extractor.extract("/test.py", b"print('hello')")
        self.assertEqual(result.mime_type, "text/x-python")

        result = self.extractor.extract("/test.json", b'{"key": "value"}')
        self.assertEqual(result.mime_type, "application/json")


class TestEntityExtractor(unittest.TestCase):
    """Test EntityExtractor class."""

    def setUp(self):
        self.extractor = EntityExtractor()

    def test_extract_person_names(self):
        """Test extracting person names."""
        text = "John Smith and Mary Johnson attended the meeting."
        entities = self.extractor.extract_entities(text)

        names = [e.value for e in entities if e.entity_type == ExtractedEntityType.PERSON]
        self.assertIn("John Smith", names)
        self.assertIn("Mary Johnson", names)

    def test_extract_dates(self):
        """Test extracting dates."""
        text = "The event is scheduled for 2025-01-15."
        entities = self.extractor.extract_entities(text)

        dates = [e.value for e in entities if e.entity_type == ExtractedEntityType.DATE]
        self.assertIn("2025-01-15", dates)

    def test_extract_hashtags(self):
        """Test extracting hashtags."""
        text = "Check out #MachineLearning and #AI trends."
        entities = self.extractor.extract_entities(text)

        tags = [e.value for e in entities if e.entity_type == ExtractedEntityType.HASHTAG]
        self.assertIn("#MachineLearning", tags)
        self.assertIn("#AI", tags)

    def test_extract_urls(self):
        """Test extracting URLs."""
        text = "Visit https://example.com for more info."
        entities = self.extractor.extract_entities(text)

        urls = [e.value for e in entities if e.entity_type == ExtractedEntityType.URL]
        self.assertTrue(any("example.com" in u for u in urls))

    def test_extract_file_paths(self):
        """Test extracting file paths."""
        text = "Edit the file at /home/user/config.json"
        entities = self.extractor.extract_entities(text)

        files = [e.value for e in entities if e.entity_type == ExtractedEntityType.FILE_PATH]
        self.assertTrue(any("config.json" in f for f in files))

    def test_extract_emails(self):
        """Test extracting email addresses."""
        text = "Contact us at support@example.com for help."
        entities = self.extractor.extract_entities(text)

        emails = [e.value for e in entities if e.entity_type == ExtractedEntityType.EMAIL]
        self.assertIn("support@example.com", emails)

    def test_entity_has_confidence(self):
        """Test entities have confidence scores."""
        text = "John Doe works at Acme Corp."
        entities = self.extractor.extract_entities(text)

        for entity in entities:
            self.assertIsInstance(entity.confidence, float)
            self.assertGreaterEqual(entity.confidence, 0.0)
            self.assertLessEqual(entity.confidence, 1.0)

    def test_entity_has_context(self):
        """Test entities have context."""
        text = "John Doe is the CEO of the company."
        entities = self.extractor.extract_entities(text)

        for entity in entities:
            self.assertIsNotNone(entity.context)

    def test_extract_empty_text(self):
        """Test extracting from empty text."""
        entities = self.extractor.extract_entities("")
        self.assertEqual(len(entities), 0)

    def test_extract_keywords(self):
        """Test keyword extraction."""
        text = "Python programming language is great for machine learning."
        keywords = self.extractor.extract_keywords(text)

        self.assertIsInstance(keywords, list)
        keywords_lower = [k.lower() for k in keywords]
        self.assertTrue(
            any(kw in keywords_lower for kw in ['python', 'programming', 'machine', 'learning'])
        )


class TestExtractAll(unittest.TestCase):
    """Test extract_all combined function."""

    def test_extract_all_returns_result(self):
        """Test extract_all returns combined result."""
        content = b"John Smith wrote about #AI on 2025-01-01."
        result = extract_all("/test.txt", content)

        self.assertIsNotNone(result)
        self.assertIsNotNone(result.text)
        self.assertIsNotNone(result.entities)
        self.assertIsNotNone(result.keywords)
        self.assertIsNotNone(result.content_hash)

    def test_extract_all_finds_entities(self):
        """Test extract_all finds entities in content."""
        content = b"Meeting with Alice Brown on 2025-03-15 about #ProjectX."
        result = extract_all("/test.txt", content)

        entity_values = [e.value for e in result.entities]
        self.assertTrue(len(entity_values) > 0)


class TestStructuredExtraction(unittest.TestCase):
    """Test structured file extraction (JSON, YAML, CSV)."""

    def setUp(self):
        self.extractor = ContentExtractor()

    def test_json_key_extraction(self):
        """Test extracting keys from JSON as FIELD entities."""
        json_data = b'{"name": "Alice", "age": 30}'
        entities = self.extractor.extract_json_entities(json_data)

        field_values = [e.value for e in entities if e.entity_type == ExtractedEntityType.FIELD]
        self.assertIn("name", field_values)
        self.assertIn("age", field_values)

    def test_json_nested_paths(self):
        """Test JSONPath context for nested keys."""
        json_data = b'{"user": {"address": {"city": "NYC"}}}'
        entities = self.extractor.extract_json_entities(json_data)

        # Find the city field
        city_entities = [e for e in entities
                        if e.entity_type == ExtractedEntityType.FIELD and e.value == "city"]
        self.assertEqual(len(city_entities), 1)
        self.assertEqual(city_entities[0].context, "user.address.city")

    def test_json_value_types(self):
        """Test SCHEMA_TYPE extraction for different value types."""
        json_data = b'{"name": "test", "count": 42, "active": true, "items": []}'
        entities = self.extractor.extract_json_entities(json_data)

        schema_types = {e.context: e.value for e in entities
                       if e.entity_type == ExtractedEntityType.SCHEMA_TYPE}

        self.assertEqual(schema_types.get("name"), "string")
        self.assertEqual(schema_types.get("count"), "number")
        self.assertEqual(schema_types.get("active"), "boolean")
        self.assertEqual(schema_types.get("items"), "array")

    def test_json_array_traversal(self):
        """Test traversing arrays in JSON."""
        json_data = b'{"users": [{"name": "Alice"}, {"name": "Bob"}]}'
        entities = self.extractor.extract_json_entities(json_data)

        # Should find name fields in both array elements
        name_contexts = [e.context for e in entities
                        if e.entity_type == ExtractedEntityType.FIELD and e.value == "name"]
        self.assertIn("users[0].name", name_contexts)
        self.assertIn("users[1].name", name_contexts)

    def test_invalid_json_fallback(self):
        """Test graceful handling of invalid JSON."""
        invalid_json = b'{invalid json here'
        entities = self.extractor.extract_json_entities(invalid_json)
        self.assertEqual(entities, [])

    def test_csv_header_extraction(self):
        """Test extracting CSV headers as COLUMN entities."""
        csv_data = b"name,age,city\nAlice,30,NYC\nBob,25,LA"
        entities = self.extractor.extract_csv_entities(csv_data)

        columns = [e.value for e in entities if e.entity_type == ExtractedEntityType.COLUMN]
        self.assertIn("name", columns)
        self.assertIn("age", columns)
        self.assertIn("city", columns)

    def test_csv_column_context(self):
        """Test CSV column index in context."""
        csv_data = b"id,name,value\n1,test,100"
        entities = self.extractor.extract_csv_entities(csv_data)

        id_entity = [e for e in entities if e.value == "id"][0]
        self.assertEqual(id_entity.context, "column[0]")

    def test_extract_all_json(self):
        """Test extract_all includes JSON field entities."""
        json_data = b'{"project": "CognitiveFS", "version": "1.0"}'
        result = extract_all("/config.json", json_data)

        # Should have FIELD entities
        field_values = [e.value for e in result.entities
                       if e.entity_type == ExtractedEntityType.FIELD]
        self.assertIn("project", field_values)
        self.assertIn("version", field_values)

        # Text should be formatted
        self.assertIn('"project"', result.text)

    def test_extract_all_csv(self):
        """Test extract_all includes CSV column entities."""
        csv_data = b"user_id,username,email\n1,alice,alice@test.com"
        result = extract_all("/users.csv", csv_data)

        column_values = [e.value for e in result.entities
                        if e.entity_type == ExtractedEntityType.COLUMN]
        self.assertIn("user_id", column_values)
        self.assertIn("username", column_values)


if __name__ == '__main__':
    unittest.main()
