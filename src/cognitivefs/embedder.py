"""
Embedding Generator Module

Generates vector embeddings for text content using sentence-transformers.
Embeddings are stored as packed float32 arrays for efficient storage in SQLite.
"""

import struct
import math
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """
    Generate vector embeddings using sentence-transformers.

    Uses all-MiniLM-L6-v2 model by default (384 dimensions).
    Model is lazy-loaded on first use to avoid startup delay.
    """

    MODEL_NAME = "all-MiniLM-L6-v2"
    DIMENSIONS = 384

    def __init__(self, model_name: Optional[str] = None):
        """
        Initialize embedding generator.

        Args:
            model_name: Optional model name override
        """
        self.model_name = model_name or self.MODEL_NAME
        self._model = None
        self._available = None  # None = not checked, True/False = checked

    @property
    def is_available(self) -> bool:
        """Check if sentence-transformers is available."""
        if self._available is None:
            try:
                import sentence_transformers
                self._available = True
            except ImportError:
                logger.warning(
                    "sentence-transformers not installed. "
                    "Embeddings will be disabled. "
                    "Install with: pip install sentence-transformers"
                )
                self._available = False
        return self._available

    @property
    def dimensions(self) -> int:
        """Get embedding dimensions for current model."""
        if self.model_name == "all-MiniLM-L6-v2":
            return 384
        elif self.model_name == "all-mpnet-base-v2":
            return 768
        elif self.model_name == "all-MiniLM-L12-v2":
            return 384
        else:
            # Load model to get dimensions
            self._load_model()
            if self._model:
                return self._model.get_sentence_embedding_dimension()
            return 384  # Default fallback

    def _load_model(self):
        """Lazy load the embedding model."""
        if self._model is not None:
            return

        if not self.is_available:
            return

        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
            logger.info(f"Model loaded. Dimensions: {self._model.get_sentence_embedding_dimension()}")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self._available = False

    def generate(self, text: str, max_length: int = 512) -> Optional[bytes]:
        """
        Generate embedding for text.

        Args:
            text: Input text to embed
            max_length: Maximum text length (truncated if longer)

        Returns:
            Packed float32 bytes, or None if embedding fails
        """
        if not self.is_available:
            return None

        self._load_model()
        if self._model is None:
            return None

        try:
            # Truncate long text
            if len(text) > max_length * 4:  # Rough char estimate
                text = text[:max_length * 4]

            # Generate embedding
            embedding = self._model.encode(text, convert_to_numpy=True)

            # Pack as float32 bytes
            return pack_embedding(embedding.tolist())

        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None

    def generate_batch(self, texts: List[str],
                       max_length: int = 512) -> List[Optional[bytes]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of input texts
            max_length: Maximum text length per text

        Returns:
            List of packed embeddings (None for failures)
        """
        if not self.is_available or not texts:
            return [None] * len(texts)

        self._load_model()
        if self._model is None:
            return [None] * len(texts)

        try:
            # Truncate long texts
            truncated = [t[:max_length * 4] for t in texts]

            # Generate embeddings
            embeddings = self._model.encode(truncated, convert_to_numpy=True)

            # Pack each embedding
            return [pack_embedding(emb.tolist()) for emb in embeddings]

        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {e}")
            return [None] * len(texts)

    def similarity(self, vec1: bytes, vec2: bytes) -> float:
        """
        Compute cosine similarity between two embeddings.

        Args:
            vec1: First embedding (packed bytes)
            vec2: Second embedding (packed bytes)

        Returns:
            Cosine similarity score (-1 to 1)
        """
        return cosine_similarity(vec1, vec2)


def pack_embedding(vector: List[float]) -> bytes:
    """
    Pack embedding vector as float32 bytes.

    Args:
        vector: List of float values

    Returns:
        Packed bytes (4 bytes per float)
    """
    return struct.pack(f'{len(vector)}f', *vector)


def unpack_embedding(data: bytes) -> List[float]:
    """
    Unpack embedding vector from bytes.

    Args:
        data: Packed float32 bytes

    Returns:
        List of float values
    """
    count = len(data) // 4
    return list(struct.unpack(f'{count}f', data))


def cosine_similarity(vec1: bytes, vec2: bytes) -> float:
    """
    Compute cosine similarity between two packed embeddings.

    Args:
        vec1: First embedding (packed bytes)
        vec2: Second embedding (packed bytes)

    Returns:
        Cosine similarity score (-1 to 1)
    """
    if not vec1 or not vec2:
        return 0.0

    v1 = unpack_embedding(vec1)
    v2 = unpack_embedding(vec2)

    if len(v1) != len(v2):
        return 0.0

    # Compute dot product and magnitudes
    dot_product = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))

    if mag1 == 0 or mag2 == 0:
        return 0.0

    return dot_product / (mag1 * mag2)


def euclidean_distance(vec1: bytes, vec2: bytes) -> float:
    """
    Compute Euclidean distance between two packed embeddings.

    Args:
        vec1: First embedding (packed bytes)
        vec2: Second embedding (packed bytes)

    Returns:
        Euclidean distance (0 to inf, lower = more similar)
    """
    if not vec1 or not vec2:
        return float('inf')

    v1 = unpack_embedding(vec1)
    v2 = unpack_embedding(vec2)

    if len(v1) != len(v2):
        return float('inf')

    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))


class MockEmbeddingGenerator:
    """
    Mock embedding generator for testing without sentence-transformers.

    Generates deterministic embeddings based on text hash.
    """

    DIMENSIONS = 384

    def __init__(self):
        self._available = True

    @property
    def is_available(self) -> bool:
        return True

    @property
    def dimensions(self) -> int:
        return self.DIMENSIONS

    def generate(self, text: str, max_length: int = 512) -> bytes:
        """Generate mock embedding based on text hash."""
        import hashlib

        # Create deterministic embedding from text hash
        hash_bytes = hashlib.sha256(text.encode('utf-8')).digest()

        # Expand hash to fill dimensions
        vector = []
        for i in range(self.DIMENSIONS):
            # Use hash bytes cyclically
            byte_val = hash_bytes[i % len(hash_bytes)]
            # Normalize to [-1, 1]
            vector.append((byte_val / 128.0) - 1.0)

        return pack_embedding(vector)

    def generate_batch(self, texts: List[str],
                       max_length: int = 512) -> List[bytes]:
        """Generate mock embeddings for batch."""
        return [self.generate(t, max_length) for t in texts]

    def similarity(self, vec1: bytes, vec2: bytes) -> float:
        """Compute cosine similarity."""
        return cosine_similarity(vec1, vec2)
