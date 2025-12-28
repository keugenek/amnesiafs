#!/usr/bin/env python3
"""
RAGAS Evaluation for CognitiveFS RAG System.

Uses the RAGAS framework (academically proven) with Ollama for local LLM evaluation.
Provides industry-standard metrics: Faithfulness, Context Precision/Recall, Answer Relevancy.

Usage:
  # Generate evaluation dataset from knowledge graph
  python tools/ragas_eval.py generate \
    --kg test-data/test.kg.db \
    --output test-data/eval_dataset.json \
    --num-samples 20

  # Run RAGAS evaluation
  python tools/ragas_eval.py run \
    --kg test-data/test.kg.db \
    --dataset test-data/eval_dataset.json \
    --output eval-results/ragas_results.json

Requirements:
  - Ollama running with 7B+ model (llama3:8b, mistral:7b, etc.)
  - CognitiveFS knowledge graph populated with files
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Third-party imports
try:
    import pandas as pd
    from ragas import evaluate
    from ragas.llms import llm_factory
    from ragas.metrics import (
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
    )
    from ragas.dataset_schema import SingleTurnSample, EvaluationDataset
    RAGAS_AVAILABLE = True
except ImportError as e:
    RAGAS_AVAILABLE = False
    RAGAS_IMPORT_ERROR = str(e)

# CognitiveFS imports
from cognitivefs.knowledge_graph import KnowledgeGraph
from cognitivefs.llm import OllamaClient, KnowledgeQueryEngine


@dataclass
class EvalSample:
    """A single evaluation sample."""
    user_input: str
    reference: str  # Ground truth answer
    expected_contexts: List[str]  # Expected file paths/content
    category: str = "general"


def get_ollama_config() -> tuple:
    """Get Ollama configuration from environment."""
    base_url = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
    model = os.environ.get('RAGAS_MODEL', 'llama3:8b')
    return base_url, model


def load_dataset(path: str) -> List[EvalSample]:
    """Load evaluation dataset from JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    samples = []
    for item in data:
        samples.append(EvalSample(
            user_input=item['user_input'],
            reference=item.get('reference', ''),
            expected_contexts=item.get('expected_contexts', []),
            category=item.get('category', 'general')
        ))
    return samples


def save_dataset(samples: List[EvalSample], path: str) -> None:
    """Save evaluation dataset to JSON file."""
    data = [asdict(s) for s in samples]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_dataset(kg_path: str, output_path: str, num_samples: int) -> None:
    """Generate evaluation dataset from knowledge graph content."""
    print(f"Generating evaluation dataset from {kg_path}...")

    kg = KnowledgeGraph(kg_path)
    kg.open()

    cursor = kg.conn.cursor()
    cursor.execute("""
        SELECT path, summary, extracted_text
        FROM files
        WHERE (summary IS NOT NULL AND summary != '')
           OR (extracted_text IS NOT NULL AND extracted_text != '')
        ORDER BY modified_at DESC
        LIMIT ?
    """, (num_samples * 3,))  # Fetch extra to filter

    samples = []
    for row in cursor.fetchall():
        path = row['path']
        summary = row['summary'] or ''
        content = row['extracted_text'] or summary

        if len(content) < 100:
            continue

        filename = Path(path).stem

        # Generate question based on file content
        question = f"What information is contained in the {filename} document?"

        # Use summary as reference if available, otherwise use truncated content
        reference = summary if summary else content[:500]

        samples.append(EvalSample(
            user_input=question,
            reference=reference,
            expected_contexts=[path],
            category="auto-generated"
        ))

        if len(samples) >= num_samples:
            break

    kg.close()

    if not samples:
        print("Warning: No files with content found in knowledge graph.")
        print("Please index some files first before generating evaluation dataset.")
        return

    save_dataset(samples, output_path)
    print(f"Generated {len(samples)} evaluation samples to {output_path}")


def run_rag_queries(kg_path: str, samples: List[EvalSample]) -> List[Dict]:
    """Run RAG queries and collect responses with contexts."""
    base_url, model = get_ollama_config()

    print(f"Connecting to Ollama at {base_url} with model {model}...")

    kg = KnowledgeGraph(kg_path)
    kg.open()

    # Use existing OllamaClient for RAG
    llm = OllamaClient(base_url=base_url, model=model)
    engine = KnowledgeQueryEngine(kg, llm)

    if not llm.is_available:
        print("ERROR: Ollama is not available. Please ensure it's running.")
        print(f"  Expected at: {base_url}")
        kg.close()
        return []

    results = []
    total = len(samples)

    for i, sample in enumerate(samples):
        print(f"  [{i+1}/{total}] Querying: {sample.user_input[:50]}...", end=" ", flush=True)

        start_time = time.time()

        # Run RAG query
        result = engine.query_with_context(sample.user_input, max_context_files=3)

        elapsed = time.time() - start_time

        # Extract retrieved contexts
        retrieved_contexts = []
        for file_info in result.get('files_used', []):
            # Get file content from KG
            file_path = file_info.get('path', '')
            file_record = kg.get_file(file_path)
            if file_record:
                context = file_record.summary or file_record.extracted_text or ''
                if context:
                    retrieved_contexts.append(f"[{file_path}]: {context[:500]}")

        results.append({
            'user_input': sample.user_input,
            'response': result.get('answer', ''),
            'reference': sample.reference,
            'retrieved_contexts': retrieved_contexts,
            'files_used': [f['path'] for f in result.get('files_used', [])],
            'latency_ms': elapsed * 1000,
            'llm_available': result.get('llm_available', False)
        })

        status = "OK" if result.get('answer') else "EMPTY"
        print(f"{status} ({elapsed:.1f}s)")

    kg.close()
    return results


def run_ragas_evaluation(results: List[Dict], output_path: str) -> Dict:
    """Run RAGAS evaluation on RAG results."""
    if not RAGAS_AVAILABLE:
        print(f"ERROR: RAGAS not available: {RAGAS_IMPORT_ERROR}")
        print("Please install: pip install ragas langchain-ollama")
        return {}

    base_url, model = get_ollama_config()

    print(f"\nRunning RAGAS evaluation with {model}...")
    print("This uses LLM-as-judge for faithfulness and relevancy metrics.")

    # Create RAGAS dataset
    ragas_samples = []
    for r in results:
        # Skip if no response or no contexts
        if not r.get('response') or not r.get('retrieved_contexts'):
            continue

        ragas_samples.append(SingleTurnSample(
            user_input=r['user_input'],
            response=r['response'],
            reference=r['reference'],
            retrieved_contexts=r['retrieved_contexts']
        ))

    if not ragas_samples:
        print("ERROR: No valid samples for RAGAS evaluation.")
        return {}

    dataset = EvaluationDataset(samples=ragas_samples)

    # Configure Ollama as the evaluator LLM
    try:
        evaluator_llm = llm_factory(
            model=model,
            provider="ollama",
            base_url=base_url
        )
    except Exception as e:
        print(f"ERROR: Failed to create Ollama LLM: {e}")
        print("Falling back to metrics without LLM-as-judge...")
        evaluator_llm = None

    # Select metrics based on LLM availability
    if evaluator_llm:
        metrics = [faithfulness, answer_relevancy, context_precision, context_recall]
    else:
        # Only context metrics work without LLM
        metrics = [context_precision, context_recall]

    # Run evaluation
    try:
        eval_results = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=evaluator_llm
        )

        # Convert to dict
        scores = {}
        if hasattr(eval_results, 'to_pandas'):
            df = eval_results.to_pandas()
            for col in df.columns:
                if col not in ['user_input', 'response', 'reference', 'retrieved_contexts']:
                    scores[col] = float(df[col].mean())
        else:
            scores = dict(eval_results)

        return scores

    except Exception as e:
        print(f"ERROR: RAGAS evaluation failed: {e}")
        return {}


def compute_retrieval_metrics(results: List[Dict], samples: List[EvalSample]) -> Dict:
    """Compute retrieval metrics without LLM."""
    if not results:
        return {}

    total_precision = 0
    total_recall = 0
    valid_count = 0

    for result, sample in zip(results, samples):
        retrieved = set(result.get('files_used', []))
        expected = set(sample.expected_contexts)

        if not expected:
            continue

        # Fuzzy matching - check if expected path appears in any retrieved path
        matches = 0
        for exp in expected:
            exp_name = Path(exp).stem.lower()
            for ret in retrieved:
                if exp_name in ret.lower():
                    matches += 1
                    break

        precision = matches / len(retrieved) if retrieved else 0
        recall = matches / len(expected) if expected else 0

        total_precision += precision
        total_recall += recall
        valid_count += 1

    if valid_count == 0:
        return {}

    return {
        'retrieval_precision': total_precision / valid_count,
        'retrieval_recall': total_recall / valid_count,
    }


def run_evaluation(kg_path: str, dataset_path: str, output_path: str) -> int:
    """Run full RAGAS evaluation pipeline."""
    print("=" * 60)
    print("CognitiveFS RAGAS Evaluation")
    print("=" * 60)

    # Load dataset
    samples = load_dataset(dataset_path)
    print(f"Loaded {len(samples)} evaluation samples")

    # Run RAG queries
    print("\n[1/2] Running RAG queries...")
    results = run_rag_queries(kg_path, samples)

    if not results:
        print("ERROR: No results from RAG queries.")
        return 1

    # Compute basic metrics
    latencies = [r['latency_ms'] for r in results]
    llm_available_count = sum(1 for r in results if r.get('llm_available'))

    # Run RAGAS evaluation
    print("\n[2/2] Running RAGAS evaluation...")
    ragas_scores = run_ragas_evaluation(results, output_path)

    # Compute retrieval metrics
    retrieval_metrics = compute_retrieval_metrics(results, samples)

    # Compile final results
    final_results = {
        'metadata': {
            'kg_path': kg_path,
            'dataset_path': dataset_path,
            'num_samples': len(samples),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'model': get_ollama_config()[1],
        },
        'ragas_metrics': ragas_scores,
        'retrieval_metrics': retrieval_metrics,
        'performance': {
            'avg_latency_ms': sum(latencies) / len(latencies) if latencies else 0,
            'min_latency_ms': min(latencies) if latencies else 0,
            'max_latency_ms': max(latencies) if latencies else 0,
            'llm_availability_rate': llm_available_count / len(results) if results else 0,
        },
        'samples': results,
    }

    # Save results
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(final_results, f, indent=2, ensure_ascii=False)

    # Print summary
    print("\n" + "=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)

    if ragas_scores:
        print("\nRAGAS Metrics (0-1, higher is better):")
        for metric, score in ragas_scores.items():
            print(f"  {metric}: {score:.3f}")

    if retrieval_metrics:
        print("\nRetrieval Metrics:")
        for metric, score in retrieval_metrics.items():
            print(f"  {metric}: {score:.3f}")

    print("\nPerformance:")
    print(f"  Avg latency: {final_results['performance']['avg_latency_ms']:.0f}ms")
    print(f"  LLM availability: {final_results['performance']['llm_availability_rate']:.0%}")

    print(f"\nResults saved to: {output_path}")
    print("=" * 60)

    # Return success if we got RAGAS scores
    return 0 if ragas_scores else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RAGAS evaluation for CognitiveFS RAG system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Generate dataset:  python tools/ragas_eval.py generate --kg test.kg.db --output eval_dataset.json
  Run evaluation:    python tools/ragas_eval.py run --kg test.kg.db --dataset eval_dataset.json --output results.json

Environment variables:
  OLLAMA_BASE_URL    Ollama server URL (default: http://localhost:11434)
  RAGAS_MODEL        Model for evaluation (default: llama3:8b)
        """
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Generate subcommand
    gen_parser = subparsers.add_parser("generate", help="Generate evaluation dataset from KG")
    gen_parser.add_argument("--kg", required=True, help="Path to knowledge graph .kg.db")
    gen_parser.add_argument("--output", required=True, help="Output JSON file")
    gen_parser.add_argument("--num-samples", type=int, default=20, help="Number of samples")

    # Run subcommand
    run_parser = subparsers.add_parser("run", help="Run RAGAS evaluation")
    run_parser.add_argument("--kg", required=True, help="Path to knowledge graph .kg.db")
    run_parser.add_argument("--dataset", required=True, help="Evaluation dataset JSON")
    run_parser.add_argument("--output", required=True, help="Output results JSON")

    args = parser.parse_args()

    if args.command == "generate":
        generate_dataset(args.kg, args.output, args.num_samples)
        return 0

    if args.command == "run":
        return run_evaluation(args.kg, args.dataset, args.output)

    return 1


if __name__ == "__main__":
    sys.exit(main())
