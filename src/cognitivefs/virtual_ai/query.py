"""
Query handler for /.ai/query/ (async LLM queries)
"""

import time
import threading
from typing import Optional, Dict, List
from .base import BaseHandler


class QueryHandler(BaseHandler):
    """Handles /.ai/query/ virtual paths for async LLM queries."""

    def __init__(self, cognitivefs=None, knowledge_graph=None):
        """Initialize query handler with async state."""
        super().__init__(cognitivefs, knowledge_graph)
        self._query_results: Dict[str, Dict] = {}  # query_id -> {status, result, query}
        self._query_counter = 0
        self._query_lock = threading.Lock()

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for query paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files and editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        # Any path under /.ai/query/ is a valid query file
        return self._make_file_stat(4096, now)

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """List query help."""
        if not target_path:
            return ["_help.txt"]
        return []

    def read(self, target_path: str, parts: List[str]) -> bytes:
        """
        Read query response.

        Usage: cat /.ai/query/<query_text>
        Replace spaces with underscores or + in the query.
        Example: cat /.ai/query/what_is_machine_learning
        """
        if not target_path:
            return b""

        if target_path == "/_help.txt" or target_path == "_help.txt":
            return self._get_query_help()

        # Convert path to query text
        query_text = target_path.lstrip("/").replace("_", " ").replace("+", " ").replace("-", " ")
        return self._process_query(query_text).encode('utf-8')

    def _get_query_help(self) -> bytes:
        """Return help text for query."""
        return b"""# Natural Language Query Interface (Async)

## Usage

Submit a query (returns immediately with ID):
    cat /.ai/query/what_is_machine_learning

Check results (poll until complete):
    cat /.ai/query/results/q1

List all queries:
    cat /.ai/query/pending

## How It Works

1. Query is queued and processed in background (non-blocking)
2. Returns query ID immediately
3. Poll results endpoint until status is 'complete'
4. LLM generates answer using indexed file context

## Tips

- Use underscores (_) for spaces in query path
- Queries run in background - won't freeze filesystem
- Results are cached until filesystem restart
"""

    def _process_query(self, query: str) -> str:
        """
        Process a natural language query - queues for async processing.

        Returns immediately with query ID. Check results via:
          cat /.ai/query/results/<id>
        """
        if not query:
            return "Please enter a query.\n"

        # Check if this is a results request
        if query.startswith("results/"):
            query_id = query[8:]
            return self._get_query_result(query_id)

        # Check if this is a debug request (shows context used)
        if query.startswith("debug/"):
            query_id = query[6:]
            return self._get_query_debug(query_id)

        # Check if listing pending queries
        if query == "pending":
            return self._list_pending_queries()

        # Queue new query
        query_id = self._queue_async_query(query)
        return f"Query queued with ID: {query_id}\n\nCheck results:\n  cat /.ai/query/results/{query_id}\n\nView context used:\n  cat /.ai/query/debug/{query_id}\n\nList pending:\n  cat /.ai/query/pending\n"

    def _queue_async_query(self, query: str) -> str:
        """Queue a query for async processing."""
        with self._query_lock:
            self._query_counter += 1
            query_id = f"q{self._query_counter}"
            self._query_results[query_id] = {
                'status': 'pending',
                'query': query,
                'result': None,
                'timestamp': time.time()
            }

        # Start background thread for this query
        thread = threading.Thread(
            target=self._run_async_query,
            args=(query_id, query),
            daemon=True
        )
        thread.start()

        return query_id

    def _run_async_query(self, query_id: str, query: str):
        """Run query in background thread."""
        try:
            from ..llm import get_query_engine

            engine = get_query_engine(self.knowledge_graph)
            # Use query_with_context for full transparency
            result_data = engine.query_with_context(query)

            with self._query_lock:
                if query_id in self._query_results:
                    self._query_results[query_id]['status'] = 'complete'
                    self._query_results[query_id]['result'] = result_data.get('formatted_response', '')
                    # Store full context for debug endpoint
                    self._query_results[query_id]['context'] = {
                        'files_used': result_data.get('files_used', []),
                        'entities_used': result_data.get('entities_used', []),
                        'relationships_used': result_data.get('relationships_used', []),
                        'llm_available': result_data.get('llm_available', False)
                    }

        except Exception as e:
            with self._query_lock:
                if query_id in self._query_results:
                    self._query_results[query_id]['status'] = 'error'
                    self._query_results[query_id]['result'] = f"Error: {e}"

    def _get_query_result(self, query_id: str) -> str:
        """Get result of async query."""
        with self._query_lock:
            if query_id not in self._query_results:
                return f"Query ID not found: {query_id}\n"

            info = self._query_results[query_id]

            # Expire old results after 24 hours
            if time.time() - info.get('timestamp', 0) > 86400:
                del self._query_results[query_id]
                return f"Query {query_id} expired. Please rerun your query.\n"

            status = info['status']
            query = info['query']

            if status == 'pending':
                return f"Query '{query}' is still processing...\n\nTry again in a few seconds:\n  cat /.ai/query/results/{query_id}\n"
            elif status == 'complete':
                return info['result']
            else:
                return info['result']

    def _get_query_debug(self, query_id: str) -> str:
        """Get debug info showing context used for a query."""
        with self._query_lock:
            if query_id not in self._query_results:
                return f"Query ID not found: {query_id}\n"

            info = self._query_results[query_id]
            status = info['status']
            query = info['query']

            if status == 'pending':
                return f"Query '{query}' is still processing...\n\nTry again in a few seconds.\n"

            lines = [
                f"# Query Debug: {query_id}",
                f"Question: {query}",
                f"Status: {status}",
                ""
            ]

            context = info.get('context', {})

            # Files used
            files_used = context.get('files_used', [])
            lines.append(f"## Files Used ({len(files_used)})")
            if files_used:
                for f in files_used:
                    sim = f.get('similarity', 0)
                    lines.append(f"  - {f['path']} (similarity: {sim:.3f})")
            else:
                lines.append("  (none)")
            lines.append("")

            # Entities used
            entities_used = context.get('entities_used', [])
            lines.append(f"## Entities Used ({len(entities_used)})")
            if entities_used:
                for e in entities_used:
                    lines.append(f"  - {e['name']} ({e['type']})")
            else:
                lines.append("  (none)")
            lines.append("")

            # LLM status
            llm_available = context.get('llm_available', False)
            lines.append(f"## LLM Available: {'Yes' if llm_available else 'No'}")
            if not llm_available:
                lines.append("  Answer was generated from indexed context only.")
            lines.append("")

            return "\n".join(lines)

    def _list_pending_queries(self) -> str:
        """List all pending/completed queries."""
        with self._query_lock:
            if not self._query_results:
                return "No queries in queue.\n"

            lines = ["# Query Queue", ""]

            for query_id, info in sorted(self._query_results.items()):
                status = info['status']
                query = info['query'][:50]
                ts = info.get('timestamp', 0)
                age = int(time.time() - ts)
                lines.append(f"  [{status}] {query_id}: {query}... ({age}s ago)")

            lines.append("")
            lines.append("Check result: cat /.ai/query/results/<id>")

            return "\n".join(lines)
