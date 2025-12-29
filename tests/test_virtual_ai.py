"""Unit tests for Virtual AI module."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cognitivefs.virtual_ai import VirtualAIHandler, VirtualNodeType


class TestVirtualAIHandler(unittest.TestCase):
    """Test VirtualAIHandler class."""

    def setUp(self):
        """Create handler."""
        self.handler = VirtualAIHandler()

    def test_handler_creation(self):
        """Test handler initializes."""
        self.assertIsNotNone(self.handler)

    def test_is_ai_path_root(self):
        """Test AI path detection for root."""
        self.assertTrue(self.handler.is_ai_path("/.ai"))
        self.assertTrue(self.handler.is_ai_path("/.ai/"))

    def test_is_ai_path_subdir(self):
        """Test AI path detection for subdirs."""
        self.assertTrue(self.handler.is_ai_path("/.ai/query"))
        self.assertTrue(self.handler.is_ai_path("/.ai/status"))
        self.assertTrue(self.handler.is_ai_path("/.ai/graph/entities"))

    def test_is_ai_path_negative(self):
        """Test non-AI paths."""
        self.assertFalse(self.handler.is_ai_path("/"))
        self.assertFalse(self.handler.is_ai_path("/home"))
        self.assertFalse(self.handler.is_ai_path("/ai"))  # No dot
        self.assertFalse(self.handler.is_ai_path("/.ai_other"))

    def test_parse_ai_path_root(self):
        """Test parsing AI root path."""
        subdir, target, parts = self.handler.parse_ai_path("/.ai")
        self.assertEqual(subdir, "")
        self.assertEqual(target, "")

    def test_parse_ai_path_subdir(self):
        """Test parsing AI subdir path."""
        subdir, target, parts = self.handler.parse_ai_path("/.ai/query")
        self.assertEqual(subdir, "query")
        self.assertEqual(target, "")
        self.assertEqual(parts, ["query"])

    def test_parse_ai_path_with_target(self):
        """Test parsing AI path with target."""
        subdir, target, parts = self.handler.parse_ai_path("/.ai/summary/docs/file.txt")
        self.assertEqual(subdir, "summary")
        self.assertEqual(target, "/docs/file.txt")
        self.assertEqual(parts, ["summary", "docs", "file.txt"])

    def test_parse_ai_path_non_ai(self):
        """Test parsing non-AI path."""
        subdir, target, parts = self.handler.parse_ai_path("/home/user")
        self.assertIsNone(subdir)
        self.assertIsNone(target)
        self.assertEqual(parts, [])

    def test_getattr_root(self):
        """Test getattr for AI root."""
        attrs = self.handler.getattr("/.ai")
        self.assertIsNotNone(attrs)
        self.assertIn('st_mode', attrs)
        # Should be directory
        import stat
        self.assertTrue(stat.S_ISDIR(attrs['st_mode']))

    def test_getattr_status(self):
        """Test getattr for status directory."""
        attrs = self.handler.getattr("/.ai/status")
        self.assertIsNotNone(attrs)
        import stat
        self.assertTrue(stat.S_ISDIR(attrs['st_mode']))

    def test_getattr_status_index(self):
        """Test getattr for status/index file."""
        attrs = self.handler.getattr("/.ai/status/index")
        self.assertIsNotNone(attrs)
        import stat
        self.assertTrue(stat.S_ISREG(attrs['st_mode']))

    def test_getattr_subdirs(self):
        """Test getattr for subdirectories."""
        # Only test implemented subdirs (summary, related, chat are not yet extracted)
        for subdir in ["query", "graph", "status", "search", "versions", "entities", "similar", "by-topic"]:
            attrs = self.handler.getattr(f"/.ai/{subdir}")
            self.assertIsNotNone(attrs, f"/.ai/{subdir} should exist")

    def test_readdir_root(self):
        """Test readdir for AI root."""
        entries = self.handler.readdir("/.ai")
        self.assertIsInstance(entries, list)
        self.assertIn("query", entries)
        self.assertIn("status", entries)
        self.assertIn("graph", entries)

    def test_readdir_query(self):
        """Test readdir for query dir."""
        entries = self.handler.readdir("/.ai/query")
        self.assertIsInstance(entries, list)
        self.assertIn("_help.txt", entries)

    def test_readdir_graph(self):
        """Test readdir for graph dir."""
        entries = self.handler.readdir("/.ai/graph")
        self.assertIsInstance(entries, list)
        self.assertIn("entities", entries)
        self.assertIn("stats", entries)


class TestVirtualAIStatus(unittest.TestCase):
    """Test status endpoint."""

    def setUp(self):
        self.handler = VirtualAIHandler()

    def test_status_content(self):
        """Test status returns valid JSON."""
        import json
        content = self.handler.read("/.ai/status", 10000, 0)
        self.assertIsInstance(content, bytes)

        data = json.loads(content.decode('utf-8'))
        self.assertIn('filesystem', data)
        self.assertEqual(data['filesystem'], 'CognitiveFS')

    def test_status_index_content(self):
        """Test status/index returns markdown."""
        content = self.handler.read("/.ai/status/index", 10000, 0)
        self.assertIsInstance(content, bytes)
        text = content.decode('utf-8')
        self.assertIn('# Index Status', text)
        self.assertIn('Knowledge graph not initialized', text)


class TestVirtualAIQuery(unittest.TestCase):
    """Test query endpoint."""

    def setUp(self):
        self.handler = VirtualAIHandler()

    def test_query_help(self):
        """Test query help file."""
        content = self.handler.read("/.ai/query/_help.txt", 10000, 0)
        self.assertIsInstance(content, bytes)
        self.assertIn(b"Query", content)

    def test_query_returns_id(self):
        """Test query returns query ID."""
        content = self.handler.read("/.ai/query/test_question", 10000, 0)
        text = content.decode('utf-8')
        self.assertIn("queued", text.lower())

    def test_query_pending(self):
        """Test listing pending queries."""
        # First submit a query
        self.handler.read("/.ai/query/test", 1000, 0)

        # Then check pending
        content = self.handler.read("/.ai/query/pending", 10000, 0)
        text = content.decode('utf-8')
        self.assertIn("Query Queue", text)


class TestVirtualAIGraph(unittest.TestCase):
    """Test graph endpoints."""

    def setUp(self):
        self.handler = VirtualAIHandler()

    def test_graph_stats_no_kg(self):
        """Test graph stats without knowledge graph."""
        content = self.handler.read("/.ai/graph/stats", 10000, 0)
        self.assertIsInstance(content, bytes)
        # Should return not_initialized status
        self.assertIn(b"not_initialized", content)

    def test_graph_help(self):
        """Test graph help."""
        attrs = self.handler.getattr("/.ai/graph/_help.txt")
        # May or may not exist depending on implementation
        # Just verify no crash


class TestAsyncQuerySystem(unittest.TestCase):
    """Test async query infrastructure."""

    def setUp(self):
        self.handler = VirtualAIHandler()

    def test_query_counter_increments(self):
        """Test query IDs increment."""
        # Access via the query handler
        initial = self.handler.query._query_counter

        self.handler.read("/.ai/query/test1", 1000, 0)
        self.handler.read("/.ai/query/test2", 1000, 0)

        self.assertEqual(self.handler.query._query_counter, initial + 2)

    def test_query_results_stored(self):
        """Test query results are stored."""
        self.handler.read("/.ai/query/test_storage", 1000, 0)

        # Access via the query handler
        with self.handler.query._query_lock:
            self.assertGreater(len(self.handler.query._query_results), 0)


class TestVirtualAISearch(unittest.TestCase):
    """Test search endpoint."""

    def setUp(self):
        self.handler = VirtualAIHandler()

    def test_search_help(self):
        """Test search help content."""
        content = self.handler.read("/.ai/search/_help.txt", 10000, 0)
        self.assertIsInstance(content, bytes)
        self.assertIn(b"Search", content)

    def test_search_without_kg(self):
        """Test search without knowledge graph."""
        content = self.handler.read("/.ai/search/test+query", 10000, 0)
        self.assertIsInstance(content, bytes)
        self.assertIn(b"Knowledge graph not initialized", content)

    def test_search_entities_method(self):
        """Test _search_entities returns empty list without KG."""
        # Access via the search handler
        result = self.handler.search._search_entities("test", None)
        self.assertEqual(result, [])


if __name__ == '__main__':
    unittest.main()
