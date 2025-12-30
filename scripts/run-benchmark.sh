#!/bin/bash
# RAG Benchmark Evaluation Runner for CognitiveFS
#
# Runs industry-standard RAG benchmarks (RAGBench, SQuAD) in Docker.
# Uses Token F1, ROUGE, BLEU, retrieval metrics.
#
# Usage:
#   ./scripts/run-benchmark.sh                              # Run with synthetic
#   ./scripts/run-benchmark.sh --dataset ragbench           # Use RAGBench
#   ./scripts/run-benchmark.sh --dataset squad --max-samples 100

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Defaults
MODEL="${RAG_MODEL:-qwen2.5:14b-instruct-q4_K_M}"
SKIP_BUILD=false
DATASET="synthetic"
MAX_SAMPLES=50
KG_PATH="/workspace/test-data/test.kg.db"
OLLAMA_URL="${OLLAMA_BASE_URL:-http://host.docker.internal:11434}"
IMPORT_DOCS=false

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
            DATASET="$2"
            shift 2
            ;;
        --max-samples)
            MAX_SAMPLES="$2"
            shift 2
            ;;
        --import-docs)
            IMPORT_DOCS=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --model MODEL      Ollama model to use (default: qwen2.5:14b-instruct-q4_K_M)"
            echo "  --skip-build       Skip Docker image build"
            echo "  --kg PATH          Knowledge graph path (default: test-data/test.kg.db)"
            echo "  --dataset NAME     Benchmark dataset: ragbench, squad, triviaqa, synthetic"
            echo "  --max-samples N    Max samples to evaluate (default: 50)"
            echo "  --import-docs      Import benchmark docs to KG before eval"
            echo ""
            echo "Datasets:"
            echo "  synthetic    - Quick test with generated questions"
            echo "  ragbench     - Galileo RAGBench (100K examples, 5 domains)"
            echo "  squad        - Stanford QA Dataset"
            echo "  triviaqa     - TriviaQA reading comprehension"
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
echo "CognitiveFS RAG Benchmark Evaluation"
echo "=============================================="
echo "Dataset: $DATASET"
echo "Model: $MODEL"
echo "Max Samples: $MAX_SAMPLES"
echo "KG Path: $KG_PATH"
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
echo ""

# Step 2: Build Docker images
if [ "$SKIP_BUILD" = false ]; then
    echo "[2/4] Building Docker images..."
    docker compose -f docker-compose.eval.yml build
else
    echo "[2/4] Skipping Docker build..."
fi

# Step 3: Optionally import benchmark docs
if [ "$IMPORT_DOCS" = true ]; then
    echo "[3/4] Importing benchmark documents to KG..."
    docker compose -f docker-compose.eval.yml run --rm \
        -e OLLAMA_BASE_URL="$OLLAMA_URL" \
        cognitivefs-eval \
        python tools/import_benchmark_docs.py \
            --kg "$KG_PATH" \
            --dataset "$DATASET" \
            --max-docs "$MAX_SAMPLES"
else
    echo "[3/4] Skipping document import..."
fi

# Step 4: Run benchmark evaluation
echo "[4/4] Running benchmark evaluation..."
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTPUT_PATH="/workspace/eval-results/benchmark_${DATASET}_${TIMESTAMP}.json"

docker compose -f docker-compose.eval.yml run --rm \
    -e RAG_MODEL="$MODEL" \
    -e OLLAMA_BASE_URL="$OLLAMA_URL" \
    cognitivefs-eval \
    python tools/rag_benchmark.py eval \
        --kg "$KG_PATH" \
        --dataset "$DATASET" \
        --max-samples "$MAX_SAMPLES" \
        --model "$MODEL" \
        --output "$OUTPUT_PATH"

echo ""
echo "=============================================="
echo "Benchmark complete!"
echo "Results: eval-results/benchmark_${DATASET}_${TIMESTAMP}.json"
echo "=============================================="
