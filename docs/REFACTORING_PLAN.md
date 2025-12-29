# CognitiveFS Refactoring Plan

**Created:** 2025-12-29
**Status:** Phase 1 Complete, Phase 2 Pending

---

## Phase 1: Remove Code Duplication ✅ COMPLETE

**Completed:** 2025-12-29
**Commits:** `025bf08`, `74c6cb6`, `7bfcf52`

### Completed Work

#### Priority 1: Extract `_format_bytes` Duplicates ✅
- **Before:** 3 implementations (utils.py, generators.py × 2)
- **After:** 1 implementation in utils.py
- **Impact:** -12 lines, single source of truth
- **Files:** generators.py

#### Priority 3: Centralize Timestamp Formatting ✅
- **Before:** 11 inline `strftime` calls
- **After:** `format_timestamp(ts, style)` utility
- **Styles:** 'full', 'short', 'date', 'time'
- **Impact:** -28 lines, consistent formatting
- **Files:** utils.py, virtual_ai.py, generators.py

### Test Results
- **Tests:** 96/96 passing (100% ✅)
- **Fixed:** embedder test for dynamic dimensions
- **All modules working correctly**

### Metrics
- **Code removed:** ~40 lines of duplication
- **Files refactored:** 3
- **Time spent:** ~2 hours
- **Risk level:** Low (extensive tests)

---

## Phase 2: Architectural Refactoring 📋 PLANNED

**Target:** Q1 2025
**Estimated effort:** 4-8 hours
**Risk level:** Medium

### Priority 2: Split `virtual_ai.py` into Sub-Handlers

#### Current State
```
virtual_ai.py
├── Lines: 2938
├── Size: 49KB
├── Handlers mixed together
└── Hard to navigate and maintain
```

#### Target State
```
virtual_ai/
├── __init__.py           # Main VirtualAIHandler (200 lines)
├── base.py              # Shared utilities (150 lines)
├── handlers/
│   ├── __init__.py
│   ├── status_handler.py    (~200 lines)
│   ├── search_handler.py    (~300 lines)
│   ├── versions_handler.py  (~320 lines)
│   ├── graph_handler.py     (~600 lines)
│   ├── entities_handler.py  (~250 lines)
│   ├── query_handler.py     (~200 lines)
│   └── chat_handler.py      (~200 lines)
└── tests/
    └── test_handlers.py  # New handler-specific tests
```

#### Benefits
- ✅ Each handler 200-400 lines (manageable)
- ✅ Clear separation of concerns
- ✅ Easier to test individual features
- ✅ Parallel development possible
- ✅ Easier onboarding for contributors

#### Implementation Steps
1. Create `virtual_ai/` package structure
2. Extract `StatusHandler` class → `status_handler.py`
3. Extract `SearchHandler` class → `search_handler.py`
4. Extract `VersionsHandler` class → `versions_handler.py`
5. Extract `GraphHandler` class → `graph_handler.py`
6. Extract `EntitiesHandler` class → `entities_handler.py`
7. Extract `QueryHandler` class → `query_handler.py`
8. Extract `ChatHandler` class → `chat_handler.py`
9. Create `base.py` with shared utilities:
   - `_make_dir_stat()`
   - `_make_file_stat()`
   - `parse_ai_path()`
10. Update `__init__.py` with main coordinator
11. Update imports in `fuse_ops.py`
12. Run full test suite
13. Update documentation

#### Testing Strategy
- Run existing tests (should pass)
- Add handler-specific unit tests
- Integration test with mounted filesystem
- Performance benchmark (should be same)

#### Rollback Plan
- Keep old `virtual_ai.py` as `virtual_ai_legacy.py`
- If issues, revert imports in `fuse_ops.py`
- Delete new package structure

---

### Priority 4: Extract Version Dashboard Generator

#### Current State
```python
# generators.py - GeneratorFactory class
def _generate_versions_file(self, filename, cognitivefs):
    # 150 lines of version-specific logic
    # Mixed with general generator logic
```

#### Target State
```python
# generators.py
class VersionDashboardGenerator:
    """Specialized generator for version control."""

    def __init__(self, version_control):
        self.vc = version_control

    def generate_dashboard(self, vc_stats, commits) -> bytes:
        """Generate _DASHBOARD.html for versions."""
        pass

    def generate_manifest(self, vc_stats, commits) -> bytes:
        """Generate _manifest.md for versions."""
        pass

    def generate_index(self, vc_stats, commits) -> bytes:
        """Generate _index.json for versions."""
        pass

class GeneratorFactory:
    def __init__(self, kg):
        self.kg = kg
        self.dashboard = DashboardGenerator(kg)
        self.manifest = ManifestGenerator(kg)
        self.index = IndexGenerator(kg)
        self.version_gen = VersionDashboardGenerator(None)  # NEW
```

#### Benefits
- ✅ Clear separation: general vs version-specific
- ✅ Easier to extend with other specialized generators
- ✅ Reduces complexity of GeneratorFactory
- ✅ Version logic in one place

#### Implementation Steps
1. Create `VersionDashboardGenerator` class
2. Move `_generate_versions_file()` logic
3. Move `_generate_versions_dashboard()` logic
4. Move `_generate_versions_manifest()` logic
5. Move `_generate_versions_index()` logic
6. Update `GeneratorFactory.get_cached_or_generate()`
7. Update tests
8. Verify dashboard generation works

---

## Phase 3: Code Quality Improvements 📋 PLANNED

**Target:** Q2 2025
**Estimated effort:** 2-4 hours
**Risk level:** Low

### Priority 5: Reduce Byte String Literals

#### Current Issue
```python
# virtual_ai.py has 37 occurrences of:
return b""
return b"Not found\n"
return b"Error...\n"
```

#### Solution
```python
# constants.py
EMPTY_RESPONSE = b""
NOT_FOUND = b"Not found.\n"
KG_NOT_INITIALIZED = b"Knowledge graph not initialized.\n"
VC_NOT_ENABLED = b"Version control not enabled.\n"

def error_response(msg: str) -> bytes:
    return f"Error: {msg}\n".encode('utf-8')

def not_found_response(resource: str) -> bytes:
    return f"{resource} not found.\n".encode('utf-8')
```

#### Benefits
- Consistent error messaging
- Easier to update messages
- Less duplication
- Type safety

---

### Priority 6: Standardize Error Responses

#### Current State
Inconsistent patterns:
```python
return b"Knowledge graph not initialized.\n"
return f"File not indexed: {path}\n".encode('utf-8')
return b""  # silent failure
raise FuseOSError(errno.ENOENT)  # OS error
```

#### Target State
```python
# error_responses.py
class VirtualPathError:
    @staticmethod
    def not_initialized(component: str) -> bytes:
        return f"{component} not initialized.\n".encode('utf-8')

    @staticmethod
    def not_found(resource: str) -> bytes:
        return f"{resource} not found.\n".encode('utf-8')

    @staticmethod
    def not_available(feature: str) -> bytes:
        return f"{feature} not available.\n".encode('utf-8')

# Usage:
return VirtualPathError.not_initialized("Knowledge graph")
```

---

### Priority 7: Extract CSS Styles

#### Current State
```python
# generators.py - DashboardGenerator
CSS_STYLES = """
    <style>
        * { box-sizing: border-box; ... }
        # 70 lines of CSS
    </style>
"""
```

#### Solution A: Separate File
```python
# dashboard_styles.css
# Move CSS to separate file
# Load at runtime
```

#### Solution B: Module Constant
```python
# dashboard_styles.py
DEFAULT_THEME = """..."""
DARK_THEME = """..."""
LIGHT_THEME = """..."""

def get_styles(theme='dark') -> str:
    return THEMES[theme]
```

#### Benefits
- Easier to maintain styling
- Potential for themes
- Cleaner code in generators.py
- CSS syntax highlighting in editor

---

## Phase 4: RAG Interface Improvements 📋 PLANNED

**Target:** Q2 2025
**Estimated effort:** 8-16 hours
**Risk level:** Medium

*Based on code analysis session findings*

### Priority 8: Code-Aware Entity Extraction

#### Current Issues
- Extracts syntax elements: `//`, `/.ai/`, `/O`
- Extracts common words: `to`, `get`, `set`
- No code-specific filtering

#### Solution
```python
# extractor.py - EntityExtractor
CODE_NOISE_PATTERNS = [
    r'^[^a-zA-Z0-9]+$',  # Only symbols
    r'^[a-z]{1,2}$',     # Single letters
    r'^__(.*?)__$',      # Dunder methods (keep as-is)
]

CODE_ENTITY_PATTERNS = {
    'class': r'\bclass\s+([A-Z][a-zA-Z0-9_]*)',
    'function': r'\bdef\s+([a-z_][a-z0-9_]*)',
    'constant': r'\b([A-Z_][A-Z0-9_]*)\s*=',
}

def extract_code_entities(self, code: str, language: str):
    """Extract code-specific entities (classes, functions, etc.)."""
    pass
```

#### Benefits
- ✅ Cleaner entity lists
- ✅ More useful for code navigation
- ✅ Better search results

---

### Priority 9: Improve Topic Clustering

#### Current State
```json
{
  "topics": {
    "concept": 8.2,
    "file": 6.2,
    "organization": 0.6
  }
}
```
Just entity types, not semantic topics.

#### Target State
```json
{
  "topics": {
    "File I/O": 12,
    "Authentication": 8,
    "Error Handling": 6,
    "Database Access": 5,
    "Testing": 3
  }
}
```

#### Solution
```python
# Use embeddings + clustering
# Or extract from:
# - Module docstrings
# - Import patterns
# - Function/class names

from sklearn.cluster import KMeans

def cluster_semantic_topics(files: List[File]) -> Dict[str, float]:
    """Cluster files by semantic topic using embeddings."""
    embeddings = [f.embedding for f in files]
    clusters = KMeans(n_clusters=10).fit(embeddings)
    # Label clusters by common keywords
    topics = label_clusters(clusters, files)
    return topics
```

---

### Priority 10: Add Result Summarization

#### Current State
Verbose snippets:
```
## Files (6)
  === /src/cognitivefs/__main__.py (relevance: 1.2) ===
    ...rface for mounting and managing CognitiveFS.
 """

 import sys
 import os
 ...
```

#### Target State
```
Found '_format_bytes' in 3 files:
  utils.py:36          def format_bytes(size: int) -> str:
  generators.py:196    def _format_bytes(self, size: int) -> str:
  generators.py:297    def _format_bytes(self, size: int) -> str:

View details: cat /.ai/search/_format_bytes/_verbose
```

#### Implementation
```python
def _format_search_results(results, query, mode='summary'):
    if mode == 'summary':
        return _format_summary(results)
    elif mode == 'verbose':
        return _format_verbose(results)
```

---

### Priority 11: Support Write Operations

#### Current Limitation
Read-only virtual paths

#### Target
```powershell
# Enable query-by-file-creation:
echo "find duplicate functions" > K:\.ai\query\analyze_code
type K:\.ai\query\analyze_code\result.txt

# Or:
echo "analyze" > K:\.ai\analyze\duplicates
type K:\.ai\analyze\duplicates\report.txt
```

#### Implementation
```python
# virtual_ai.py
def write(self, path: str, data: bytes, offset: int) -> int:
    """Handle writes to virtual paths."""
    subdir, target, parts = self.parse_ai_path(path)

    if subdir == "query":
        # Store query, trigger analysis
        query_id = self._store_query(data.decode('utf-8'))
        return len(data)

    return -errno.EPERM  # Read-only by default
```

---

### Priority 12: Add Pattern Matching

#### New Virtual Paths
```
/.ai/patterns/
├── methods_returning_bytes
├── classes_with_init
├── functions_over_100_lines
├── modules_importing_X
└── unused_functions
```

#### Implementation
Use AST parsing:
```python
import ast

def find_methods_returning_bytes(code: str) -> List[str]:
    tree = ast.parse(code)
    methods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if returns_bytes(node):
                methods.append(node.name)
    return methods
```

---

## Implementation Priority

### High Priority (Next Sprint)
1. ✅ Phase 1: Code duplication (DONE)
2. 📋 Phase 2: Split virtual_ai.py
3. 📋 Phase 2: Extract version dashboard

### Medium Priority (Q1 2025)
4. 📋 Phase 3: Byte string constants
5. 📋 Phase 3: Standardize errors
6. 📋 Phase 4: Code-aware entities

### Low Priority (Q2 2025)
7. 📋 Phase 3: Extract CSS
8. 📋 Phase 4: Topic clustering
9. 📋 Phase 4: Result summarization
10. 📋 Phase 4: Write operations
11. 📋 Phase 4: Pattern matching

---

## Success Criteria

### Phase 1 ✅
- [x] No duplicate utility functions
- [x] Consistent timestamp formatting
- [x] All tests passing
- [x] Code quality metrics improved

### Phase 2 📋
- [ ] virtual_ai.py < 500 lines
- [ ] Each handler < 400 lines
- [ ] All tests still passing
- [ ] No performance regression
- [ ] Documentation updated

### Phase 3 📋
- [ ] < 5 byte string literals per file
- [ ] Consistent error messages
- [ ] CSS in separate file/module
- [ ] Code coverage > 90%

### Phase 4 📋
- [ ] Entity extraction < 10% noise
- [ ] Semantic topic clustering
- [ ] Search results scannable
- [ ] Write operations working
- [ ] AST pattern matching available

---

## Risk Assessment

| Phase | Risk Level | Mitigation |
|-------|------------|------------|
| Phase 1 | Low ✅ | Extensive tests, completed successfully |
| Phase 2 | Medium ⚠️ | Keep legacy code, gradual migration |
| Phase 3 | Low | Isolated changes, backward compatible |
| Phase 4 | Medium ⚠️ | New features, extensive testing needed |

---

## Maintenance Notes

### When to Refactor
- Module > 1000 lines
- Function > 100 lines
- Duplication > 3 times
- Test coverage < 80%
- Cyclomatic complexity > 15

### How to Verify
```bash
# Run tests
pytest tests/ -v

# Check coverage
pytest --cov=src/cognitivefs tests/

# Check complexity
radon cc src/cognitivefs -a

# Check duplications
pylint --disable=all --enable=duplicate-code src/
```

### Documentation Requirements
- Update README.md if user-facing changes
- Update CHANGELOG.md for each release
- Update this plan after each phase
- Document breaking changes

---

## Notes from Code Analysis Session

### What Worked
- Virtual paths for exploration ✅
- Semantic search found patterns ✅
- Version history accessible ✅
- Status dashboard useful ✅

### What Needs Work
- Entity extraction too noisy ❌
- Topic clustering not useful ❌
- Similarity ranking too coarse ❌
- No pattern-based search ❌

### Key Insight
**Hybrid approach wins:** Use CognitiveFS for discovery/overview, traditional tools (grep/AST) for precision.

See: `docs/CODE_ANALYSIS_SESSION.md` for detailed findings.

---

**Last Updated:** 2025-12-29
**Next Review:** After Phase 2 completion
