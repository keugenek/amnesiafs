# RAG Benchmark Datasets Reference

## 1. RAGBench (Galileo) - RECOMMENDED

```python
from datasets import load_dataset

# Full dataset: 100,000 examples across 5 domains
ragbench = load_dataset("galileo-ai/ragbench")

# Or specific subset
ragbench_tech = load_dataset("galileo-ai/ragbench", "techqa")
```

| Feature | Details |
|---------|---------|
| Size | 100,000 examples |
| Domains | 5 industry-specific (user manuals, tech docs) |
| Splits | Train/Val/Test for 12 sub-datasets |
| Downloads | 9,000+/month |
| License | Open |

---

## 2. NVIDIA ChatRAG-Bench - PRODUCTION TESTED

```python
from datasets import load_dataset

# Multiple conversational QA datasets
chatrag = load_dataset("nvidia/ChatRAG-Bench")

# Individual subsets:
coqa = load_dataset("nvidia/ChatRAG-Bench", "coqa")        # 7,980 rows
doc2dial = load_dataset("nvidia/ChatRAG-Bench", "doc2dial")
quac = load_dataset("nvidia/ChatRAG-Bench", "quac")
```

| Subset | Size | Type |
|--------|------|------|
| CoQA | 7,980 | Conversational QA |
| Doc2Dial | ~4,800 | Document-grounded |
| QuAC | ~8,000 | QA in context |
| DoQA (cooking/movies/travel) | ~3,000 each | Domain-specific |
| **Total** | ~40,000+ | Mixed |

---

## 3. MoNaCo Benchmark (Allen AI) - MULTI-HOP

```python
from datasets import load_dataset

# 1,315 human-written multi-hop questions
monaco = load_dataset("allenai/MoNaCo_Benchmark")
```

| Feature | Details |
|---------|---------|
| Size | 1,315 questions |
| Type | Multi-document reasoning |
| Includes | Full reasoning chains, intermediate Q&A |
| Best for | Testing complex retrieval |

---

## 4. RAG Mini Datasets (HuggingFace) - QUICK START

```python
from datasets import load_dataset

# Small, focused datasets
bioasq = load_dataset("rag-datasets/rag-mini-bioasq")
wikipedia = load_dataset("rag-datasets/rag-mini-wikipedia")
```

| Dataset | Size | Domain |
|---------|------|--------|
| rag-mini-bioasq | ~500 | Biomedical |
| rag-mini-wikipedia | ~500 | General knowledge |

---

## 5. Open RAG Bench (Vectara) - MULTIMODAL

```python
# GitHub: https://github.com/vectara/open-rag-bench
# Focus: PDF documents with tables/images
```

| Feature | Details |
|---------|---------|
| Source | arXiv PDFs |
| Type | Multimodal (text + tables + images) |
| Best for | Document understanding |

---

## Evaluation Plan

### Phase 1: Quick Validation
```python
# Use RAG Mini for fast iteration
from datasets import load_dataset
wiki = load_dataset("rag-datasets/rag-mini-wikipedia")
# ~500 questions, quick to run
```

### Phase 2: Production Benchmark
```python
# Use NVIDIA ChatRAG-Bench subset
from datasets import load_dataset
coqa = load_dataset("nvidia/ChatRAG-Bench", "coqa")
# Run on 500 random samples
import random
sample = random.sample(list(coqa['test']), 500)
```

### Phase 3: Full Benchmark (Publication-ready)
```python
# Use RAGBench for comprehensive eval
from datasets import load_dataset
ragbench = load_dataset("galileo-ai/ragbench")
# Run on 1,000+ samples across domains
```

---

## Industry Comparison Targets

| Metric | Minimum | Standard | Publication-ready |
|--------|---------|----------|-------------------|
| Sample Size | 100-200 | 500+ | 1,000+ |
| Domains | 3+ | 5+ | 10+ |
| Question Types | Factual | + Multi-hop | + Unanswerable |
| Documents | 100+ real | 1,000+ | 10,000+ |

---

## Quick Start Code

```python
# Install
pip install datasets ragas rouge-score bert-score

# Run evaluation
from datasets import load_dataset
from ragas import evaluate
from ragas.metrics import context_precision, answer_relevancy, faithfulness

# Load industry benchmark
dataset = load_dataset("nvidia/ChatRAG-Bench", "coqa", split="test[:500]")

# Format for your RAG system
test_samples = []
for row in dataset:
    test_samples.append({
        "question": row["question"],
        "ground_truth": row["answer"],
        "contexts": your_rag_system.retrieve(row["question"]),
        "answer": your_rag_system.generate(row["question"])
    })

# Run RAGAS eval
results = evaluate(test_samples, metrics=[
    context_precision,
    answer_relevancy,
    faithfulness
])

print(f"Context Precision: {results['context_precision']:.3f}")
print(f"Answer Relevancy: {results['answer_relevancy']:.3f}")
print(f"Faithfulness: {results['faithfulness']:.3f}")
```

---

## Dataset Selection Guide

| Dataset | Best For | Effort | Credibility |
|---------|----------|--------|-------------|
| rag-mini-wikipedia | Quick dev testing | Low | Low |
| NVIDIA ChatRAG-Bench | Production validation | Medium | High |
| RAGBench (Galileo) | Publication-ready claims | High | Very High |

**Recommendation**: Run CognitiveFS on NVIDIA ChatRAG-Bench CoQA subset (500 samples) for comparable benchmarks.
