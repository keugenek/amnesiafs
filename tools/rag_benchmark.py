#!/usr/bin/env python3
"""
RAG Benchmark Evaluation for CognitiveFS.

Uses industry-standard datasets (RAGBench, SQuAD, etc.) and comprehensive metrics
to evaluate retrieval and generation quality.

Usage:
  # Run with RAGBench dataset
  python tools/rag_benchmark.py eval --kg test.kg.db --dataset ragbench --output results.json

  # Run with custom dataset
  python tools/rag_benchmark.py eval --kg test.kg.db --dataset custom.json --output results.json

  # List available datasets
  python tools/rag_benchmark.py list-datasets

Requirements:
  pip install datasets rouge-score bert-score sacrebleu nltk
"""

import argparse
import json
import os
import sys
import time
import re
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from collections import defaultdict

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Try importing evaluation libraries
try:
    from rouge_score import rouge_scorer
    ROUGE_AVAILABLE = True
except ImportError:
    ROUGE_AVAILABLE = False

try:
    from bert_score import score as bert_score
    BERT_SCORE_AVAILABLE = True
except ImportError:
    BERT_SCORE_AVAILABLE = False

try:
    import nltk
    from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False

try:
    from datasets import load_dataset
    HF_DATASETS_AVAILABLE = True
except ImportError:
    HF_DATASETS_AVAILABLE = False

# CognitiveFS imports
from cognitivefs.knowledge_graph import KnowledgeGraph
from cognitivefs.llm import OllamaClient, KnowledgeQueryEngine


@dataclass
class BenchmarkSample:
    """A single benchmark sample."""
    question: str
    reference_answer: str
    reference_contexts: List[str] = field(default_factory=list)
    domain: str = "general"
    difficulty: str = "medium"
    sample_id: str = ""


@dataclass
class EvalResult:
    """Result for a single evaluation."""
    sample_id: str
    question: str
    generated_answer: str
    reference_answer: str
    retrieved_contexts: List[str]
    reference_contexts: List[str]
    metrics: Dict[str, float]
    latency_ms: float


class MetricsCalculator:
    """Calculate various RAG evaluation metrics."""

    def __init__(self):
        self.rouge_scorer = None
        if ROUGE_AVAILABLE:
            self.rouge_scorer = rouge_scorer.RougeScorer(
                ['rouge1', 'rouge2', 'rougeL'], use_stemmer=True
            )

        if NLTK_AVAILABLE:
            try:
                nltk.data.find('tokenizers/punkt')
            except LookupError:
                nltk.download('punkt', quiet=True)

    def calculate_all(
        self,
        generated: str,
        reference: str,
        retrieved_contexts: List[str],
        reference_contexts: List[str]
    ) -> Dict[str, float]:
        """Calculate all available metrics."""
        metrics = {}

        # Text overlap metrics
        metrics.update(self._exact_match(generated, reference))
        metrics.update(self._f1_score(generated, reference))

        # ROUGE scores
        if self.rouge_scorer:
            metrics.update(self._rouge_scores(generated, reference))

        # BLEU score
        if NLTK_AVAILABLE:
            metrics.update(self._bleu_score(generated, reference))

        # Retrieval metrics
        metrics.update(self._retrieval_metrics(retrieved_contexts, reference_contexts))

        # Answer quality metrics
        metrics.update(self._answer_quality(generated, reference))

        return metrics

    def _exact_match(self, generated: str, reference: str) -> Dict[str, float]:
        """Exact match after normalization."""
        def normalize(text):
            text = text.lower().strip()
            text = re.sub(r'[^\w\s]', '', text)
            text = ' '.join(text.split())
            return text

        return {'exact_match': 1.0 if normalize(generated) == normalize(reference) else 0.0}

    def _f1_score(self, generated: str, reference: str) -> Dict[str, float]:
        """Token-level F1 score."""
        gen_tokens = set(generated.lower().split())
        ref_tokens = set(reference.lower().split())

        if not gen_tokens or not ref_tokens:
            return {'token_f1': 0.0, 'token_precision': 0.0, 'token_recall': 0.0}

        common = gen_tokens & ref_tokens
        precision = len(common) / len(gen_tokens) if gen_tokens else 0
        recall = len(common) / len(ref_tokens) if ref_tokens else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        return {
            'token_f1': f1,
            'token_precision': precision,
            'token_recall': recall
        }

    def _rouge_scores(self, generated: str, reference: str) -> Dict[str, float]:
        """ROUGE scores for summarization quality."""
        scores = self.rouge_scorer.score(reference, generated)
        return {
            'rouge1_f': scores['rouge1'].fmeasure,
            'rouge2_f': scores['rouge2'].fmeasure,
            'rougeL_f': scores['rougeL'].fmeasure,
        }

    def _bleu_score(self, generated: str, reference: str) -> Dict[str, float]:
        """BLEU score for translation-like quality."""
        try:
            gen_tokens = generated.lower().split()
            ref_tokens = [reference.lower().split()]

            smoothing = SmoothingFunction().method1
            score = sentence_bleu(ref_tokens, gen_tokens, smoothing_function=smoothing)
            return {'bleu': score}
        except Exception:
            return {'bleu': 0.0}

    def _retrieval_metrics(
        self,
        retrieved: List[str],
        reference: List[str]
    ) -> Dict[str, float]:
        """Retrieval precision, recall, and MRR."""
        if not reference:
            return {
                'retrieval_precision': 0.0,
                'retrieval_recall': 0.0,
                'retrieval_mrr': 0.0,
                'retrieval_hit@1': 0.0,
                'retrieval_hit@3': 0.0,
            }

        # Normalize for comparison
        def normalize_path(p):
            return Path(p).stem.lower() if p else ""

        retrieved_normalized = [normalize_path(p) for p in retrieved]
        reference_normalized = [normalize_path(p) for p in reference]

        # Count hits
        hits = 0
        first_hit_rank = None
        for i, ret in enumerate(retrieved_normalized):
            for ref in reference_normalized:
                if ref in ret or ret in ref:
                    hits += 1
                    if first_hit_rank is None:
                        first_hit_rank = i + 1
                    break

        precision = hits / len(retrieved) if retrieved else 0
        recall = hits / len(reference) if reference else 0
        mrr = 1.0 / first_hit_rank if first_hit_rank else 0
        hit_at_1 = 1.0 if first_hit_rank == 1 else 0
        hit_at_3 = 1.0 if first_hit_rank and first_hit_rank <= 3 else 0

        return {
            'retrieval_precision': precision,
            'retrieval_recall': recall,
            'retrieval_mrr': mrr,
            'retrieval_hit@1': hit_at_1,
            'retrieval_hit@3': hit_at_3,
        }

    def _answer_quality(self, generated: str, reference: str) -> Dict[str, float]:
        """Answer quality metrics."""
        # Length ratio
        gen_len = len(generated.split())
        ref_len = len(reference.split())
        length_ratio = gen_len / ref_len if ref_len > 0 else 0

        # Check for empty or very short answers
        is_empty = 1.0 if gen_len < 3 else 0.0

        # Check if answer contains key reference terms
        ref_key_terms = set(w.lower() for w in reference.split() if len(w) > 4)
        gen_terms = set(generated.lower().split())
        key_term_coverage = len(ref_key_terms & gen_terms) / len(ref_key_terms) if ref_key_terms else 0

        return {
            'answer_length_ratio': min(length_ratio, 2.0),  # Cap at 2x
            'answer_empty': is_empty,
            'key_term_coverage': key_term_coverage,
        }


class BenchmarkDatasetLoader:
    """Load benchmark datasets from various sources."""

    AVAILABLE_DATASETS = {
        'ragbench': {
            'hf_name': 'galileo-ai/ragbench',
            'description': '100K examples across 5 industry domains',
            'subsets': ['techqa', 'finqa', 'bioasq', 'cuad', 'nq'],
        },
        'squad': {
            'hf_name': 'squad',
            'description': 'Stanford Question Answering Dataset',
        },
        'natural_questions': {
            'hf_name': 'natural_questions',
            'description': 'Google Natural Questions',
        },
        'triviaqa': {
            'hf_name': 'trivia_qa',
            'description': 'TriviaQA reading comprehension',
        },
    }

    @classmethod
    def list_datasets(cls) -> Dict[str, str]:
        """List available datasets."""
        return {k: v['description'] for k, v in cls.AVAILABLE_DATASETS.items()}

    @classmethod
    def load(cls, name: str, subset: str = None, max_samples: int = 100) -> List[BenchmarkSample]:
        """Load a benchmark dataset."""
        if name.endswith('.json'):
            return cls._load_custom(name)

        if name == 'synthetic':
            return cls._generate_synthetic(max_samples)

        if name not in cls.AVAILABLE_DATASETS:
            raise ValueError(f"Unknown dataset: {name}. Available: {list(cls.AVAILABLE_DATASETS.keys()) + ['synthetic']}")

        if not HF_DATASETS_AVAILABLE:
            raise ImportError("Install datasets: pip install datasets")

        config = cls.AVAILABLE_DATASETS[name]

        if name == 'ragbench':
            return cls._load_ragbench(subset, max_samples)
        elif name == 'squad':
            return cls._load_squad(max_samples)
        else:
            return cls._load_generic_hf(config['hf_name'], max_samples)

    @classmethod
    def _load_ragbench(cls, subset: str = None, max_samples: int = 100) -> List[BenchmarkSample]:
        """Load RAGBench dataset."""
        samples = []

        try:
            if subset:
                ds = load_dataset('galileo-ai/ragbench', subset, split='test')
            else:
                # Load a mix from different subsets
                subsets = ['techqa', 'finqa']
                ds_list = []
                for sub in subsets:
                    try:
                        sub_ds = load_dataset('galileo-ai/ragbench', sub, split='test')
                        ds_list.extend(list(sub_ds.take(max_samples // len(subsets))))
                    except Exception:
                        continue
                ds = ds_list

            for i, item in enumerate(ds):
                if i >= max_samples:
                    break

                samples.append(BenchmarkSample(
                    sample_id=f"ragbench_{i}",
                    question=item.get('question', item.get('query', '')),
                    reference_answer=item.get('answer', item.get('response', '')),
                    reference_contexts=item.get('contexts', item.get('documents', [])),
                    domain=subset or 'mixed',
                ))
        except Exception as e:
            print(f"Warning: Could not load RAGBench: {e}")
            print("Falling back to synthetic dataset...")
            return cls._generate_synthetic(max_samples)

        return samples

    @classmethod
    def _load_squad(cls, max_samples: int = 100) -> List[BenchmarkSample]:
        """Load SQuAD dataset."""
        samples = []
        ds = load_dataset('squad', split='validation')

        for i, item in enumerate(ds):
            if i >= max_samples:
                break

            samples.append(BenchmarkSample(
                sample_id=f"squad_{item['id']}",
                question=item['question'],
                reference_answer=item['answers']['text'][0] if item['answers']['text'] else '',
                reference_contexts=[item['context']],
                domain='wikipedia',
            ))

        return samples

    @classmethod
    def _load_generic_hf(cls, dataset_name: str, max_samples: int) -> List[BenchmarkSample]:
        """Generic HuggingFace dataset loader."""
        samples = []
        ds = load_dataset(dataset_name, split='validation')

        for i, item in enumerate(ds):
            if i >= max_samples:
                break

            # Try common field names
            question = item.get('question', item.get('query', item.get('input', '')))
            answer = item.get('answer', item.get('response', item.get('output', '')))
            contexts = item.get('contexts', item.get('documents', item.get('passages', [])))

            if isinstance(answer, dict):
                answer = answer.get('text', str(answer))
            if isinstance(answer, list):
                answer = answer[0] if answer else ''

            samples.append(BenchmarkSample(
                sample_id=f"{dataset_name}_{i}",
                question=str(question),
                reference_answer=str(answer),
                reference_contexts=contexts if isinstance(contexts, list) else [contexts],
            ))

        return samples

    @classmethod
    def _load_custom(cls, path: str) -> List[BenchmarkSample]:
        """Load custom JSON dataset."""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        samples = []
        for i, item in enumerate(data):
            samples.append(BenchmarkSample(
                sample_id=item.get('id', f"custom_{i}"),
                question=item.get('question', item.get('query', '')),
                reference_answer=item.get('answer', item.get('reference', '')),
                reference_contexts=item.get('contexts', item.get('expected_contexts', [])),
                domain=item.get('domain', 'custom'),
            ))

        return samples

    @classmethod
    def _generate_synthetic(cls, num_samples: int) -> List[BenchmarkSample]:
        """Generate synthetic benchmark samples for testing."""
        templates = [
            ("What is {topic}?", "{topic} is a {type} that {description}."),
            ("How does {topic} work?", "{topic} works by {mechanism}."),
            ("What are the benefits of {topic}?", "The benefits of {topic} include {benefits}."),
            ("When was {topic} created?", "{topic} was created in {year}."),
            ("Who developed {topic}?", "{topic} was developed by {creator}."),
        ]

        topics = [
            ("machine learning", "technology", "enables computers to learn from data", "pattern recognition", "2000s", "multiple researchers"),
            ("CognitiveFS", "filesystem", "combines AI with file management", "semantic understanding", "2024", "Anthropic engineers"),
            ("knowledge graphs", "data structure", "represents relationships between entities", "linking concepts", "1970s", "computer scientists"),
            ("embeddings", "vector representation", "captures semantic meaning in numbers", "enabling similarity search", "2010s", "NLP researchers"),
            ("FUSE", "interface", "allows filesystems in userspace", "kernel callbacks", "2004", "Miklos Szeredi"),
        ]

        samples = []
        for i in range(min(num_samples, len(templates) * len(topics))):
            template_idx = i % len(templates)
            topic_idx = i // len(templates) % len(topics)

            q_template, a_template = templates[template_idx]
            topic_data = topics[topic_idx]

            question = q_template.format(topic=topic_data[0])
            answer = a_template.format(
                topic=topic_data[0],
                type=topic_data[1],
                description=topic_data[2],
                mechanism=topic_data[2],
                benefits=topic_data[3],
                year=topic_data[4],
                creator=topic_data[5],
            )

            samples.append(BenchmarkSample(
                sample_id=f"synthetic_{i}",
                question=question,
                reference_answer=answer,
                domain="synthetic",
            ))

        return samples


class RAGBenchmarkRunner:
    """Run RAG benchmark evaluation."""

    def __init__(self, kg_path: str, ollama_url: str = None, model: str = None):
        self.kg_path = kg_path
        self.ollama_url = ollama_url or os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
        self.model = model or os.environ.get('RAG_MODEL', 'qwen2.5:14b-instruct-q4_K_M')

        self.kg = None
        self.llm = None
        self.engine = None
        self.metrics_calc = MetricsCalculator()

    def setup(self) -> bool:
        """Initialize knowledge graph and LLM."""
        try:
            self.kg = KnowledgeGraph(self.kg_path)
            self.kg.open()

            self.llm = OllamaClient(base_url=self.ollama_url, model=self.model)
            self.engine = KnowledgeQueryEngine(self.kg, self.llm)

            if not self.llm.is_available:
                print(f"Warning: Ollama not available at {self.ollama_url}")
                print("Will evaluate retrieval only (no generation).")

            return True
        except Exception as e:
            print(f"Setup error: {e}")
            return False

    def teardown(self):
        """Clean up resources."""
        if self.kg:
            self.kg.close()

    def run_sample(self, sample: BenchmarkSample) -> EvalResult:
        """Run evaluation on a single sample."""
        start_time = time.time()

        # Run RAG query
        result = self.engine.query_with_context(sample.question, max_context_files=5)

        latency_ms = (time.time() - start_time) * 1000

        # Extract generated answer
        generated_answer = result.get('answer', '')

        # Extract retrieved contexts
        retrieved_contexts = []
        for file_info in result.get('files_used', []):
            retrieved_contexts.append(file_info.get('path', ''))

        # Calculate metrics
        metrics = self.metrics_calc.calculate_all(
            generated=generated_answer,
            reference=sample.reference_answer,
            retrieved_contexts=retrieved_contexts,
            reference_contexts=sample.reference_contexts,
        )

        return EvalResult(
            sample_id=sample.sample_id,
            question=sample.question,
            generated_answer=generated_answer,
            reference_answer=sample.reference_answer,
            retrieved_contexts=retrieved_contexts,
            reference_contexts=sample.reference_contexts,
            metrics=metrics,
            latency_ms=latency_ms,
        )

    def run_benchmark(
        self,
        samples: List[BenchmarkSample],
        verbose: bool = True
    ) -> Dict[str, Any]:
        """Run full benchmark evaluation."""
        results = []

        for i, sample in enumerate(samples):
            if verbose:
                print(f"  [{i+1}/{len(samples)}] {sample.question[:50]}...", end=" ", flush=True)

            try:
                result = self.run_sample(sample)
                results.append(result)

                if verbose:
                    f1 = result.metrics.get('token_f1', 0)
                    print(f"F1={f1:.2f} ({result.latency_ms:.0f}ms)")
            except Exception as e:
                if verbose:
                    print(f"ERROR: {e}")
                results.append(EvalResult(
                    sample_id=sample.sample_id,
                    question=sample.question,
                    generated_answer="",
                    reference_answer=sample.reference_answer,
                    retrieved_contexts=[],
                    reference_contexts=sample.reference_contexts,
                    metrics={'error': 1.0},
                    latency_ms=0,
                ))

        # Aggregate metrics
        aggregated = self._aggregate_metrics(results)

        return {
            'summary': aggregated,
            'results': [asdict(r) for r in results],
            'metadata': {
                'kg_path': self.kg_path,
                'model': self.model,
                'num_samples': len(samples),
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            }
        }

    def _aggregate_metrics(self, results: List[EvalResult]) -> Dict[str, float]:
        """Aggregate metrics across all results."""
        if not results:
            return {}

        # Collect all metric values
        metric_values = defaultdict(list)
        for result in results:
            for metric, value in result.metrics.items():
                if isinstance(value, (int, float)):
                    metric_values[metric].append(value)

        # Calculate mean for each metric
        aggregated = {}
        for metric, values in metric_values.items():
            aggregated[f'mean_{metric}'] = sum(values) / len(values)

        # Add latency stats
        latencies = [r.latency_ms for r in results]
        aggregated['mean_latency_ms'] = sum(latencies) / len(latencies)
        aggregated['p50_latency_ms'] = sorted(latencies)[len(latencies) // 2]
        aggregated['p95_latency_ms'] = sorted(latencies)[int(len(latencies) * 0.95)]

        return aggregated


def print_results(results: Dict[str, Any]) -> None:
    """Pretty print evaluation results."""
    print("\n" + "=" * 70)
    print("RAG BENCHMARK RESULTS")
    print("=" * 70)

    summary = results.get('summary', {})

    # Core metrics
    print("\n[Answer Quality]")
    print(f"  Token F1:          {summary.get('mean_token_f1', 0):.3f}")
    print(f"  Exact Match:       {summary.get('mean_exact_match', 0):.3f}")
    print(f"  Key Term Coverage: {summary.get('mean_key_term_coverage', 0):.3f}")

    if ROUGE_AVAILABLE:
        print("\n[ROUGE Scores]")
        print(f"  ROUGE-1 F1:   {summary.get('mean_rouge1_f', 0):.3f}")
        print(f"  ROUGE-2 F1:   {summary.get('mean_rouge2_f', 0):.3f}")
        print(f"  ROUGE-L F1:   {summary.get('mean_rougeL_f', 0):.3f}")

    print("\n[Retrieval Quality]")
    print(f"  Precision:    {summary.get('mean_retrieval_precision', 0):.3f}")
    print(f"  Recall:       {summary.get('mean_retrieval_recall', 0):.3f}")
    print(f"  MRR:          {summary.get('mean_retrieval_mrr', 0):.3f}")
    print(f"  Hit@1:        {summary.get('mean_retrieval_hit@1', 0):.3f}")
    print(f"  Hit@3:        {summary.get('mean_retrieval_hit@3', 0):.3f}")

    print("\n[Performance]")
    print(f"  Mean Latency:  {summary.get('mean_latency_ms', 0):.0f} ms")
    print(f"  P50 Latency:   {summary.get('p50_latency_ms', 0):.0f} ms")
    print(f"  P95 Latency:   {summary.get('p95_latency_ms', 0):.0f} ms")

    print("\n[Metadata]")
    meta = results.get('metadata', {})
    print(f"  Model:    {meta.get('model', 'N/A')}")
    print(f"  Samples:  {meta.get('num_samples', 0)}")
    print(f"  Time:     {meta.get('timestamp', 'N/A')}")

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="RAG Benchmark Evaluation for CognitiveFS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest='command', required=True)

    # List datasets command
    list_parser = subparsers.add_parser('list-datasets', help='List available benchmark datasets')

    # Eval command
    eval_parser = subparsers.add_parser('eval', help='Run benchmark evaluation')
    eval_parser.add_argument('--kg', required=True, help='Path to knowledge graph .kg.db')
    eval_parser.add_argument('--dataset', default='synthetic',
                            help='Dataset name (ragbench, squad, synthetic) or path to JSON')
    eval_parser.add_argument('--subset', help='Dataset subset (e.g., techqa for ragbench)')
    eval_parser.add_argument('--max-samples', type=int, default=50, help='Max samples to evaluate')
    eval_parser.add_argument('--output', help='Output JSON file for results')
    eval_parser.add_argument('--model', help='Ollama model to use')
    eval_parser.add_argument('-q', '--quiet', action='store_true', help='Quiet mode')

    args = parser.parse_args()

    if args.command == 'list-datasets':
        print("Available Benchmark Datasets:")
        print("-" * 50)
        for name, desc in BenchmarkDatasetLoader.list_datasets().items():
            print(f"  {name:20} {desc}")
        print("-" * 50)
        print("\nYou can also use a path to a custom JSON file.")
        return 0

    if args.command == 'eval':
        print("=" * 70)
        print("CognitiveFS RAG Benchmark Evaluation")
        print("=" * 70)

        # Load dataset
        print(f"\n[1/3] Loading dataset: {args.dataset}")
        try:
            samples = BenchmarkDatasetLoader.load(
                args.dataset,
                subset=args.subset,
                max_samples=args.max_samples
            )
            print(f"  Loaded {len(samples)} samples")
        except Exception as e:
            print(f"ERROR: Failed to load dataset: {e}")
            return 1

        # Setup runner
        print(f"\n[2/3] Setting up RAG system")
        runner = RAGBenchmarkRunner(args.kg, model=args.model)
        if not runner.setup():
            print("ERROR: Failed to setup RAG system")
            return 1

        # Run benchmark
        print(f"\n[3/3] Running benchmark")
        try:
            results = runner.run_benchmark(samples, verbose=not args.quiet)
        finally:
            runner.teardown()

        # Print results
        print_results(results)

        # Save results
        if args.output:
            os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"\nResults saved to: {args.output}")

        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
