#!/bin/bash
# Interactive Shell for CognitiveFS Evaluation
#
# Starts Ollama and drops into an interactive shell for manual testing.
#
# Usage:
#   ./scripts/eval-shell.sh
#   ./scripts/eval-shell.sh --model mistral:7b

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

MODEL="${RAGAS_MODEL:-llama3:8b}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --model)
            MODEL="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

cd "$PROJECT_DIR"

echo "=============================================="
echo "CognitiveFS Evaluation Shell"
echo "=============================================="
echo "Model: $MODEL"
echo ""

# Start Ollama if not running
echo "Starting Ollama service..."
docker compose -f docker-compose.eval.yml up -d ollama

# Wait for Ollama
echo "Waiting for Ollama..."
for i in {1..60}; do
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo "Ollama is ready"
        break
    fi
    sleep 1
done

# Pull model if needed
echo "Ensuring model $MODEL is available..."
docker compose -f docker-compose.eval.yml exec -T ollama ollama pull "$MODEL" 2>/dev/null || true

echo ""
echo "Starting interactive shell..."
echo "=============================================="
echo "Useful commands:"
echo "  python tools/ragas_eval.py --help"
echo "  python tools/ragas_eval.py generate --kg test-data/test.kg.db --output test-data/eval_dataset.json"
echo "  python tools/ragas_eval.py run --kg test-data/test.kg.db --dataset test-data/eval_dataset.json --output eval-results/test.json"
echo "  python -m cognitivefs --help"
echo "=============================================="
echo ""

# Start interactive shell
docker compose -f docker-compose.eval.yml run --rm \
    -e RAGAS_MODEL="$MODEL" \
    -e OLLAMA_BASE_URL="http://ollama:11434" \
    cognitivefs-eval \
    bash

# Cleanup on exit
echo ""
echo "Stopping services..."
docker compose -f docker-compose.eval.yml down
