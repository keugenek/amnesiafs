"""
Cross-Encoder Reranker Module

Provides reranking capabilities using cross-encoder models to improve
retrieval precision by scoring query-document pairs directly.

Phase 1.2 RAG Improvement - Based on BGE-reranker research.
"""

import logging
from typing import List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Flag for reranker availability
_RERANKER_AVAILABLE = None
_reranker_instance = None


@dataclass
class RerankResult:
    """Result from reranking."""
    text: str
    score: float
    original_index: int
    metadata: dict = None


class CrossEncoderReranker:
    """
    Cross-encoder reranker using sentence-transformers.

    Cross-encoders process query-document pairs together, enabling
    more accurate relevance scoring than bi-encoders (separate embeddings).

    Default model: BAAI/bge-reranker-base (lightweight, fast)
    Alternative: BAAI/bge-reranker-v2-m3 (better quality, 8192 tokens)
    """

    # Model options
    MODEL_BASE = "BAAI/bge-reranker-base"  # Fast, 512 tokens
    MODEL_LARGE = "BAAI/bge-reranker-large"  # Better quality
    MODEL_V2_M3 = "BAAI/bge-reranker-v2-m3"  # Best quality, 8192 tokens

    def __init__(self, model_name: str = None):
        """
        Initialize reranker with specified model.

        Args:
            model_name: HuggingFace model name (default: bge-reranker-base)
        """
        self.model_name = model_name or self.MODEL_BASE
        self.model = None
        self._available = None

    @property
    def is_available(self) -> bool:
        """Check if reranker model is available."""
        if self._available is None:
            self._available = self._load_model()
        return self._available

    def _load_model(self) -> bool:
        """Load the cross-encoder model."""
        try:
            from sentence_transformers import CrossEncoder

            logger.info(f"Loading reranker model: {self.model_name}")
            self.model = CrossEncoder(self.model_name)
            logger.info("Reranker model loaded successfully")
            return True

        except ImportError:
            logger.warning("sentence-transformers not installed. Reranking disabled.")
            return False
        except Exception as e:
            logger.warning(f"Failed to load reranker model: {e}")
            return False

    def rerank(self, query: str, documents: List[str],
               top_k: int = None) -> List[RerankResult]:
        """
        Rerank documents by relevance to query.

        Args:
            query: The search query
            documents: List of document texts to rerank
            top_k: Return only top K results (None = all)

        Returns:
            List of RerankResult sorted by relevance score (descending)
        """
        if not documents:
            return []

        if not self.is_available:
            # Return documents in original order with default scores
            logger.debug("Reranker not available, returning original order")
            return [
                RerankResult(text=doc, score=1.0 - (i * 0.1), original_index=i)
                for i, doc in enumerate(documents)
            ]

        try:
            # Create query-document pairs
            pairs = [[query, doc] for doc in documents]

            # Get relevance scores
            scores = self.model.predict(pairs)

            # Create results with scores
            results = [
                RerankResult(
                    text=doc,
                    score=float(score),
                    original_index=i
                )
                for i, (doc, score) in enumerate(zip(documents, scores))
            ]

            # Sort by score descending
            results.sort(key=lambda x: x.score, reverse=True)

            # Return top_k if specified
            if top_k is not None:
                results = results[:top_k]

            return results

        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            # Fallback to original order
            return [
                RerankResult(text=doc, score=0.5, original_index=i)
                for i, doc in enumerate(documents[:top_k] if top_k else documents)
            ]

    def rerank_with_metadata(self, query: str,
                             documents: List[Tuple[str, dict]],
                             top_k: int = None) -> List[RerankResult]:
        """
        Rerank documents with associated metadata.

        Args:
            query: The search query
            documents: List of (document_text, metadata_dict) tuples
            top_k: Return only top K results

        Returns:
            List of RerankResult with metadata preserved
        """
        if not documents:
            return []

        texts = [doc[0] for doc in documents]
        metadatas = [doc[1] for doc in documents]

        results = self.rerank(query, texts, top_k=None)  # Rerank all first

        # Attach metadata
        for result in results:
            result.metadata = metadatas[result.original_index]

        # Apply top_k after metadata attachment
        if top_k is not None:
            results = results[:top_k]

        return results


def get_reranker(model_name: str = None) -> CrossEncoderReranker:
    """
    Get or create reranker singleton.

    Args:
        model_name: Optional model name override

    Returns:
        CrossEncoderReranker instance
    """
    global _reranker_instance

    if _reranker_instance is None or (model_name and _reranker_instance.model_name != model_name):
        _reranker_instance = CrossEncoderReranker(model_name)

    return _reranker_instance


def is_reranker_available() -> bool:
    """Check if reranking is available without loading model."""
    global _RERANKER_AVAILABLE

    if _RERANKER_AVAILABLE is None:
        try:
            from sentence_transformers import CrossEncoder
            _RERANKER_AVAILABLE = True
        except ImportError:
            _RERANKER_AVAILABLE = False

    return _RERANKER_AVAILABLE
