#!/bin/bash
# E2E Acceptance Tests for CognitiveFS
# Runs in Docker with FUSE support to verify core .ai/ functionality
#
# Usage: ./scripts/e2e-acceptance.sh
# Exit codes: 0 = all tests passed, 1 = tests failed

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

TESTS_PASSED=0
TESTS_FAILED=0
TEST_IMG="/tmp/e2e-test.img"
MOUNT_POINT="/tmp/cognitivefs-e2e"

log_info() { echo -e "${YELLOW}[INFO]${NC} $1"; }
log_pass() { echo -e "${GREEN}[PASS]${NC} $1"; ((TESTS_PASSED++)) || true; }
log_fail() { echo -e "${RED}[FAIL]${NC} $1"; ((TESTS_FAILED++)) || true; }

cleanup() {
    log_info "Cleaning up..."
    # Try to unmount if mounted
    if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
        fusermount -u "$MOUNT_POINT" 2>/dev/null || true
    fi
    rm -rf "$MOUNT_POINT" "$TEST_IMG" "${TEST_IMG%.img}.kg.db"* "${TEST_IMG%.img}.vcs" 2>/dev/null || true
}

trap cleanup EXIT

# ============================================================
# Setup
# ============================================================

log_info "=== CognitiveFS E2E Acceptance Tests ==="
log_info "Working directory: $(pwd)"
log_info "Python: $(python --version)"

# Create mount point
mkdir -p "$MOUNT_POINT"

# Format test image (100MB)
log_info "Formatting test image..."
python tools/format_device.py "$TEST_IMG" --force --size 100M > /dev/null || {
    log_fail "Failed to format test image"
    exit 1
}
log_pass "Test image formatted"

# Mount filesystem in background
log_info "Mounting filesystem..."
python tools/mount.py "$TEST_IMG" "$MOUNT_POINT" &
MOUNT_PID=$!
sleep 3

# Check mount is working
if [ ! -d "$MOUNT_POINT/.ai" ]; then
    log_fail "Mount failed - .ai directory not found"
    exit 1
fi
log_pass "Filesystem mounted at $MOUNT_POINT"

# ============================================================
# Test 1: Status endpoint
# ============================================================

log_info "Testing status endpoint..."
STATUS=$(cat "$MOUNT_POINT/.ai/status/overview" 2>/dev/null)
if echo "$STATUS" | grep -q '"status": "mounted"'; then
    log_pass "Status shows mounted"
else
    log_fail "Status endpoint failed"
fi

# ============================================================
# Test 2: Copy files and verify indexing
# ============================================================

log_info "Copying test files..."

# Create a Python file
cat > "$MOUNT_POINT/test_code.py" << 'EOF'
"""Test module for E2E acceptance tests."""

class UserManager:
    """Manages user accounts and authentication."""

    def create_user(self, username: str, email: str) -> bool:
        """Create a new user account."""
        return True

    def delete_user(self, user_id: int) -> bool:
        """Delete a user account."""
        return False

def calculate_total(items: list) -> float:
    """Calculate total price of items."""
    return sum(item.price for item in items)
EOF

# Create a markdown file with real content
cat > "$MOUNT_POINT/project_notes.md" << 'EOF'
# Project Notes

## Meeting with John Smith

On January 15, 2024, we discussed the new authentication system.
The team at Acme Corporation will implement OAuth2.

## Technical Decisions

- Use PostgreSQL for the database
- Deploy on AWS with Docker containers
- Contact: john.smith@example.com

## Links

- Documentation: https://docs.example.com/auth
- Repository: https://github.com/acme/auth-service
EOF

log_pass "Test files created"

# Wait for background indexing
log_info "Waiting for indexing (15 seconds)..."
sleep 15

# ============================================================
# Test 3: Verify entity extraction quality
# ============================================================

log_info "Testing entity extraction quality..."
STATS=$(cat "$MOUNT_POINT/.ai/graph/stats" 2>/dev/null)

# Check files were indexed (both test_code.py and project_notes.md)
FILES_INDEXED=$(echo "$STATS" | grep -o '"files_indexed": [0-9]*' | grep -o '[0-9]*')
if [ "$FILES_INDEXED" -ge 2 ]; then
    log_pass "Files indexed: $FILES_INDEXED"
else
    log_fail "Expected at least 2 files indexed, got $FILES_INDEXED"
fi

# Check entities were extracted
ENTITIES=$(cat "$MOUNT_POINT/.ai/graph/entities" 2>/dev/null)
ENTITY_COUNT=$(echo "$STATS" | grep -o '"entities": [0-9]*' | grep -o '[0-9]*')

if [ "$ENTITY_COUNT" -gt 0 ]; then
    log_pass "Entities extracted: $ENTITY_COUNT"
else
    log_fail "No entities extracted"
fi

# Check concept entities exist (URLs, emails, code elements are stored as concept)
if echo "$STATS" | grep -q '"concept":'; then
    CONCEPT_COUNT=$(echo "$STATS" | grep -o '"concept": [0-9]*' | grep -o '[0-9]*')
    log_pass "Concept entities found: $CONCEPT_COUNT"
else
    log_fail "No concept entities found"
fi

# Check NO garbage entities from code (like function names as PERSON)
# Code-aware extraction should NOT create PERSON entities from code identifiers
if echo "$ENTITIES" | grep -q "## Person" && echo "$ENTITIES" | grep -A5 "## Person" | grep -qi "calculate_total\|UserManager\|create_user"; then
    log_fail "Garbage entities found: code identifiers extracted as Person"
else
    log_pass "No garbage code entities in Person type"
fi

# ============================================================
# Test 4: Entity detail view
# ============================================================

log_info "Testing entity detail view..."

# List concept entities
CONCEPTS=$(ls "$MOUNT_POINT/.ai/entities/concept/" 2>/dev/null || echo "")
if [ -n "$CONCEPTS" ]; then
    log_pass "Concept entities listed"

    # Try to read a concept entity detail
    FIRST_CONCEPT=$(echo "$CONCEPTS" | head -1)
    if [ -n "$FIRST_CONCEPT" ]; then
        DETAIL=$(cat "$MOUNT_POINT/.ai/entities/concept/$FIRST_CONCEPT" 2>/dev/null)
        if echo "$DETAIL" | grep -q "# Entity:"; then
            log_pass "Entity detail view works for: $FIRST_CONCEPT"
        else
            log_fail "Entity detail view failed for: $FIRST_CONCEPT"
        fi
    fi
else
    log_info "No concept entities to test (may be expected)"
fi

# Test date entity if exists
DATE_ENTITIES=$(ls "$MOUNT_POINT/.ai/entities/date/" 2>/dev/null || echo "")
if echo "$DATE_ENTITIES" | grep -q "2024"; then
    DETAIL=$(cat "$MOUNT_POINT/.ai/entities/date/January_15,_2024" 2>/dev/null || \
             cat "$MOUNT_POINT/.ai/entities/date/2024-01-15" 2>/dev/null || echo "")
    if echo "$DETAIL" | grep -q "# Entity:"; then
        log_pass "Date entity detail view works"
    else
        log_fail "Date entity detail view failed"
    fi
fi

# ============================================================
# Test 5: Search functionality
# ============================================================

log_info "Testing search functionality..."

SEARCH_RESULT=$(cat "$MOUNT_POINT/.ai/search/authentication" 2>/dev/null)
if echo "$SEARCH_RESULT" | grep -qi "project_notes.md\|test_code.py"; then
    log_pass "Search found relevant files"
else
    log_fail "Search did not find expected files"
fi

# ============================================================
# Test 6: Graph queries
# ============================================================

log_info "Testing graph queries..."

GRAPH_STATS=$(cat "$MOUNT_POINT/.ai/graph/stats" 2>/dev/null)
if echo "$GRAPH_STATS" | grep -q '"entities":'; then
    log_pass "Graph stats accessible"
else
    log_fail "Graph stats not accessible"
fi

# ============================================================
# Test 7: URL and email extraction
# ============================================================

log_info "Testing URL/email extraction..."

if echo "$ENTITIES" | grep -q "john.smith@example.com\|https://"; then
    log_pass "URLs and/or emails extracted"
else
    log_fail "URLs/emails not extracted from markdown"
fi

# ============================================================
# Test 8: Ignored files (.git, node_modules, etc.)
# ============================================================

log_info "Testing ignored files are not indexed..."

# Create .git directory with files (should be ignored)
mkdir -p "$MOUNT_POINT/.git/objects"
echo "ref: refs/heads/main" > "$MOUNT_POINT/.git/HEAD"
echo "[core]" > "$MOUNT_POINT/.git/config"

# Create node_modules directory (should be ignored)
mkdir -p "$MOUNT_POINT/node_modules/lodash"
echo "module.exports = {};" > "$MOUNT_POINT/node_modules/lodash/index.js"

# Create __pycache__ directory (should be ignored)
mkdir -p "$MOUNT_POINT/__pycache__"
echo "compiled bytecode" > "$MOUNT_POINT/__pycache__/module.cpython-311.pyc"

# Wait for any potential indexing
sleep 3

# Check that files count hasn't increased beyond expected
STATS_AFTER=$(cat "$MOUNT_POINT/.ai/graph/stats" 2>/dev/null)
FILES_AFTER=$(echo "$STATS_AFTER" | grep -o '"files_indexed": [0-9]*' | grep -o '[0-9]*')

# Should still be 2 (test_code.py and project_notes.md)
if [ "$FILES_AFTER" -eq 2 ]; then
    log_pass "Ignored files not indexed (files: $FILES_AFTER)"
else
    log_fail "Ignored files may have been indexed (files: $FILES_AFTER, expected 2)"
fi

# Verify .git content not in entities
ENTITIES_AFTER=$(cat "$MOUNT_POINT/.ai/graph/entities" 2>/dev/null)
if echo "$ENTITIES_AFTER" | grep -qi "refs/heads/main\|module.exports"; then
    log_fail "Content from ignored directories found in entities"
else
    log_pass "No content from ignored directories in entities"
fi

# ============================================================
# Results Summary
# ============================================================

echo ""
echo "=============================================="
echo -e "  ${GREEN}PASSED${NC}: $TESTS_PASSED"
echo -e "  ${RED}FAILED${NC}: $TESTS_FAILED"
echo "=============================================="

if [ "$TESTS_FAILED" -gt 0 ]; then
    log_fail "E2E acceptance tests FAILED"
    exit 1
else
    log_pass "All E2E acceptance tests PASSED"
    exit 0
fi
