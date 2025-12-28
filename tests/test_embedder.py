"""Unit tests for Embedder module."""

import os
import sys
import struct
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cognitivefs.embedder import (
    EmbeddingGenerator, cosine_similarity, pack_embedding, unpack_embedding
)


class TestVectorOperations(unittest.TestCase):
    """Test vector packing and similarity functions."""

    def test_pack_unpack_vector(self):
        """Test vector serialization round-trip."""
        original = [0.1, 0.2, 0.3, 0.4, 0.5]
        packed = pack_embedding(original)
        unpacked = unpack_embedding(packed)

        self.assertEqual(len(original), len(unpacked))
        for a, b in zip(original, unpacked):
            self.assertAlmostEqual(a, b, places=5)

    def test_pack_empty_vector(self):
        """Test packing empty vector."""
        packed = pack_embedding([])
        self.assertEqual(packed, b'')

    def test_unpack_empty_bytes(self):
        """Test unpacking empty bytes."""
        unpacked = unpack_embedding(b'')
        self.assertEqual(unpacked, [])

    def test_cosine_similarity_identical(self):
        """Test similarity of identical vectors."""
        v1 = pack_embedding([1.0, 0.0, 0.0])
        v2 = pack_embedding([1.0, 0.0, 0.0])
        sim = cosine_similarity(v1, v2)
        self.assertAlmostEqual(sim, 1.0, places=5)

    def test_cosine_similarity_orthogonal(self):
        """Test similarity of orthogonal vectors."""
        v1 = pack_embedding([1.0, 0.0, 0.0])
        v2 = pack_embedding([0.0, 1.0, 0.0])
        sim = cosine_similarity(v1, v2)
        self.assertAlmostEqual(sim, 0.0, places=5)

    def test_cosine_similarity_opposite(self):
        """Test similarity of opposite vectors."""
        v1 = pack_embedding([1.0, 0.0])
        v2 = pack_embedding([-1.0, 0.0])
        sim = cosine_similarity(v1, v2)
        self.assertAlmostEqual(sim, -1.0, places=5)

    def test_cosine_similarity_normalized(self):
        """Test similarity is magnitude-independent."""
        v1 = pack_embedding([1.0, 1.0])
        v2 = pack_embedding([2.0, 2.0])  # Same direction, different magnitude
        sim = cosine_similarity(v1, v2)
        self.assertAlmostEqual(sim, 1.0, places=5)

    def test_cosine_similarity_empty(self):
        """Test similarity with empty vectors."""
        sim = cosine_similarity(b'', b'')
        self.assertEqual(sim, 0.0)

    def test_cosine_similarity_mismatched_length(self):
        """Test similarity with different length vectors."""
        v1 = pack_embedding([1.0, 2.0])
        v2 = pack_embedding([1.0, 2.0, 3.0])
        sim = cosine_similarity(v1, v2)
        self.assertEqual(sim, 0.0)


class TestEmbeddingGenerator(unittest.TestCase):
    """Test EmbeddingGenerator class."""

    def setUp(self):
        """Create embedding generator."""
        self.generator = EmbeddingGenerator()

    def test_generator_creation(self):
        """Test generator initializes."""
        self.assertIsNotNone(self.generator)

    def test_availability_check(self):
        """Test is_available property."""
        # Should be True or False, not raise
        available = self.generator.is_available
        self.assertIsInstance(available, bool)

    def test_generate_returns_bytes_or_none(self):
        """Test generate returns bytes or None."""
        result = self.generator.generate("test text")
        self.assertTrue(result is None or isinstance(result, bytes))

    def test_generate_empty_text(self):
        """Test generate with empty text."""
        result = self.generator.generate("")
        # Should handle gracefully
        self.assertTrue(result is None or isinstance(result, bytes))

    @unittest.skipUnless(
        EmbeddingGenerator().is_available,
        "sentence-transformers not installed"
    )
    def test_generate_produces_vector(self):
        """Test actual embedding generation."""
        result = self.generator.generate("Hello world")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, bytes)
        # Should be 384 dimensions * 4 bytes
        self.assertEqual(len(result), 384 * 4)

    @unittest.skipUnless(
        EmbeddingGenerator().is_available,
        "sentence-transformers not installed"
    )
    def test_similar_texts_have_high_similarity(self):
        """Test similar texts produce similar embeddings."""
        v1 = self.generator.generate("machine learning algorithms")
        v2 = self.generator.generate("machine learning methods")
        v3 = self.generator.generate("cooking recipes for dinner")

        sim_similar = cosine_similarity(v1, v2)
        sim_different = cosine_similarity(v1, v3)

        self.assertGreater(sim_similar, sim_different)
        self.assertGreater(sim_similar, 0.5)


if __name__ == '__main__':
    unittest.main()
