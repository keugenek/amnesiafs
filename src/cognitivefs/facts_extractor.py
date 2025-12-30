"""
LLM-based Facts Extractor

Extracts structured facts (subject-predicate-object triples) from text using LLM.
"""

import json
import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class FactsExtractor:
    """Extract structured facts from text using LLM."""

    SYSTEM_PROMPT = """You are a fact extraction assistant. Extract structured facts from text.
Output ONLY valid JSON with no additional text or explanation."""

    EXTRACTION_PROMPT = """Extract structured facts from this text as a JSON array.

TEXT:
{content}

Output format (respond with ONLY this JSON, no other text):
{{
  "facts": [
    {{"subject": "entity1", "predicate": "relationship", "object": "entity2", "confidence": 0.9}}
  ]
}}

Rules:
1. Extract only explicit facts clearly stated in the text
2. Use normalized predicates: works_at, created, founded, located_in, part_of, discusses, mentions, depends_on, authored_by, related_to
3. Confidence: 0.9+ for explicit, 0.7-0.9 for implied
4. Maximum 15 facts
5. Subject and object should be specific named entities
6. Skip trivial facts

JSON:"""

    def __init__(self, llm_client):
        self.llm = llm_client

    def extract_facts(self, content: str, file_path: str = None) -> List[Dict[str, Any]]:
        """
        Extract facts from text content.

        Args:
            content: Text content to extract facts from
            file_path: Optional file path for context

        Returns:
            List of fact dictionaries with subject, predicate, object, confidence
        """
        if not self.llm.is_available:
            logger.warning("LLM not available for facts extraction")
            return []

        if not content or len(content.strip()) < 50:
            return []

        # Truncate very long content
        if len(content) > 6000:
            content = content[:6000] + " [truncated]"

        prompt = self.EXTRACTION_PROMPT.format(content=content)

        try:
            response = self.llm.generate(
                prompt,
                system=self.SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=1024
            )

            if not response or not response.content:
                return []

            # Parse JSON response
            facts = self._parse_facts_response(response.content)

            # Filter and validate facts
            valid_facts = []
            for fact in facts:
                if self._is_valid_fact(fact):
                    valid_facts.append({
                        'subject': fact.get('subject', '').strip(),
                        'predicate': self._normalize_predicate(fact.get('predicate', '')),
                        'object': fact.get('object', '').strip(),
                        'confidence': min(1.0, max(0.0, float(fact.get('confidence', 0.8))))
                    })

            logger.debug(f"Extracted {len(valid_facts)} facts from {file_path or 'content'}")
            return valid_facts

        except Exception as e:
            logger.error(f"Facts extraction failed: {e}")
            return []

    def _parse_facts_response(self, response: str) -> List[Dict]:
        """Parse LLM response to extract facts JSON."""
        response = response.strip()

        # Try direct parse first
        try:
            data = json.loads(response)
            if isinstance(data, dict) and 'facts' in data:
                return data['facts']
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code block
        json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', response)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if isinstance(data, dict) and 'facts' in data:
                    return data['facts']
            except json.JSONDecodeError:
                pass

        # Try to find JSON object anywhere in response
        json_match = re.search(r'\{[\s\S]*"facts"[\s\S]*\}', response)
        if json_match:
            try:
                data = json.loads(json_match.group())
                if 'facts' in data:
                    return data['facts']
            except json.JSONDecodeError:
                pass

        logger.warning(f"Could not parse facts from response: {response[:200]}")
        return []

    def _is_valid_fact(self, fact: Dict) -> bool:
        """Check if a fact is valid and meaningful."""
        if not isinstance(fact, dict):
            return False

        subject = fact.get('subject', '').strip()
        predicate = fact.get('predicate', '').strip()
        obj = fact.get('object', '').strip()

        if not subject or not predicate or not obj:
            return False

        if len(subject) < 2 or len(obj) < 2:
            return False

        generic_subjects = {'this', 'it', 'the document', 'the file', 'the text', 'document'}
        if subject.lower() in generic_subjects:
            return False

        return True

    def _normalize_predicate(self, predicate: str) -> str:
        """Normalize predicate to standard form."""
        predicate = predicate.strip().lower().replace(' ', '_')

        normalizations = {
            'works_for': 'works_at',
            'employed_by': 'works_at',
            'employee_of': 'works_at',
            'made': 'created',
            'built': 'created',
            'developed': 'created',
            'wrote': 'authored_by',
            'written_by': 'authored_by',
            'is_in': 'located_in',
            'based_in': 'located_in',
            'contains': 'includes',
            'has': 'includes',
            'is_a': 'is_type',
            'is_an': 'is_type',
            'talks_about': 'discusses',
            'about': 'discusses',
            'references': 'mentions',
            'uses': 'depends_on',
            'requires': 'depends_on',
            'needs': 'depends_on',
        }

        return normalizations.get(predicate, predicate)


# Singleton instance
_facts_extractor = None


def get_facts_extractor():
    """Get or create facts extractor singleton."""
    global _facts_extractor
    if _facts_extractor is None:
        from .llm import get_ollama_client
        _facts_extractor = FactsExtractor(get_ollama_client())
    return _facts_extractor
