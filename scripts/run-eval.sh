#!/bin/bash
# RAGAS Evaluation Runner for CognitiveFS
#
# Runs the full RAGAS evaluation pipeline in Docker using HOST's Ollama.
# Requires Ollama running on host machine with a capable model (7B+).
#
# Usage:
#   ./scripts/run-eval.sh                              # Run with defaults
#   ./scripts/run-eval.sh --model qwen2.5:14b-instruct-q4_K_M  # Use specific model
#   ./scripts/run-eval.sh --skip-build                 # Skip Docker build

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Defaults - use host's Ollama
MODEL="${RAGAS_MODEL:-qwen2.5:14b-instruct-q4_K_M}"
SKIP_BUILD=false
DATASET_PATH="/workspace/test-data/eval_dataset.json"
KG_PATH="/workspace/test-data/test.kg.db"
OLLAMA_URL="${OLLAMA_BASE_URL:-http://host.docker.internal:11434}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --model)
            MODEL="$2"
            shift 2
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --kg)
            KG_PATH="$2"
            shift 2
            ;;
        --dataset)
            DATASET_PATH="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --model MODEL    Ollama model to use (default: qwen2.5:14b-instruct-q4_K_M)"
            echo "  --skip-build     Skip Docker image build"
            echo "  --kg PATH        Knowledge graph path (default: test-data/test.kg.db)"
            echo "  --dataset PATH   Evaluation dataset path"
            echo ""
            echo "Environment variables:"
            echo "  RAGAS_MODEL      Default model for evaluation"
            echo "  OLLAMA_BASE_URL  Ollama server URL (default: http://host.docker.internal:11434)"
            echo ""
            echo "NOTE: This script uses the HOST machine's Ollama. Ensure Ollama is running."
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

cd "$PROJECT_DIR"

echo "=============================================="
echo "CognitiveFS RAGAS Evaluation"
echo "=============================================="
echo "Model: $MODEL"
echo "Ollama: HOST machine (localhost:11434)"
echo "KG Path: $KG_PATH"
echo "Dataset: $DATASET_PATH"
echo ""

# Create output directories
mkdir -p eval-results test-data

# Step 1: Check host Ollama is running
echo "[1/4] Checking host Ollama..."
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "ERROR: Ollama is not running on host machine"
    echo "Please start Ollama: ollama serve"
    exit 1
fi
echo "Host Ollama is running"

# List available models
echo "Available models:"
curl -s http://localhost:11434/api/tags | grep -o '"name":"[^"]*"' | head -5 || true
echo ""

# Step 2: Build Docker images
if [ "$SKIP_BUILD" = false ]; then
    echo "[2/4] Building Docker images..."
    docker compose -f docker-compose.eval.yml build
else
    echo "[2/4] Skipping Docker build..."
fi

# Step 3: Check if dataset exists
echo "[3/4] Checking evaluation data..."
if [ ! -f "test-data/eval_dataset.json" ]; then
    echo "Using default eval_dataset.json (10 curated test cases)"
fi

# Step 4: Run RAGAS evaluation
echo "[4/4] Running RAGAS evaluation..."
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTPUT_PATH="/workspace/eval-results/ragas_${TIMESTAMP}.json"

docker compose -f docker-compose.eval.yml run --rm \
    -e RAGAS_MODEL="$MODEL" \
    -e OLLAMA_BASE_URL="$OLLAMA_URL" \
    cognitivefs-eval \
    python tools/ragas_eval.py run \
        --kg "$KG_PATH" \
        --dataset "$DATASET_PATH" \
        --output "$OUTPUT_PATH"

echo ""
echo "=============================================="
echo "Evaluation complete!"
echo "Results: eval-results/ragas_${TIMESTAMP}.json"
echo "=============================================="
