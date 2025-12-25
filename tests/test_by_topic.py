#!/usr/bin/env python3
"""Test the by-topic clustering functionality."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cognitivefs.virtual_ai import VirtualAIHandler
from cognitivefs.embedder import cosine_similarity, pack_embedding, unpack_embedding


def test_cosine_similarity():
    """Test cosine similarity calculation."""
    # Create some test vectors
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [1.0, 0.0, 0.0]
    vec3 = [0.0, 1.0, 0.0]
    vec4 = [0.707, 0.707, 0.0]

    packed1 = pack_embedding(vec1)
    packed2 = pack_embedding(vec2)
    packed3 = pack_embedding(vec3)
    packed4 = pack_embedding(vec4)

    # Same vector should have similarity 1.0
    sim1 = cosine_similarity(packed1, packed2)
    assert abs(sim1 - 1.0) < 0.001, f"Expected 1.0, got {sim1}"

    # Orthogonal vectors should have similarity 0.0
    sim2 = cosine_similarity(packed1, packed3)
    assert abs(sim2 - 0.0) < 0.001, f"Expected 0.0, got {sim2}"

    # 45 degree vector should have similarity ~0.707
    sim3 = cosine_similarity(packed1, packed4)
    assert abs(sim3 - 0.707) < 0.01, f"Expected ~0.707, got {sim3}"

    print("[OK] Cosine similarity tests passed")


def test_virtual_ai_handler_parsing():
    """Test path parsing for by-topic."""
    handler = VirtualAIHandler()

    # Test parsing
    subdir, target, parts = handler.parse_ai_path("/.ai/by-topic")
    assert subdir == "by-topic", f"Expected by-topic, got {subdir}"
    assert target == "", f"Expected empty target, got {target}"

    subdir, target, parts = handler.parse_ai_path("/.ai/by-topic/machine_learning")
    assert subdir == "by-topic", f"Expected by-topic, got {subdir}"
    assert parts == ["by-topic", "machine_learning"], f"Expected parts, got {parts}"

    subdir, target, parts = handler.parse_ai_path("/.ai/by-topic/ml/notes.txt")
    assert subdir == "by-topic", f"Expected by-topic, got {subdir}"
    assert parts == ["by-topic", "ml", "notes.txt"], f"Expected parts, got {parts}"

    print("[OK] Path parsing tests passed")


def test_getattr_by_topic():
    """Test getattr for by-topic paths."""
    handler = VirtualAIHandler()

    # Root by-topic should be a directory
    result = handler.getattr("/.ai/by-topic")
    assert result is not None, "Expected stat dict for by-topic root"
    assert result.get('st_mode') & 0o170000 == 0o040000, "Expected directory mode"

    print("[OK] getattr tests passed")


def test_readdir_by_topic():
    """Test readdir for by-topic (without KG should return empty or uncategorized)."""
    handler = VirtualAIHandler()

    # Without knowledge graph, should return empty list or uncategorized
    topics = handler._readdir_by_topic("")
    assert isinstance(topics, list), f"Expected list, got {type(topics)}"

    print(f"[OK] readdir tests passed (topics: {topics})")


def test_topic_clustering_algorithm():
    """Test the topic clustering algorithm with mock data."""
    from cognitivefs.embedder import pack_embedding

    # Create mock files with embeddings
    # Group 1: Similar vectors (cooking)
    cooking_vec = [0.8, 0.2, 0.1]
    recipe_vec = [0.75, 0.25, 0.15]

    # Group 2: Similar vectors (tech)
    tech_vec = [0.1, 0.9, 0.1]
    code_vec = [0.15, 0.85, 0.2]

    # Outlier
    random_vec = [0.5, 0.5, 0.5]

    # Pack them
    cooking_packed = pack_embedding(cooking_vec)
    recipe_packed = pack_embedding(recipe_vec)
    tech_packed = pack_embedding(tech_vec)
    code_packed = pack_embedding(code_vec)
    random_packed = pack_embedding(random_vec)

    # Test similarity within groups
    sim_cooking = cosine_similarity(cooking_packed, recipe_packed)
    sim_tech = cosine_similarity(tech_packed, code_packed)
    sim_cross = cosine_similarity(cooking_packed, tech_packed)

    print(f"  Cooking group similarity: {sim_cooking:.3f}")
    print(f"  Tech group similarity: {sim_tech:.3f}")
    print(f"  Cross-group similarity: {sim_cross:.3f}")

    # Within group should be higher than cross-group
    assert sim_cooking > sim_cross, "Expected cooking similarity > cross"
    assert sim_tech > sim_cross, "Expected tech similarity > cross"

    print("[OK] Topic clustering algorithm tests passed")


if __name__ == "__main__":
    print("Testing by-topic functionality...\n")

    test_cosine_similarity()
    test_virtual_ai_handler_parsing()
    test_getattr_by_topic()
    test_readdir_by_topic()
    test_topic_clustering_algorithm()

    print("\n[OK] All tests passed!")
