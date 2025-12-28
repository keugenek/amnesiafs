"""
Relationship Detection Module

Automatically detects and creates relationships between entities in the knowledge graph.
Supports:
- Co-occurrence: Entities appearing in the same file
- Semantic similarity: Entities with similar embeddings
- Reference patterns: Explicit links between files/entities
"""

import logging
import struct
import math
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass

from .knowledge_graph import (
    KnowledgeGraph, Entity, Relationship, RelationType, EntityType
)

logger = logging.getLogger(__name__)


@dataclass
class DetectedRelationship:
    """Represents a detected relationship."""
    source_id: int
    target_id: int
    relation_type: RelationType
    weight: float
    evidence: str = ""  # Explanation of why this relationship exists


class RelationshipDetector:
    """
    Detects and creates relationships between entities.

    Relationship types detected:
    - RELATED_TO: Co-occurrence in same file
    - SIMILAR_TO: Semantic similarity (embedding-based)
    - REFERENCES: Explicit reference between files
    """

    # Thresholds
    SIMILARITY_THRESHOLD = 0.6  # Minimum cosine similarity for SIMILAR_TO
    CO_OCCURRENCE_WEIGHT = 0.5  # Base weight for co-occurrence relations
    MAX_RELATIONSHIPS_PER_ENTITY = 20  # Limit to avoid explosion

    def __init__(self, knowledge_graph: KnowledgeGraph):
        """
        Initialize relationship detector.

        Args:
            knowledge_graph: KnowledgeGraph instance
        """
        self.kg = knowledge_graph

    def detect_for_file(self, file_id: int) -> List[DetectedRelationship]:
        """
        Detect relationships for entities in a file.

        Called after a file is processed to create co-occurrence
        relationships between entities found in the same file.

        Args:
            file_id: ID of the processed file

        Returns:
            List of detected relationships
        """
        detected = []

        # Get all entities in this file
        file_entities = self.kg.get_file_entities(file_id)
        if len(file_entities) < 2:
            return detected

        # Create co-occurrence relationships between entities
        entity_ids = [e[0].id for e in file_entities]

        for i, (entity_i, rel_i, conf_i) in enumerate(file_entities):
            for j, (entity_j, rel_j, conf_j) in enumerate(file_entities[i+1:], i+1):
                # Skip if same entity type and name (likely duplicates)
                if (entity_i.entity_type == entity_j.entity_type and
                    entity_i.normalized_name == entity_j.normalized_name):
                    continue

                # Calculate weight based on confidences
                weight = (conf_i + conf_j) / 2 * self.CO_OCCURRENCE_WEIGHT

                detected.append(DetectedRelationship(
                    source_id=entity_i.id,
                    target_id=entity_j.id,
                    relation_type=RelationType.RELATED_TO,
                    weight=weight,
                    evidence=f"Co-occur in same file (file_id={file_id})"
                ))

        return detected

    def detect_similar_entities(self, entity_id: int,
                                 limit: int = 10) -> List[DetectedRelationship]:
        """
        Find entities similar to the given entity based on embeddings.

        This looks for entities that appear in files with similar embeddings.

        Args:
            entity_id: Entity to find similar entities for
            limit: Maximum similar entities to return

        Returns:
            List of detected SIMILAR_TO relationships
        """
        detected = []

        # Get files containing this entity
        entity_files = self.kg.get_entity_files(entity_id)
        if not entity_files:
            return detected

        # Get embeddings for these files
        file_embeddings = []
        for f in entity_files:
            emb = self.kg.get_embedding(file_id=f.id)
            if emb and emb.vector:
                file_embeddings.append((f.id, emb.vector))

        if not file_embeddings:
            return detected

        # Find similar files
        similar_files = self._find_similar_files(file_embeddings, limit=limit * 2)

        # Get entities from similar files
        seen_entities: Set[int] = {entity_id}
        for sim_file_id, similarity in similar_files:
            if len(detected) >= limit:
                break

            sim_entities = self.kg.get_file_entities(sim_file_id)
            for entity, rel_type, conf in sim_entities:
                if entity.id in seen_entities:
                    continue
                seen_entities.add(entity.id)

                detected.append(DetectedRelationship(
                    source_id=entity_id,
                    target_id=entity.id,
                    relation_type=RelationType.SIMILAR_TO,
                    weight=similarity * conf,
                    evidence=f"Similar file context (sim={similarity:.2f})"
                ))

        return detected

    def _find_similar_files(self, reference_embeddings: List[Tuple[int, bytes]],
                            limit: int = 20) -> List[Tuple[int, float]]:
        """
        Find files similar to the reference embeddings.

        Args:
            reference_embeddings: List of (file_id, embedding) tuples
            limit: Maximum results

        Returns:
            List of (file_id, similarity) tuples, sorted by similarity
        """
        cursor = self.kg.conn.cursor()

        # Get all file embeddings
        cursor.execute("""
            SELECT file_id, vector FROM embeddings
            WHERE file_id IS NOT NULL
        """)

        # Reference file IDs to exclude
        ref_file_ids = {fid for fid, _ in reference_embeddings}

        # Average reference embedding
        ref_vectors = [self._unpack_vector(v) for _, v in reference_embeddings]
        if not ref_vectors:
            return []

        avg_ref = self._average_vectors(ref_vectors)

        similarities = []
        for row in cursor.fetchall():
            file_id = row['file_id']
            if file_id in ref_file_ids:
                continue

            vec = self._unpack_vector(row['vector'])
            if vec:
                sim = self._cosine_similarity(avg_ref, vec)
                if sim >= self.SIMILARITY_THRESHOLD:
                    similarities.append((file_id, sim))

        # Sort by similarity
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:limit]

    def detect_all_co_occurrences(self, batch_size: int = 100) -> int:
        """
        Detect co-occurrence relationships across all files.

        This is a batch operation for initial graph building.

        Args:
            batch_size: Number of files to process per batch

        Returns:
            Total number of relationships created
        """
        cursor = self.kg.conn.cursor()
        cursor.execute("SELECT id FROM files")
        file_ids = [row['id'] for row in cursor.fetchall()]

        total_created = 0
        for file_id in file_ids:
            relationships = self.detect_for_file(file_id)
            for rel in relationships:
                self._save_relationship(rel)
            total_created += len(relationships)

        logger.info(f"Detected {total_created} co-occurrence relationships")
        return total_created

    def detect_entity_similarities(self, limit_per_entity: int = 5) -> int:
        """
        Detect similarity relationships for all entities.

        This creates SIMILAR_TO relationships based on embedding similarity.

        Args:
            limit_per_entity: Max similar entities per entity

        Returns:
            Total number of relationships created
        """
        cursor = self.kg.conn.cursor()
        cursor.execute("SELECT id FROM entities")
        entity_ids = [row['id'] for row in cursor.fetchall()]

        total_created = 0
        for entity_id in entity_ids:
            relationships = self.detect_similar_entities(
                entity_id, limit=limit_per_entity
            )
            for rel in relationships:
                self._save_relationship(rel)
            total_created += len(relationships)

        logger.info(f"Detected {total_created} similarity relationships")
        return total_created

    def _save_relationship(self, rel: DetectedRelationship):
        """Save a detected relationship to the knowledge graph."""
        try:
            self.kg.add_relationship(
                source_id=rel.source_id,
                target_id=rel.target_id,
                relation_type=rel.relation_type,
                weight=rel.weight,
                metadata={'evidence': rel.evidence}
            )
        except Exception as e:
            logger.debug(f"Failed to save relationship: {e}")

    def _unpack_vector(self, vector_bytes: bytes) -> Optional[List[float]]:
        """Unpack vector from bytes."""
        if not vector_bytes:
            return None
        try:
            n_floats = len(vector_bytes) // 4
            return list(struct.unpack(f'{n_floats}f', vector_bytes))
        except:
            return None

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0

        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot / (norm1 * norm2)

    def _average_vectors(self, vectors: List[List[float]]) -> List[float]:
        """Average multiple vectors."""
        if not vectors:
            return []

        n = len(vectors)
        dim = len(vectors[0])
        result = [0.0] * dim

        for vec in vectors:
            for i, v in enumerate(vec):
                result[i] += v

        return [v / n for v in result]


class MultiHopQueryEngine:
    """
    Query engine for multi-hop reasoning over the knowledge graph.

    Supports:
    - Path finding between entities
    - Contextual queries across relationships
    - Aggregated answers from connected knowledge
    """

    MAX_HOPS = 4

    def __init__(self, knowledge_graph: KnowledgeGraph):
        """
        Initialize multi-hop query engine.

        Args:
            knowledge_graph: KnowledgeGraph instance
        """
        self.kg = knowledge_graph

    def find_connections(self, source_name: str, target_name: str,
                         max_hops: int = 3) -> List[Dict]:
        """
        Find connections between two entities.

        Args:
            source_name: Name of source entity
            target_name: Name of target entity
            max_hops: Maximum relationship hops

        Returns:
            List of paths, each path is a list of entities
        """
        # Find source entity
        source = self._find_entity_by_name(source_name)
        if not source:
            return []

        # Find target entity
        target = self._find_entity_by_name(target_name)
        if not target:
            return []

        # Find paths
        paths = self.kg.find_path(source.id, target.id, max_hops=max_hops)

        # Convert paths to readable format
        result = []
        for path in paths:
            path_info = []
            for entity_id in path:
                entity = self.kg.get_entity_by_id(entity_id)
                if entity:
                    path_info.append({
                        'id': entity.id,
                        'name': entity.name,
                        'type': entity.entity_type.value
                    })
            if path_info:
                result.append(path_info)

        return result

    def get_entity_context(self, entity_name: str,
                           depth: int = 2) -> Dict:
        """
        Get full context for an entity including related entities.

        Args:
            entity_name: Name of the entity
            depth: How many hops to explore

        Returns:
            Dict with entity info and related entities
        """
        entity = self._find_entity_by_name(entity_name)
        if not entity:
            return {'error': f'Entity not found: {entity_name}'}

        # Get directly related entities
        related = self.kg.get_related_entities(entity.id, depth=depth)

        # Get files mentioning this entity
        files = self.kg.get_entity_files(entity.id)

        # Get relationships
        relationships = self.kg.get_relationships(entity.id)

        return {
            'entity': {
                'id': entity.id,
                'name': entity.name,
                'type': entity.entity_type.value,
                'source_count': entity.source_count
            },
            'related_entities': [
                {
                    'id': e.id,
                    'name': e.name,
                    'type': e.entity_type.value
                }
                for e in related
            ],
            'files': [
                {
                    'id': f.id,
                    'path': f.path,
                    'summary': f.summary[:200] if f.summary else ''
                }
                for f in files[:10]
            ],
            'relationships': [
                {
                    'type': r.relation_type.value,
                    'target_id': r.target_id if r.source_id == entity.id else r.source_id,
                    'weight': r.weight
                }
                for r in relationships[:20]
            ]
        }

    def query_graph(self, question: str) -> Dict:
        """
        Answer a question using graph traversal.

        Parses the question to identify entities and relationship types,
        then traverses the graph to find answers.

        Args:
            question: Natural language question

        Returns:
            Dict with answer and supporting evidence
        """
        # Extract potential entity names from question
        # (Simple approach: look for capitalized phrases)
        import re
        pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b'
        potential_entities = re.findall(pattern, question)

        # Find matching entities
        found_entities = []
        for name in potential_entities:
            entity = self._find_entity_by_name(name)
            if entity:
                found_entities.append(entity)

        if not found_entities:
            # Try keyword search
            words = question.lower().split()
            for word in words:
                if len(word) > 3:
                    results = self.kg.search_entities(word, limit=3)
                    found_entities.extend(results)

        if not found_entities:
            return {
                'answer': 'No relevant entities found in knowledge graph.',
                'entities': [],
                'evidence': []
            }

        # Collect context from found entities
        evidence = []
        all_related = []

        for entity in found_entities[:5]:  # Limit to top 5 entities
            # Get files
            files = self.kg.get_entity_files(entity.id)
            for f in files[:3]:
                evidence.append({
                    'file': f.path,
                    'text': f.extracted_text[:500] if f.extracted_text else ''
                })

            # Get related entities
            related = self.kg.get_related_entities(entity.id, depth=1)
            all_related.extend(related)

        return {
            'answer': self._generate_answer(found_entities, evidence),
            'entities': [
                {'name': e.name, 'type': e.entity_type.value}
                for e in found_entities
            ],
            'related': [
                {'name': e.name, 'type': e.entity_type.value}
                for e in all_related[:10]
            ],
            'evidence': evidence[:5]
        }

    def _find_entity_by_name(self, name: str) -> Optional[Entity]:
        """Find entity by name (case-insensitive partial match)."""
        cursor = self.kg.conn.cursor()

        # Exact match first
        cursor.execute("""
            SELECT * FROM entities
            WHERE normalized_name = ?
            LIMIT 1
        """, (name.lower().strip(),))
        row = cursor.fetchone()
        if row:
            return self.kg._row_to_entity(row)

        # Partial match
        cursor.execute("""
            SELECT * FROM entities
            WHERE normalized_name LIKE ?
            ORDER BY source_count DESC
            LIMIT 1
        """, (f'%{name.lower().strip()}%',))
        row = cursor.fetchone()
        if row:
            return self.kg._row_to_entity(row)

        return None

    def _generate_answer(self, entities: List[Entity],
                         evidence: List[Dict]) -> str:
        """Generate a simple answer from entities and evidence."""
        if not entities:
            return "No information found."

        entity_names = [e.name for e in entities]
        answer_parts = [f"Found information about: {', '.join(entity_names[:5])}"]

        if evidence:
            answer_parts.append(f"Referenced in {len(evidence)} files.")

        # Add brief context from first evidence
        if evidence and evidence[0].get('text'):
            text = evidence[0]['text'][:200]
            answer_parts.append(f"Context: {text}...")

        return " ".join(answer_parts)


def build_relationship_graph(kg: KnowledgeGraph) -> Dict:
    """
    Build/rebuild relationship graph for existing knowledge.

    This is a utility function to create relationships for
    already-indexed files.

    Args:
        kg: KnowledgeGraph instance

    Returns:
        Stats about relationships created
    """
    detector = RelationshipDetector(kg)

    # Build co-occurrence relationships
    co_occurrence_count = detector.detect_all_co_occurrences()

    # Build similarity relationships
    similarity_count = detector.detect_entity_similarities()

    return {
        'co_occurrence_relationships': co_occurrence_count,
        'similarity_relationships': similarity_count,
        'total': co_occurrence_count + similarity_count
    }
