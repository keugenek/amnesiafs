"""
Topic handler for /.ai/by-topic/ (semantic clustering)
"""

import os
import time
import pickle
from typing import Optional, Dict, List, Tuple
from .base import BaseHandler


class TopicHandler(BaseHandler):
    """Handles /.ai/by-topic/ virtual paths for semantic topic clustering."""

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for by-topic paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files and editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        # /.ai/by-topic/<topic> - directory listing files in topic
        if len(parts) == 2:
            topic_name = parts[1]
            topics = self._get_topic_clusters()
            if topic_name in topics:
                return self._make_dir_stat(now)
            return None

        # /.ai/by-topic/<topic>/<filename> - virtual file showing file info
        if len(parts) == 3:
            topic_name = parts[1]
            filename = parts[2]
            topics = self._get_topic_clusters()
            if topic_name in topics:
                for file_path, _ in topics[topic_name]:
                    if file_path.split('/')[-1] == filename:
                        content = self._get_topic_file_content(file_path)
                        return self._make_file_stat(len(content), now)
            return None

        return None

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """List topics or files in a topic."""
        if not target_path:
            topics = self._get_topic_clusters()
            return list(topics.keys())

        # List files in a specific topic
        path_parts = target_path.strip('/').split('/')
        if len(path_parts) == 1:
            topic_name = path_parts[0]
            topics = self._get_topic_clusters()
            if topic_name in topics:
                # Return just filenames (not full paths)
                return [path.split('/')[-1] for path, _ in topics[topic_name]]

        return []

    def read(self, target_path: str, parts: List[str]) -> bytes:
        """Read content from by-topic virtual paths."""
        if not target_path:
            # Show help for by-topic directory
            return self._get_by_topic_help()

        # /.ai/by-topic/<topic> - show topic overview
        if len(parts) == 2:
            topic_name = parts[1]
            return self._get_topic_overview(topic_name)

        # /.ai/by-topic/<topic>/<filename> - show file info
        if len(parts) == 3:
            topic_name = parts[1]
            filename = parts[2]
            topics = self._get_topic_clusters()
            if topic_name in topics:
                for file_path, _ in topics[topic_name]:
                    if file_path.split('/')[-1] == filename:
                        return self._get_topic_file_content(file_path)

        return b""

    def _get_topic_clusters(self) -> Dict[str, List[Tuple[str, float]]]:
        """
        Cluster files into topics based on embedding similarity.

        Returns:
            Dict mapping topic_name -> [(file_path, similarity_score), ...]
        """
        cache_key = "topic_clusters"
        cached = self._get_cached(cache_key)
        if cached:
            return pickle.loads(cached)

        topics = self._compute_topic_clusters()

        # Cache the result
        self._set_cached(cache_key, pickle.dumps(topics))

        return topics

    def _compute_topic_clusters(self) -> Dict[str, List[Tuple[str, float]]]:
        """Compute topic clusters from file embeddings."""
        if not self.knowledge_graph:
            return {"uncategorized": []}

        from ..embedder import cosine_similarity

        # Get all files with embeddings
        cursor = self.knowledge_graph.conn.cursor()
        cursor.execute("""
            SELECT f.id, f.path, f.summary, e.vector
            FROM files f
            JOIN embeddings e ON f.embedding_id = e.id
            WHERE e.vector IS NOT NULL
        """)

        files = []
        for row in cursor.fetchall():
            path = row['path']
            # Verify file still exists
            if self.cognitivefs and not self.cognitivefs._resolve_path(path):
                continue
            files.append({
                'id': row['id'],
                'path': path,
                'summary': row['summary'] or "",
                'vector': row['vector']
            })

        if not files:
            return {"uncategorized": []}

        # Simple clustering: group files with similarity > threshold
        SIMILARITY_THRESHOLD = 0.5
        clusters = []  # List of sets of file indices
        assigned = set()

        for i, file_i in enumerate(files):
            if i in assigned:
                continue

            # Start new cluster with this file
            cluster = {i}
            assigned.add(i)

            # Find all similar files
            for j, file_j in enumerate(files):
                if j in assigned:
                    continue

                sim = cosine_similarity(file_i['vector'], file_j['vector'])
                if sim >= SIMILARITY_THRESHOLD:
                    cluster.add(j)
                    assigned.add(j)

            clusters.append(cluster)

        # Name clusters based on common entities or keywords
        topics = {}
        for idx, cluster in enumerate(clusters):
            # Get files in this cluster
            cluster_files = [files[i] for i in cluster]

            # Get topic name from entities
            topic_name = self._get_cluster_topic_name(cluster_files, idx)

            # Add files with their "centrality" score
            topic_files = []
            for file in cluster_files:
                # Calculate average similarity to other files in cluster
                if len(cluster_files) > 1:
                    sims = []
                    for other in cluster_files:
                        if other['id'] != file['id']:
                            sims.append(cosine_similarity(file['vector'], other['vector']))
                    avg_sim = sum(sims) / len(sims) if sims else 1.0
                else:
                    avg_sim = 1.0
                topic_files.append((file['path'], avg_sim))

            # Sort by centrality
            topic_files.sort(key=lambda x: x[1], reverse=True)
            topics[topic_name] = topic_files

        # Add uncategorized for any remaining files
        if not topics:
            topics["uncategorized"] = [(f['path'], 1.0) for f in files]

        return topics

    def _get_cluster_topic_name(self, cluster_files: List[Dict], cluster_idx: int) -> str:
        """Generate a topic name for a cluster based on common entities."""
        if not cluster_files:
            return f"topic_{cluster_idx}"

        # Get entities from files in cluster
        file_ids = [f['id'] for f in cluster_files]

        if not self.knowledge_graph:
            return f"topic_{cluster_idx}"

        cursor = self.knowledge_graph.conn.cursor()
        placeholders = ",".join("?" * len(file_ids))

        # Get most common entities across cluster files
        cursor.execute(f"""
            SELECT e.name, e.entity_type, COUNT(*) as count
            FROM file_entities fe
            JOIN entities e ON fe.entity_id = e.id
            WHERE fe.file_id IN ({placeholders})
            GROUP BY e.id
            ORDER BY count DESC
            LIMIT 3
        """, file_ids)

        entities = cursor.fetchall()

        if entities:
            # Use top entity as topic name
            top_entity = entities[0]['name']
            # Clean up the name for use as directory name
            topic_name = top_entity.lower().replace(' ', '_').replace('/', '-')
            # Remove non-alphanumeric except underscore and hyphen
            topic_name = ''.join(c for c in topic_name if c.isalnum() or c in '_-')
            if topic_name:
                return topic_name[:50]  # Limit length

        # Fall back to path-based name if no entities
        if cluster_files:
            paths = [f['path'] for f in cluster_files]
            # Find common path prefix
            common_prefix = os.path.commonpath([p for p in paths if p])
            if common_prefix and common_prefix != '/':
                dir_name = os.path.basename(common_prefix)
                if dir_name:
                    return dir_name.lower().replace(' ', '_')

        return f"topic_{cluster_idx}"

    def _get_topic_file_content(self, file_path: str) -> bytes:
        """Get content for a file viewed through the topic browser."""
        lines = [
            f"# File: {file_path}",
            ""
        ]

        # Get file info from knowledge graph
        if self.knowledge_graph:
            file_record = self.knowledge_graph.get_file(file_path)
            if file_record:
                lines.append(f"Path: {file_record.path}")
                if file_record.mime_type:
                    lines.append(f"Type: {file_record.mime_type}")
                if file_record.summary:
                    lines.append(f"Summary: {file_record.summary}")
                lines.append("")

                # Get entities
                cursor = self.knowledge_graph.conn.cursor()
                cursor.execute("""
                    SELECT e.name, e.entity_type
                    FROM file_entities fe
                    JOIN entities e ON fe.entity_id = e.id
                    WHERE fe.file_id = ?
                    LIMIT 10
                """, (file_record.id,))

                entities = cursor.fetchall()
                if entities:
                    lines.append("Entities:")
                    for e in entities:
                        lines.append(f"  - {e['name']} ({e['entity_type']})")
                    lines.append("")

        lines.append(f"To read full file: cat {file_path}")
        lines.append("")

        return "\n".join(lines).encode('utf-8')

    def _get_by_topic_help(self) -> bytes:
        """Return help text for by-topic directory."""
        topics = self._get_topic_clusters()

        lines = [
            "# Files Organized by Topic",
            "",
            "Files are automatically clustered by semantic similarity.",
            "Topics are named based on common entities in each cluster.",
            "",
            f"## Topics ({len(topics)} total)",
            ""
        ]

        for topic_name, files in topics.items():
            lines.append(f"  {topic_name}/ ({len(files)} files)")

        lines.extend([
            "",
            "## Usage",
            "",
            "  ls /.ai/by-topic/              # List all topics",
            "  ls /.ai/by-topic/<topic>/      # List files in topic",
            "  cat /.ai/by-topic/<topic>/file # View file info",
            ""
        ])

        return "\n".join(lines).encode('utf-8')

    def _get_topic_overview(self, topic_name: str) -> bytes:
        """Get overview of a topic cluster."""
        topics = self._get_topic_clusters()

        if topic_name not in topics:
            return f"Topic not found: {topic_name}\n".encode('utf-8')

        files = topics[topic_name]

        lines = [
            f"# Topic: {topic_name}",
            f"# Files: {len(files)}",
            ""
        ]

        # List files with their centrality scores
        lines.append("## Files (sorted by centrality)")
        for file_path, score in files:
            lines.append(f"  [{score:.2f}] {file_path}")

        lines.append("")

        # Get common entities across all files in topic
        if self.knowledge_graph and files:
            file_ids = []
            for file_path, _ in files:
                file_record = self.knowledge_graph.get_file(file_path)
                if file_record:
                    file_ids.append(file_record.id)

            if file_ids:
                cursor = self.knowledge_graph.conn.cursor()
                placeholders = ",".join("?" * len(file_ids))
                cursor.execute(f"""
                    SELECT e.name, e.entity_type, COUNT(*) as count
                    FROM file_entities fe
                    JOIN entities e ON fe.entity_id = e.id
                    WHERE fe.file_id IN ({placeholders})
                    GROUP BY e.id
                    ORDER BY count DESC
                    LIMIT 10
                """, file_ids)

                entities = cursor.fetchall()
                if entities:
                    lines.append("## Common Entities")
                    for e in entities:
                        lines.append(f"  - {e['name']} ({e['entity_type']}) [{e['count']} refs]")
                    lines.append("")

        return "\n".join(lines).encode('utf-8')
