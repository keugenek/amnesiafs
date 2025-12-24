"""
Content and Entity Extraction Module

Extracts text content from various file types and identifies named entities
using regex-based pattern matching. Supports text, code, and config files.
"""

import re
import hashlib
import mimetypes
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ExtractedEntityType(Enum):
    """Types of entities that can be extracted."""
    PERSON = "person"
    ORGANIZATION = "organization"
    EMAIL = "email"
    URL = "url"
    DATE = "date"
    HASHTAG = "hashtag"
    CODE_CLASS = "code_class"
    CODE_FUNCTION = "code_function"
    FILE_PATH = "file_path"
    KEYWORD = "keyword"


@dataclass
class ExtractedEntity:
    """Represents an extracted entity."""
    entity_type: ExtractedEntityType
    value: str
    confidence: float = 1.0
    context: str = ""  # Surrounding text
    position: int = 0  # Byte offset in content


@dataclass
class ExtractionResult:
    """Result of content extraction."""
    text: str = ""
    mime_type: str = "text/plain"
    content_hash: str = ""
    entities: List[ExtractedEntity] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# MIME type mappings for common extensions
EXTENSION_MIME_MAP = {
    # Text
    '.txt': 'text/plain',
    '.md': 'text/markdown',
    '.rst': 'text/x-rst',
    '.log': 'text/plain',

    # Code
    '.py': 'text/x-python',
    '.js': 'text/javascript',
    '.ts': 'text/typescript',
    '.jsx': 'text/javascript',
    '.tsx': 'text/typescript',
    '.go': 'text/x-go',
    '.rs': 'text/x-rust',
    '.c': 'text/x-c',
    '.cpp': 'text/x-c++',
    '.h': 'text/x-c',
    '.hpp': 'text/x-c++',
    '.java': 'text/x-java',
    '.rb': 'text/x-ruby',
    '.php': 'text/x-php',
    '.sh': 'text/x-shellscript',
    '.bash': 'text/x-shellscript',
    '.zsh': 'text/x-shellscript',
    '.ps1': 'text/x-powershell',
    '.sql': 'text/x-sql',
    '.r': 'text/x-r',
    '.scala': 'text/x-scala',
    '.kt': 'text/x-kotlin',
    '.swift': 'text/x-swift',
    '.lua': 'text/x-lua',
    '.pl': 'text/x-perl',
    '.cs': 'text/x-csharp',
    '.fs': 'text/x-fsharp',
    '.clj': 'text/x-clojure',
    '.ex': 'text/x-elixir',
    '.erl': 'text/x-erlang',
    '.hs': 'text/x-haskell',
    '.ml': 'text/x-ocaml',
    '.nim': 'text/x-nim',
    '.zig': 'text/x-zig',
    '.v': 'text/x-v',
    '.d': 'text/x-d',

    # Config
    '.json': 'application/json',
    '.yaml': 'text/yaml',
    '.yml': 'text/yaml',
    '.toml': 'text/x-toml',
    '.ini': 'text/x-ini',
    '.cfg': 'text/x-ini',
    '.conf': 'text/plain',
    '.env': 'text/plain',
    '.xml': 'text/xml',
    '.csv': 'text/csv',
    '.tsv': 'text/tab-separated-values',

    # Documents
    '.html': 'text/html',
    '.htm': 'text/html',
    '.css': 'text/css',
    '.scss': 'text/x-scss',
    '.sass': 'text/x-sass',
    '.less': 'text/x-less',

    # Data
    '.graphql': 'text/x-graphql',
    '.proto': 'text/x-protobuf',
}

# Text-based MIME types that can be directly read
TEXT_MIME_TYPES = {
    'text/', 'application/json', 'application/xml',
    'application/javascript', 'application/typescript',
}


class ContentExtractor:
    """
    Extract text content from various file types.

    Supports text, code, and configuration files. Binary files
    are skipped with empty text result.
    """

    def __init__(self):
        # Initialize mimetypes database
        mimetypes.init()

    def extract(self, path: str, data: bytes) -> ExtractionResult:
        """
        Extract content from file data.

        Args:
            path: File path (used for extension-based type detection)
            data: Raw file content

        Returns:
            ExtractionResult with text, mime_type, hash, and metadata
        """
        result = ExtractionResult()

        # Compute content hash
        result.content_hash = hashlib.sha256(data).hexdigest()

        # Detect MIME type
        result.mime_type = self._detect_mime_type(path, data)

        # Extract text based on MIME type
        result.text = self._extract_text(data, result.mime_type)

        # Add metadata
        result.metadata['size'] = len(data)
        result.metadata['encoding'] = self._detect_encoding(data)

        return result

    def _detect_mime_type(self, path: str, data: bytes) -> str:
        """Detect MIME type from extension and content."""
        # Try extension first
        ext = Path(path).suffix.lower()
        if ext in EXTENSION_MIME_MAP:
            return EXTENSION_MIME_MAP[ext]

        # Fall back to mimetypes library
        mime_type, _ = mimetypes.guess_type(path)
        if mime_type:
            return mime_type

        # Try magic bytes detection for common formats
        if data[:4] == b'%PDF':
            return 'application/pdf'
        if data[:2] == b'PK':
            return 'application/zip'
        if data[:3] == b'\xff\xd8\xff':
            return 'image/jpeg'
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return 'image/png'
        if data[:4] == b'GIF8':
            return 'image/gif'
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return 'image/webp'

        # Check if it looks like text
        if self._is_text(data):
            return 'text/plain'

        return 'application/octet-stream'

    def _is_text(self, data: bytes, sample_size: int = 8192) -> bool:
        """Check if data appears to be text."""
        sample = data[:sample_size]

        # Check for null bytes (binary indicator)
        if b'\x00' in sample:
            return False

        # Try to decode as UTF-8
        try:
            sample.decode('utf-8')
            return True
        except UnicodeDecodeError:
            pass

        # Try Latin-1 (always succeeds but check for control chars)
        try:
            text = sample.decode('latin-1')
            # Count control characters (excluding common ones)
            control_count = sum(1 for c in text if ord(c) < 32 and c not in '\n\r\t')
            return control_count / len(text) < 0.1 if text else True
        except:
            return False

    def _detect_encoding(self, data: bytes) -> str:
        """Detect text encoding."""
        # Check BOM
        if data[:3] == b'\xef\xbb\xbf':
            return 'utf-8-sig'
        if data[:2] == b'\xff\xfe':
            return 'utf-16-le'
        if data[:2] == b'\xfe\xff':
            return 'utf-16-be'

        # Try UTF-8
        try:
            data.decode('utf-8')
            return 'utf-8'
        except UnicodeDecodeError:
            pass

        # Default to Latin-1
        return 'latin-1'

    def _extract_text(self, data: bytes, mime_type: str) -> str:
        """Extract text based on MIME type."""
        # Check if it's a text type
        is_text = any(mime_type.startswith(t) for t in TEXT_MIME_TYPES)
        if not is_text and mime_type not in EXTENSION_MIME_MAP.values():
            # Binary file - return empty
            return ""

        # Decode text
        encoding = self._detect_encoding(data)
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            text = data.decode('latin-1', errors='replace')

        # Strip BOM if present
        if text.startswith('\ufeff'):
            text = text[1:]

        # Handle HTML - strip tags
        if mime_type == 'text/html':
            text = self._strip_html_tags(text)

        return text

    def _strip_html_tags(self, html: str) -> str:
        """Remove HTML tags, keeping text content."""
        # Remove script and style elements
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove tags
        html = re.sub(r'<[^>]+>', ' ', html)

        # Decode entities
        html = html.replace('&nbsp;', ' ')
        html = html.replace('&lt;', '<')
        html = html.replace('&gt;', '>')
        html = html.replace('&amp;', '&')
        html = html.replace('&quot;', '"')

        # Collapse whitespace
        html = re.sub(r'\s+', ' ', html)

        return html.strip()


class EntityExtractor:
    """
    Extract named entities from text using regex patterns.

    Extracts: emails, URLs, dates, hashtags, capitalized phrases
    (likely proper nouns), and code identifiers.
    """

    # Regex patterns for entity extraction
    PATTERNS = {
        ExtractedEntityType.EMAIL: re.compile(
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        ),
        ExtractedEntityType.URL: re.compile(
            r'https?://[^\s<>"\']+|www\.[^\s<>"\']+\.[^\s<>"\']+'
        ),
        ExtractedEntityType.HASHTAG: re.compile(
            r'#[A-Za-z][A-Za-z0-9_]*'
        ),
        ExtractedEntityType.FILE_PATH: re.compile(
            r'(?:[A-Za-z]:\\|/)[^\s<>"\'|*?]+|\.{1,2}/[^\s<>"\'|*?]+'
        ),
    }

    # Date patterns (multiple formats)
    DATE_PATTERNS = [
        # ISO format: 2024-01-15
        re.compile(r'\b\d{4}-\d{2}-\d{2}\b'),
        # US format: 01/15/2024 or 1/15/24
        re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b'),
        # EU format: 15.01.2024
        re.compile(r'\b\d{1,2}\.\d{1,2}\.\d{2,4}\b'),
        # Written format: January 15, 2024 or Jan 15, 2024
        re.compile(
            r'\b(?:January|February|March|April|May|June|July|August|'
            r'September|October|November|December|'
            r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
            r'\s+\d{1,2},?\s+\d{4}\b',
            re.IGNORECASE
        ),
    ]

    # Code identifier patterns
    CODE_PATTERNS = {
        ExtractedEntityType.CODE_CLASS: [
            re.compile(r'\bclass\s+([A-Z][A-Za-z0-9_]*)\b'),  # Python/Java/JS
            re.compile(r'\bstruct\s+([A-Z][A-Za-z0-9_]*)\b'),  # C/Go/Rust
            re.compile(r'\binterface\s+([A-Z][A-Za-z0-9_]*)\b'),  # Java/TS
            re.compile(r'\benum\s+([A-Z][A-Za-z0-9_]*)\b'),  # Various
            re.compile(r'\btype\s+([A-Z][A-Za-z0-9_]*)\b'),  # Go/TS
        ],
        ExtractedEntityType.CODE_FUNCTION: [
            re.compile(r'\bdef\s+([a-z_][a-z0-9_]*)\b'),  # Python
            re.compile(r'\bfunction\s+([a-zA-Z_][a-zA-Z0-9_]*)\b'),  # JS
            re.compile(r'\bfn\s+([a-z_][a-z0-9_]*)\b'),  # Rust
            re.compile(r'\bfunc\s+([a-zA-Z_][a-zA-Z0-9_]*)\b'),  # Go
            re.compile(r'\basync\s+def\s+([a-z_][a-z0-9_]*)\b'),  # Python async
        ],
    }

    # Proper noun pattern (capitalized phrases)
    PROPER_NOUN_PATTERN = re.compile(
        r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b'
    )

    # Common words to exclude from proper nouns
    COMMON_WORDS = {
        'The', 'This', 'That', 'These', 'Those', 'There', 'Here',
        'What', 'When', 'Where', 'Which', 'Who', 'How', 'Why',
        'If', 'Then', 'But', 'And', 'Or', 'Not', 'So', 'As',
        'For', 'From', 'To', 'In', 'On', 'At', 'By', 'With',
        'It', 'Is', 'Are', 'Was', 'Were', 'Be', 'Been', 'Being',
        'Have', 'Has', 'Had', 'Do', 'Does', 'Did', 'Will', 'Would',
        'Could', 'Should', 'May', 'Might', 'Must', 'Can',
        'New', 'First', 'Last', 'Next', 'Now', 'Today', 'Tomorrow',
    }

    # Stop words for keyword extraction
    STOP_WORDS = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'must', 'can', 'this', 'that',
        'these', 'those', 'it', 'its', 'if', 'then', 'so', 'than', 'such',
        'no', 'not', 'only', 'same', 'too', 'very', 'just', 'also', 'now',
        'here', 'there', 'when', 'where', 'why', 'how', 'what', 'which', 'who',
        'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other', 'some',
        'any', 'into', 'through', 'during', 'before', 'after', 'above', 'below',
        'between', 'under', 'again', 'further', 'once', 'about', 'out', 'over',
        'up', 'down', 'off', 'your', 'you', 'i', 'me', 'my', 'we', 'our', 'they',
        'their', 'them', 'he', 'she', 'him', 'her', 'his', 'hers',
    }

    def __init__(self):
        pass

    def extract_entities(self, text: str) -> List[ExtractedEntity]:
        """
        Extract all entities from text.

        Args:
            text: Input text to analyze

        Returns:
            List of extracted entities
        """
        entities = []

        # Extract using direct patterns
        for entity_type, pattern in self.PATTERNS.items():
            for match in pattern.finditer(text):
                entities.append(ExtractedEntity(
                    entity_type=entity_type,
                    value=match.group(),
                    position=match.start(),
                    context=self._get_context(text, match.start(), match.end())
                ))

        # Extract dates
        for pattern in self.DATE_PATTERNS:
            for match in pattern.finditer(text):
                entities.append(ExtractedEntity(
                    entity_type=ExtractedEntityType.DATE,
                    value=match.group(),
                    position=match.start(),
                    context=self._get_context(text, match.start(), match.end())
                ))

        # Extract code identifiers
        for entity_type, patterns in self.CODE_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    entities.append(ExtractedEntity(
                        entity_type=entity_type,
                        value=match.group(1),  # Capture group
                        position=match.start(),
                        context=self._get_context(text, match.start(), match.end())
                    ))

        # Extract proper nouns (potential persons/organizations)
        for match in self.PROPER_NOUN_PATTERN.finditer(text):
            value = match.group()
            # Filter out common phrases
            words = value.split()
            if words[0] not in self.COMMON_WORDS:
                # Classify as person (2 words) or organization (3+ words)
                entity_type = (ExtractedEntityType.PERSON
                              if len(words) == 2
                              else ExtractedEntityType.ORGANIZATION)
                entities.append(ExtractedEntity(
                    entity_type=entity_type,
                    value=value,
                    confidence=0.7,  # Lower confidence for regex-based NER
                    position=match.start(),
                    context=self._get_context(text, match.start(), match.end())
                ))

        # Deduplicate entities
        return self._deduplicate_entities(entities)

    def extract_keywords(self, text: str, max_keywords: int = 20) -> List[str]:
        """
        Extract important keywords from text.

        Uses simple frequency-based extraction with stop word filtering.

        Args:
            text: Input text
            max_keywords: Maximum keywords to return

        Returns:
            List of keywords sorted by importance
        """
        # Tokenize: extract words
        words = re.findall(r'\b[a-z][a-z0-9_]*\b', text.lower())

        # Filter stop words and short words
        words = [w for w in words if w not in self.STOP_WORDS and len(w) > 2]

        # Count frequencies
        freq: Dict[str, int] = {}
        for word in words:
            freq[word] = freq.get(word, 0) + 1

        # Sort by frequency
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)

        # Return top keywords
        return [word for word, _ in sorted_words[:max_keywords]]

    def _get_context(self, text: str, start: int, end: int,
                     window: int = 50) -> str:
        """Get surrounding context for an entity."""
        ctx_start = max(0, start - window)
        ctx_end = min(len(text), end + window)

        context = text[ctx_start:ctx_end]

        # Clean up context
        if ctx_start > 0:
            context = '...' + context
        if ctx_end < len(text):
            context = context + '...'

        return context.replace('\n', ' ').strip()

    def _deduplicate_entities(self,
                              entities: List[ExtractedEntity]) -> List[ExtractedEntity]:
        """Remove duplicate entities, keeping highest confidence."""
        seen: Dict[tuple, ExtractedEntity] = {}

        for entity in entities:
            key = (entity.entity_type, entity.value.lower())
            if key not in seen or entity.confidence > seen[key].confidence:
                seen[key] = entity

        return list(seen.values())


def extract_all(path: str, data: bytes) -> ExtractionResult:
    """
    Convenience function to extract content and entities.

    Args:
        path: File path
        data: Raw file content

    Returns:
        ExtractionResult with text, entities, and keywords
    """
    content_extractor = ContentExtractor()
    entity_extractor = EntityExtractor()

    # Extract content
    result = content_extractor.extract(path, data)

    # Extract entities if we have text
    if result.text:
        result.entities = entity_extractor.extract_entities(result.text)
        result.keywords = entity_extractor.extract_keywords(result.text)

    return result
