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
log_pass() { echo -e "${GREEN}[PASS]${NC} $1"; ((TESTS_PASSED++)); }
log_fail() { echo -e "${RED}[FAIL]${NC} $1"; ((TESTS_FAILED++)); }

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
log_info "Waiting for indexing (10 seconds)..."
sleep 10

# ============================================================
# Test 3: Verify entity extraction quality
# ============================================================

log_info "Testing entity extraction quality..."
STATS=$(cat "$MOUNT_POINT/.ai/graph/stats" 2>/dev/null)

# Check files were indexed
FILES_INDEXED=$(echo "$STATS" | grep -o '"files_indexed": [0-9]*' | grep -o '[0-9]*')
if [ "$FILES_INDEXED" -ge 2 ]; then
    log_pass "Files indexed: $FILES_INDEXED"
else
    log_fail "Expected at least 2 files indexed, got $FILES_INDEXED"
fi

# Check entities were extracted
ENTITIES=$(cat "$MOUNT_POINT/.ai/graph/entities" 2>/dev/null)

# For markdown file: should have person entities (John Smith)
if echo "$STATS" | grep -q '"person":'; then
    PERSON_COUNT=$(echo "$STATS" | grep -o '"person": [0-9]*' | grep -o '[0-9]*')
    if [ "$PERSON_COUNT" -gt 0 ]; then
        log_pass "Person entities extracted: $PERSON_COUNT"
    else
        log_fail "No person entities found"
    fi
else
    log_fail "Person entity type missing from stats"
fi

# Check for legitimate entities (not garbage)
if echo "$ENTITIES" | grep -qi "john smith\|January 15"; then
    log_pass "Legitimate entities found (John Smith or date)"
else
    log_fail "Expected legitimate entities not found"
fi

# Check NO garbage entities from code (like function names as PERSON)
if echo "$ENTITIES" | grep -q "## Person" && echo "$ENTITIES" | grep -A5 "## Person" | grep -qi "calculate_total\|UserManager"; then
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
