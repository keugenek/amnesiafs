# CognitiveFS Changelog & Development History

## [2024-12-28] Phase A Complete: Structured File Extraction

### Summary
Added JSON/YAML/CSV parsing to extract structural entities (FIELD, COLUMN, SCHEMA_TYPE) with JSONPath context.

### Files Modified
- `src/cognitivefs/extractor.py` - Added structured parsing methods
- `src/cognitivefs/knowledge_graph.py` - Added new EntityType values
- `src/cognitivefs/processor.py` - Updated ENTITY_TYPE_MAP
- `tests/test_extractor.py` - Added 10 new tests

### Implementation Details

**New Entity Types:**
```python
class ExtractedEntityType(Enum):
    FIELD = "field"           # JSON/YAML keys
    COLUMN = "column"         # CSV headers
    SCHEMA_TYPE = "schema_type"  # Value type info
```

**JSON Entity Extraction:**
- Traverses nested objects recursively
- Creates FIELD entity for each key with JSONPath context (e.g., `user.address.city`)
- Creates SCHEMA_TYPE entity for value types (string, number, boolean, array, object)

**CSV Entity Extraction:**
- Extracts headers as COLUMN entities
- Context includes column index

**YAML Entity Extraction:**
- Same approach as JSON using PyYAML

### Tests Added
- `test_json_key_extraction` - Keys become FIELD entities
- `test_json_nested_paths` - context="user.address.city"
- `test_json_value_types` - SCHEMA_TYPE entities
- `test_json_array_traversal` - Array index notation
- `test_invalid_json_fallback` - Graceful degradation
- `test_csv_header_extraction` - COLUMN entities
- `test_csv_column_context` - Column index context
- `test_extract_all_json` - Full integration
- `test_extract_all_csv` - Full integration

### Commit
`3d4cac6` - feat: Add structured file extraction for JSON/YAML/CSV

---

## [2024-12-28] Real-World Usage Testing Session

### Context
Attempted to analyze a LinkedIn post draft using cognitive interface (/.ai/ virtual paths) without direct file reads.

### Index Stats
- Files indexed: 45
- Entities: 1,027
- Relationships: 68,060
- Embeddings: 107

### Endpoints Tested

**Working Well:**
| Endpoint | Result |
|----------|--------|
| `/.ai/graph/stats` | Returns index health metrics |
| `/.ai/search/<terms>` | Returns files with relevance scores + context snippets |

**Not Working:**
| Endpoint | Issue |
|----------|-------|
| `/.ai/query/<question>` | Returns "no files" despite indexed content |
| `/.ai/similar/<path>` | "File not indexed" for temp files |
| `/.ai/entities/<path>` | Path format unclear, returns errors |

### Root Cause Analysis

**Why Query Fails When Search Works:**

Search uses FTS5 (keyword matching):
```sql
SELECT f.path FROM files f
JOIN files_fts fts ON f.id = fts.rowid
WHERE files_fts MATCH ?  -- No embedding dependency
```

Query uses embeddings (semantic similarity):
```sql
SELECT f.id, f.path FROM files f
JOIN embeddings e ON f.embedding_id = e.id  -- INNER JOIN excludes files without embeddings
WHERE e.vector IS NOT NULL
```

**Embedding Coverage Issues:**
- 45 files indexed, only 40 have embeddings (88%)
- 107 total embeddings for 40 files (2.7x duplication - no UNIQUE constraint)
- 5 files missing embeddings: 4 are `.tmp.*` temp files

**Silent Failure Points:**
1. `processor.py:298` - No logging when embedding returns None
2. `processor.py:292-294` - Only DEBUG level for unavailable embedder
3. `embedder.py:116-118` - Exception logged but caller doesn't know why

### Bugs Identified
- BUG-001: Query uses INNER JOIN excluding files without embeddings
- BUG-002: Stale query results persist across sessions
- BUG-003: Temp files (.tmp.*) not embedded
- BUG-004: No embedding coverage visibility in status
- BUG-005: Entity browsing paths broken
- BUG-006: Graph entity type listing not implemented
- BUG-013: Silent embedding failures
- BUG-014: Duplicate embeddings per file

### Successful Workflow Discovered
```
1. /.ai/graph/stats      → Verify index populated
2. /.ai/search/<terms>   → Find files + snippets
3. (snippets often enough for analysis)
4. Direct read only if needed
```

---

## Previously Completed Features

### Tier 1 (P1+P2)
- RAG query uses knowledge graph entities
- Entity name fuzzy matching with suggestions
- Entity list pagination
- `/.ai/similar/` embedding search
- `/.ai/entities/<file>` file entity view
- Query transparency via `/.ai/query/debug/<id>`
- Index status via `/.ai/status/index`
- Search returns entities + files

### Phase Completion Status (as of 2024-12-28)
| Phase | Name | Status |
|-------|------|--------|
| 1 | FUSE Foundation | 100% |
| 2 | Cognitive Write Path | 100% |
| 3 | Virtual Paths (/.ai/) | 95% |
| 4 | Knowledge Graph Core | 90% |
| 5 | Multi-Memory | 20% |
| 6 | Multi-Modal | 10% |
| 7-10 | Future phases | 0% |

---

## Google Vertex AI Search Insights (Reference)

Research from Google's ranking system, incorporated into roadmap:

**7 Ranking Signals:**
1. Base Ranking - embedding similarity
2. Gecko Score - semantic embeddings
3. Jetstream - cross-attention relevance
4. BM25 - keyword matching
5. PCTR - predicted click-through (N/A for local)
6. Freshness - time-decay scoring
7. Boost/Bury - manual rules

**Best Practices:**
- 500-token chunks with overlap
- Ancestor headings travel with chunks
- Hybrid retrieval: BM25 + embeddings + freshness
- Parse structured files (JSON/YAML) for entity extraction

---

## Future Phase Reference (Archived from Plan)

### Phase B: Semantic Chunking
- New `chunker.py` module
- 500-token chunks with heading context
- Schema: chunks table with embedding_id

### Phase C: Hybrid Retrieval
- Use FTS5 bm25() function
- Formula: `0.6*embedding + 0.3*bm25 + 0.1*freshness`

### Phase D: Context Assembly
- Increase from 1,500 to 6,000 chars
- Deduplicate overlapping chunks

### Hierarchical Embeddings Strategy
```
Directory Level  → Aggregate embedding
    ↓
File Level       → Current (keep)
    ↓
Chunk Level      → 500-token chunks
```
