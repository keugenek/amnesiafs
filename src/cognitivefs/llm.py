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

            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode('utf-8'))

            return LLMResponse(
                content=result.get("response", ""),
                model=result.get("model", self.model),
                done=result.get("done", True),
                total_duration=result.get("total_duration"),
                prompt_eval_count=result.get("prompt_eval_count"),
                eval_count=result.get("eval_count"),
            )

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

            with urllib.request.urlopen(req, timeout=60) as resp:
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
        if not self.llm.is_available:
            return "LLM not available. Please ensure Ollama is running.\n"

        # 1. Find relevant files using semantic search
        context_files = self._find_relevant_files(question, max_context_files)

        if not context_files:
            # No indexed files, still try to answer
            prompt = f"Question: {question}\n\nNo files have been indexed yet. Please let the user know they should add some files first."
            response = self.llm.generate(prompt, system=self.SYSTEM_PROMPT)
            if response:
                return response.content
            return "No files indexed and LLM unavailable.\n"

        # 2. Build context from files
        context = self._build_context(context_files)

        # 3. Generate answer
        prompt = f"""Context from your files:
{context}

Question: {question}

Answer based on the context above:"""

        response = self.llm.generate(prompt, system=self.SYSTEM_PROMPT, max_tokens=256)

        if response:
            # Add source references
            sources = "\n\nSources:\n" + "\n".join(f"  - {f['path']}" for f in context_files)
            return response.content + sources + "\n"

        return "Failed to generate response.\n"

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

    def _build_context(self, files: List[Dict], max_chars: int = 2000) -> str:
        """Build context string from files."""
        context_parts = []
        total_chars = 0

        for f in files:
            # Use summary if available, otherwise use extracted text
            content = f.get('summary') or f.get('text', "")
            if not content:
                continue

            # Truncate individual file content if needed
            if len(content) > 1000:
                content = content[:1000] + "..."

            file_context = f"[{f['path']}]\n{content}\n"

            if total_chars + len(file_context) > max_chars:
                break

            context_parts.append(file_context)
            total_chars += len(file_context)

        return "\n".join(context_parts)


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
