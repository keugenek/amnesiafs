"""
Chat handler for /.ai/chat/ (conversation sessions)
"""

import time
from typing import Optional, Dict, List
from .base import BaseHandler
from ..utils import format_timestamp


class ChatHandler(BaseHandler):
    """Handles /.ai/chat/ virtual paths for conversation sessions."""

    def __init__(self, cognitivefs=None, knowledge_graph=None):
        """Initialize chat handler with session state."""
        super().__init__(cognitivefs, knowledge_graph)
        self.chat_sessions: Dict[str, List[Dict]] = {}  # session_name -> messages

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for chat paths."""
        now = int(time.time())

        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files and editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        if len(parts) == 2:
            session_name = parts[1]
            # Get chat history content
            content = self._get_chat_content(session_name)
            return self._make_file_stat(len(content), now, writable=True)

        return None

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """List chat sessions."""
        if not target_path:
            return list(self.chat_sessions.keys()) if self.chat_sessions else ["_help.txt"]
        return []

    def read(self, target_path: str, parts: List[str]) -> bytes:
        """Read chat session history."""
        if not target_path:
            return self._get_chat_help()

        if target_path == "_help.txt":
            return self._get_chat_help()

        if len(parts) == 2:
            session_name = parts[1]
            return self._get_chat_content(session_name)
        return b""

    def write(self, target_path: str, parts: List[str], data: bytes, offset: int) -> int:
        """Write to chat session (send message)."""
        if len(parts) == 2:
            session_name = parts[1]
            message = data.decode('utf-8', errors='replace').strip()

            if message:
                # Add user message
                if session_name not in self.chat_sessions:
                    self.chat_sessions[session_name] = []

                self.chat_sessions[session_name].append({
                    "role": "user",
                    "content": message,
                    "timestamp": time.time(),
                })

                # Generate AI response (placeholder)
                response = self._generate_chat_response(session_name, message)
                self.chat_sessions[session_name].append({
                    "role": "assistant",
                    "content": response,
                    "timestamp": time.time(),
                })

            return len(data)
        return 0

    def _get_chat_help(self) -> bytes:
        """Return help text for chat interface."""
        return b"""# Chat Interface

## Usage

Start or continue a chat session:
    cat /.ai/chat/my_session          # Read chat history
    echo "Hello" > /.ai/chat/my_session   # Send a message

List all sessions:
    ls /.ai/chat/

## How It Works

1. Create a session by writing to /.ai/chat/<session_name>
2. Read the file to see conversation history
3. Write more messages to continue the conversation

## Notes

- Sessions are stored in memory (cleared on unmount)
- AI responses require LLM integration (placeholder for now)
- Multiple sessions can run simultaneously
"""

    def _get_chat_content(self, session_name: str) -> bytes:
        """Format chat session as readable text."""
        messages = self.chat_sessions.get(session_name, [])

        if not messages:
            return b"Chat session is empty. Write a message to start.\n"

        lines = [f"# Chat Session: {session_name}", ""]

        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            ts = msg.get("timestamp", 0)
            time_str = format_timestamp(ts, 'time') if ts else ""

            lines.append(f"[{time_str}] {role}:")
            lines.append(content)
            lines.append("")

        return "\n".join(lines).encode('utf-8')

    def _generate_chat_response(self, session_name: str, message: str) -> str:
        """
        Generate AI chat response.

        Placeholder until LLM integration is complete.
        """
        return (
            "AI chat responses not yet implemented.\n"
            "When complete, I'll be able to:\n"
            "  - Answer questions about your files\n"
            "  - Search the knowledge graph\n"
            "  - Help with file organization\n"
            "  - Provide summaries and insights\n"
        )
