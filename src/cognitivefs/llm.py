"""
LLM Integration Module

Provides LLM capabilities via Ollama for:
- Natural language queries against the knowledge graph
- File summarization
- Chat conversations
"""

import json
import logging
from typing import Optional, List, Dict, Any, Generator
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default Ollama configuration
OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:3b"


@dataclass
class LLMResponse:
    """Response from LLM."""
    content: str
    model: str
    done: bool
    total_duration: Optional[int] = None
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None


class OllamaClient:
    """Client for Ollama API."""

    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = DEFAULT_MODEL):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self._available = None

    @property
    def is_available(self) -> bool:
        """Check if Ollama is available."""
        if self._available is None:
            self._available = self._check_availability()
        return self._available

    def _check_availability(self) -> bool:
        """Check if Ollama server is running."""
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f"Ollama not available: {e}")
            return False

    def generate(self, prompt: str, system: str = None,
                 temperature: float = 0.7, max_tokens: int = 1024) -> Optional[LLMResponse]:
        """
        Generate a response from the LLM.

        Args:
            prompt: The user prompt
            system: Optional system prompt
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate

        Returns:
            LLMResponse or None if failed
        """
        if not self.is_available:
            return None

        try:
            import urllib.request

            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                }
            }

            if system:
                payload["system"] = system

            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                f"{self.base_url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode('utf-8'))

            return LLMResponse(
                content=result.get("response", ""),
                model=result.get("model", self.model),
                done=result.get("done", True),
                total_duration=result.get("total_duration"),
                prompt_eval_count=result.get("prompt_eval_count"),
                eval_count=result.get("eval_count"),
            )

        except urllib.error.URLError as e:
            if 'timed out' in str(e).lower():
                logger.warning("LLM query timed out (15s limit)")
                return LLMResponse(content="Query timed out. Try a simpler question.", model=self.model, done=True)
            logger.error(f"LLM generation failed: {e}")
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return None

    def chat(self, messages: List[Dict[str, str]],
             temperature: float = 0.7, max_tokens: int = 1024) -> Optional[LLMResponse]:
        """
        Chat completion with message history.

        Args:
            messages: List of {"role": "user"|"assistant"|"system", "content": "..."}
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            LLMResponse or None if failed
        """
        if not self.is_available:
            return None

        try:
            import urllib.request

            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                }
            }

            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode('utf-8'))

            message = result.get("message", {})
            return LLMResponse(
                content=message.get("content", ""),
                model=result.get("model", self.model),
                done=result.get("done", True),
                total_duration=result.get("total_duration"),
                prompt_eval_count=result.get("prompt_eval_count"),
                eval_count=result.get("eval_count"),
            )

        except Exception as e:
            logger.error(f"LLM chat failed: {e}")
            return None


class KnowledgeQueryEngine:
    """
    Query engine that combines knowledge graph with LLM.

    Retrieves relevant context from KG and uses LLM to answer questions.
    """

    SYSTEM_PROMPT = """You are a helpful AI assistant with access to a personal knowledge base.
Answer questions based on the provided context from the user's files.
If the context doesn't contain enough information, say so.
Be concise and direct. Reference specific files when relevant."""

    def __init__(self, knowledge_graph, llm_client: OllamaClient):
        self.kg = knowledge_graph
        self.llm = llm_client

    def query(self, question: str, max_context_files: int = 3) -> str:
        """
        Answer a question using the knowledge graph and LLM.

        Args:
            question: Natural language question
            max_context_files: Maximum number of files to include as context

        Returns:
            Answer string
        """
        result = self.query_with_context(question, max_context_files)
        return result.get('formatted_response', 'No response generated.\n')

    def query_with_context(self, question: str, max_context_files: int = 3) -> Dict:
        """
        Answer a question and return full context for transparency.

        Args:
            question: Natural language question
            max_context_files: Maximum number of files to include as context

        Returns:
            Dict with answer, files_used, entities_used, relationships_used
        """
        result = {
            'question': question,
            'answer': '',
            'files_used': [],
            'entities_used': [],
            'relationships_used': [],
            'llm_available': self.llm.is_available,
            'formatted_response': ''
        }

        if not self.llm.is_available:
            result['answer'] = "LLM not available. Please ensure Ollama is running."
            result['formatted_response'] = result['answer'] + "\n"
            return result

        # 1. Find relevant files using semantic search
        context_files = self._find_relevant_files(question, max_context_files)
        result['files_used'] = [
            {'path': f['path'], 'similarity': f.get('similarity', 0)}
            for f in context_files
        ]

        # 2. Find relevant entities from the knowledge graph
        entity_context, entities_found, relationships_found = self._find_relevant_entities_detailed(
            question, context_files
        )
        result['entities_used'] = entities_found
        result['relationships_used'] = relationships_found

        if not context_files and not entity_context:
            # No indexed content, still try to answer
            prompt = f"Question: {question}\n\nNo files have been indexed yet. Please let the user know they should add some files first."
            response = self.llm.generate(prompt, system=self.SYSTEM_PROMPT)
            if response:
                result['answer'] = response.content
                result['formatted_response'] = response.content
            else:
                result['answer'] = "No files indexed and LLM unavailable."
                result['formatted_response'] = result['answer'] + "\n"
            return result

        # 3. Build context from files and entities
        file_context = self._build_context(context_files) if context_files else ""

        # 4. Combine contexts
        full_context = ""
        if file_context:
            full_context += f"[Files]\n{file_context}\n"
        if entity_context:
            full_context += f"\n[Knowledge Graph]\n{entity_context}\n"

        # 5. Generate answer
        prompt = f"""Context from your knowledge base:
{full_context}

Question: {question}

Answer based on the context above. Reference specific files and entities when relevant:"""

        response = self.llm.generate(prompt, system=self.SYSTEM_PROMPT, max_tokens=256)

        if response:
            result['answer'] = response.content
            # Format response with sources
            sources = "\n\nSources:\n"
            if context_files:
                sources += "\n".join(f"  - {f['path']}" for f in context_files)
            result['formatted_response'] = response.content + sources + "\n"
        else:
            result['answer'] = "Failed to generate response."
            result['formatted_response'] = result['answer'] + "\n"

        return result

    def _find_relevant_files(self, query: str, limit: int) -> List[Dict]:
        """Find files relevant to the query using embeddings."""
        if not self.kg:
            return []

        # Try to get query embedding
        try:
            from .embedder import EmbeddingGenerator, cosine_similarity
            embedder = EmbeddingGenerator()
            if not embedder.is_available:
                # Fall back to text search
                return self._text_search_files(query, limit)

            query_vec = embedder.generate(query)
            if not query_vec:
                return self._text_search_files(query, limit)

            # Find similar files
            cursor = self.kg.conn.cursor()
            cursor.execute("""
                SELECT f.id, f.path, f.extracted_text, f.summary, e.vector
                FROM files f
                JOIN embeddings e ON f.embedding_id = e.id
                WHERE e.vector IS NOT NULL
            """)

            results = []
            for row in cursor.fetchall():
                file_vec = row['vector']
                sim = cosine_similarity(query_vec, file_vec)
                if sim > 0.1:
                    results.append({
                        'id': row['id'],
                        'path': row['path'],
                        'text': row['extracted_text'] or "",
                        'summary': row['summary'] or "",
                        'similarity': sim
                    })

            results.sort(key=lambda x: x['similarity'], reverse=True)
            return results[:limit]

        except Exception as e:
            logger.error(f"Embedding search failed: {e}")
            return self._text_search_files(query, limit)

    def _text_search_files(self, query: str, limit: int) -> List[Dict]:
        """Fall back to text search if embeddings unavailable."""
        if not self.kg:
            return []

        cursor = self.kg.conn.cursor()
        like_pattern = f"%{query}%"

        cursor.execute("""
            SELECT id, path, extracted_text, summary
            FROM files
            WHERE extracted_text LIKE ? OR path LIKE ? OR summary LIKE ?
            ORDER BY modified_at DESC
            LIMIT ?
        """, (like_pattern, like_pattern, like_pattern, limit))

        return [{
            'id': row['id'],
            'path': row['path'],
            'text': row['extracted_text'] or "",
            'summary': row['summary'] or "",
            'similarity': 0.5  # Default similarity for text matches
        } for row in cursor.fetchall()]

    def _build_context(self, files: List[Dict], max_chars: int = 1500) -> str:
        """Build context string from files."""
        context_parts = []
        total_chars = 0

        for f in files:
            # Use summary if available, otherwise use extracted text
            content = f.get('summary') or f.get('text', "")
            if not content:
                continue

            # Truncate individual file content if needed
            if len(content) > 800:
                content = content[:800] + "..."

            file_context = f"[{f['path']}]\n{content}\n"

            if total_chars + len(file_context) > max_chars:
                break

            context_parts.append(file_context)
            total_chars += len(file_context)

        return "\n".join(context_parts)

    def _find_relevant_entities(self, query: str, context_files: List[Dict],
                                 max_entities: int = 10) -> str:
        """
        Find entities relevant to the query from the knowledge graph.

        Returns:
            Formatted string of entity context
        """
        context, _, _ = self._find_relevant_entities_detailed(query, context_files, max_entities)
        return context

    def _find_relevant_entities_detailed(self, query: str, context_files: List[Dict],
                                          max_entities: int = 10) -> tuple:
        """
        Find entities relevant to the query with full details for transparency.

        Searches for:
        1. Entities matching query terms via FTS5
        2. Entities extracted from relevant files
        3. Related entities via relationships

        Args:
            query: The user's question
            context_files: Files already found as relevant
            max_entities: Maximum entities to include

        Returns:
            Tuple of (context_string, entities_list, relationships_list)
        """
        if not self.kg:
            return "", [], []

        entities_list = []  # For transparency output
        relationships_list = []  # For transparency output

        try:
            entities_found = {}  # id -> (entity, source)
            relationships_found = []

            # 1. Search for entities matching query terms
            try:
                # FTS5 search for entities
                matched_entities = self.kg.search_entities(query, limit=5)
                for entity in matched_entities:
                    if entity.id not in entities_found:
                        entities_found[entity.id] = (entity, "query_match")
            except Exception as e:
                logger.debug(f"Entity FTS search failed: {e}")

            # 2. Get entities from relevant files
            for f in context_files[:3]:  # Limit to top 3 files
                file_id = f.get('id')
                if not file_id:
                    continue
                try:
                    file_entities = self.kg.get_file_entities(file_id)
                    for entity, rel_type, confidence in file_entities[:5]:
                        if entity.id not in entities_found:
                            entities_found[entity.id] = (entity, f"from:{f['path']}")
                except Exception as e:
                    logger.debug(f"File entity lookup failed: {e}")

            # 3. Get related entities for high-confidence matches
            top_entity_ids = list(entities_found.keys())[:3]
            for eid in top_entity_ids:
                try:
                    related = self.kg.get_related_entities(eid, depth=1)
                    for rel_entity in related[:3]:
                        if rel_entity.id not in entities_found:
                            entities_found[rel_entity.id] = (rel_entity, "related")

                    # Get direct relationships for context
                    rels = self.kg.get_relationships(eid)
                    for rel in rels[:5]:
                        source_entity = self.kg.get_entity_by_id(rel.source_id)
                        target_entity = self.kg.get_entity_by_id(rel.target_id)
                        if source_entity and target_entity:
                            relationships_found.append(
                                (source_entity.name, rel.relation_type.value, target_entity.name)
                            )
                except Exception as e:
                    logger.debug(f"Related entity lookup failed: {e}")

            # Build entity context string
            if not entities_found and not relationships_found:
                return "", [], []

            context_parts = []

            # Add entities section and build transparency list
            if entities_found:
                context_parts.append("Entities:")
                for eid, (entity, source) in list(entities_found.items())[:max_entities]:
                    desc = entity.description[:100] + "..." if len(entity.description) > 100 else entity.description
                    line = f"  - {entity.name} ({entity.entity_type.value})"
                    if desc:
                        line += f": {desc}"
                    context_parts.append(line)
                    # Add to transparency list
                    entities_list.append({
                        'name': entity.name,
                        'type': entity.entity_type.value,
                        'source': source,
                        'refs': entity.source_count
                    })

            # Add relationships section and build transparency list
            if relationships_found:
                context_parts.append("\nRelationships:")
                seen = set()
                for src, rel, tgt in relationships_found[:10]:
                    key = (src, rel, tgt)
                    if key not in seen:
                        seen.add(key)
                        context_parts.append(f"  - {src} → {rel} → {tgt}")
                        # Add to transparency list
                        relationships_list.append({
                            'source': src,
                            'relation': rel,
                            'target': tgt
                        })

            return "\n".join(context_parts), entities_list, relationships_list

        except Exception as e:
            logger.error(f"Entity context building failed: {e}")
            return "", [], []


class FileSummarizer:
    """Generate AI summaries of files."""

    SYSTEM_PROMPT = """You are a helpful assistant that creates concise summaries.
Summarize the key points of the provided content in 2-3 sentences.
Focus on the main topics, important facts, and actionable items."""

    def __init__(self, llm_client: OllamaClient):
        self.llm = llm_client

    def summarize(self, content: str, file_path: str = None) -> str:
        """
        Generate a summary of file content.

        Args:
            content: File content to summarize
            file_path: Optional file path for context

        Returns:
            Summary string
        """
        if not self.llm.is_available:
            return "LLM not available for summarization.\n"

        if not content or not content.strip():
            return "File is empty or has no text content.\n"

        # Truncate very long content
        if len(content) > 8000:
            content = content[:8000] + "\n\n[Content truncated...]"

        prompt = f"""Summarize the following content:

{content}

Summary:"""

        response = self.llm.generate(
            prompt,
            system=self.SYSTEM_PROMPT,
            temperature=0.3,  # Lower temperature for more focused summaries
            max_tokens=256
        )

        if response:
            return response.content

        return "Failed to generate summary.\n"


# Singleton instances
_ollama_client = None
_query_engine = None
_summarizer = None


def get_ollama_client() -> OllamaClient:
    """Get or create Ollama client singleton."""
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client


def get_query_engine(knowledge_graph) -> KnowledgeQueryEngine:
    """Get or create query engine singleton."""
    global _query_engine
    if _query_engine is None or _query_engine.kg != knowledge_graph:
        _query_engine = KnowledgeQueryEngine(knowledge_graph, get_ollama_client())
    return _query_engine


def get_summarizer() -> FileSummarizer:
    """Get or create summarizer singleton."""
    global _summarizer
    if _summarizer is None:
        _summarizer = FileSummarizer(get_ollama_client())
    return _summarizer
