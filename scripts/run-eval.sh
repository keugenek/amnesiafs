#!/bin/bash
# RAGAS Evaluation Runner for CognitiveFS
#
# Runs the full RAGAS evaluation pipeline in Docker with Ollama.
# Uses 7B+ model for reliable evaluation scores.
#
# Usage:
#   ./scripts/run-eval.sh                    # Run with defaults
#   ./scripts/run-eval.sh --model mistral:7b # Use different model
#   ./scripts/run-eval.sh --gpu              # Enable GPU support
#   ./scripts/run-eval.sh --skip-build       # Skip Docker build

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Defaults
MODEL="${RAGAS_MODEL:-llama3:8b}"
USE_GPU=false
SKIP_BUILD=false
DATASET_PATH="/workspace/test-data/eval_dataset.json"
KG_PATH="/workspace/test-data/test.kg.db"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --model)
            MODEL="$2"
            shift 2
            ;;
        --gpu)
            USE_GPU=true
            shift
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
            echo "  --model MODEL    Ollama model to use (default: llama3:8b)"
            echo "  --gpu            Enable GPU support"
            echo "  --skip-build     Skip Docker image build"
            echo "  --kg PATH        Knowledge graph path (default: test-data/test.kg.db)"
            echo "  --dataset PATH   Evaluation dataset path"
            echo ""
            echo "Environment variables:"
            echo "  RAGAS_MODEL      Default model for evaluation"
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
echo "KG Path: $KG_PATH"
echo "Dataset: $DATASET_PATH"
echo ""

# Create output directories
mkdir -p eval-results test-data

# Step 1: Build Docker images
if [ "$SKIP_BUILD" = false ]; then
    echo "[1/5] Building Docker images..."
    docker compose -f docker-compose.eval.yml build
else
    echo "[1/5] Skipping Docker build..."
fi

# Step 2: Start Ollama service
echo "[2/5] Starting Ollama service..."
docker compose -f docker-compose.eval.yml up -d ollama

# Wait for Ollama to be ready
echo "Waiting for Ollama to start..."
for i in {1..60}; do
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo "Ollama is ready"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "ERROR: Ollama failed to start within 60 seconds"
        docker compose -f docker-compose.eval.yml logs ollama
        exit 1
    fi
    sleep 1
done

# Step 3: Pull the model
echo "[3/5] Pulling model: $MODEL"
echo "Note: First pull may take several minutes for 7B models (~4GB download)"
docker compose -f docker-compose.eval.yml exec -T ollama ollama pull "$MODEL"

# Step 4: Check if dataset exists, generate if not
echo "[4/5] Preparing evaluation data..."
if [ ! -f "test-data/eval_dataset.json" ]; then
    echo "Generating evaluation dataset from knowledge graph..."

    # Check if KG exists
    if [ ! -f "test-data/test.kg.db" ]; then
        echo "Warning: No knowledge graph found at test-data/test.kg.db"
        echo "Please create and populate a knowledge graph first."
        echo ""
        echo "Example:"
        echo "  python tools/format_device.py test-data/test.img --size 50 --force"
        echo "  python tools/mount.py test-data/test.img /mnt/test"
        echo "  # Copy files to /mnt/test"
        echo "  fusermount -u /mnt/test"
    fi

    docker compose -f docker-compose.eval.yml run --rm \
        -e RAGAS_MODEL="$MODEL" \
        cognitivefs-eval \
        python tools/ragas_eval.py generate \
            --kg "$KG_PATH" \
            --output "$DATASET_PATH" \
            --num-samples 20
fi

# Step 5: Run RAGAS evaluation
echo "[5/5] Running RAGAS evaluation..."
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTPUT_PATH="/workspace/eval-results/ragas_${TIMESTAMP}.json"

docker compose -f docker-compose.eval.yml run --rm \
    -e RAGAS_MODEL="$MODEL" \
    -e OLLAMA_BASE_URL="http://ollama:11434" \
    cognitivefs-eval \
    python tools/ragas_eval.py run \
        --kg "$KG_PATH" \
        --dataset "$DATASET_PATH" \
        --output "$OUTPUT_PATH"

# Cleanup
echo ""
echo "Stopping services..."
docker compose -f docker-compose.eval.yml down

echo ""
echo "=============================================="
echo "Evaluation complete!"
echo "Results: eval-results/ragas_${TIMESTAMP}.json"
echo "=============================================="
