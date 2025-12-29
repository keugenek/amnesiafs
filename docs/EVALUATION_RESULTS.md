# CognitiveFS RAG Evaluation Results

## Overview

This document captures the results of RAGAS (Retrieval Augmented Generation Assessment) evaluation for CognitiveFS's RAG system. RAGAS is an academically proven framework used by industry leaders (Elastic, Neptune.ai, Microsoft) for evaluating RAG pipelines.

## Evaluation Setup

| Component | Value |
|-----------|-------|
| **Framework** | RAGAS v0.4.2 |
| **Evaluator LLM** | qwen2.5:14b-instruct-q4_K_M (via Ollama) |
| **Test Samples** | 10 curated questions |
| **Knowledge Graph** | 10 synthetic documents |
| **Date** | 2025-12-29 |

## Results Summary

### RAGAS Metrics (0-1 scale, higher is better)

| Metric | Score | Industry Benchmark | Status |
|--------|-------|-------------------|--------|
| **Faithfulness** | 0.564 | 0.7+ | Needs improvement |
| **Answer Relevancy** | 0.280 | 0.7+ | Needs improvement |
| **Context Precision** | 0.100 | 0.6+ | Needs improvement |
| **Context Recall** | 0.200 | 0.6+ | Needs improvement |

### Performance Metrics

| Metric | Value |
|--------|-------|
| **Avg Query Latency** | 5,829 ms |
| **Min Latency** | ~3,000 ms |
| **Max Latency** | ~20,000 ms |
| **LLM Availability** | 100% |

## Metric Definitions

- **Faithfulness**: Measures whether the generated answer is grounded in the retrieved context (no hallucination)
- **Answer Relevancy**: Measures how well the answer addresses the user's question
- **Context Precision**: Measures whether the retrieved documents are relevant to the question
- **Context Recall**: Measures whether all relevant information was retrieved

## Analysis

### Strengths
1. **LLM Integration Working**: Successfully connects to Ollama and generates coherent responses
2. **Knowledge Graph Functional**: Files are indexed, entities extracted, embeddings generated
3. **End-to-End Pipeline**: Full RAG flow from query to response works reliably

### Weaknesses
1. **Low Context Precision (0.10)**: Retrieval often returns irrelevant documents
2. **Low Answer Relevancy (0.28)**: Responses don't fully address questions
3. **Moderate Faithfulness (0.56)**: Some hallucination in responses
4. **High Latency**: 6s average per query is slow for interactive use

### Root Causes
1. **Embedding Model**: Current model may not capture domain-specific semantics well
2. **Retrieval Strategy**: Simple similarity search without reranking
3. **Context Window**: Retrieved contexts may be too long/short
4. **Prompt Engineering**: Query prompts may need optimization

---

## Research-Based Improvement Roadmap

Based on deep research of 15+ recent arXiv papers (2024-2025) and industry best practices, this roadmap outlines state-of-the-art techniques for improving CognitiveFS's RAG system.

### RAG Evolution: Current State

| Paradigm | Description | CognitiveFS Status |
|----------|-------------|-------------------|
| **Naive RAG** | Simple retrieve -> read -> generate | Current |
| **Advanced RAG** | Pre/post-retrieval optimization | Target |
| **Modular RAG** | Pluggable components, routing | Future |

---

## Phase 1: Retrieval Foundation (P0 - Critical)

### 1.1 Hybrid Search (BM25 + Semantic)
**Problem**: Context precision at 0.10 means 90% of retrieved docs are irrelevant.

**Research**: Industry consensus shows BM25 + Dense + Sparse vectors provide 15-30% recall improvement. Three-way hybrid retrieval outperforms pure vector or two-way approaches ([IBM Research](https://infiniflow.org/blog/best-hybrid-search-solution)).

**Implementation**:
- [ ] Add SQLite FTS5 index for BM25 keyword search
- [ ] Implement Reciprocal Rank Fusion (RRF) for combining results
- [ ] Tune alpha parameter for BM25/semantic weighting

**Files**: `src/cognitivefs/knowledge_graph.py`

**Expected Impact**: Context precision 0.10 -> 0.40

### 1.2 Cross-Encoder Reranking
**Research**: BGE-reranker-v2-m3 and ColBERT provide significant precision improvements by scoring query-document pairs directly ([HuggingFace BGE](https://huggingface.co/BAAI/bge-reranker-v2-m3)).

**Implementation**:
- [ ] Add `src/cognitivefs/reranker.py` with CrossEncoder
- [ ] Integrate reranking after initial retrieval
- [ ] Use BAAI/bge-reranker-base (lightweight) or v2-m3 (8192 tokens)

**Files**: NEW `src/cognitivefs/reranker.py`, `src/cognitivefs/llm.py`

**Expected Impact**: +20% precision on retrieved results

---

## Phase 2: Query Enhancement (P1 - High)

### 2.1 RAG-Fusion Multi-Query
**Paper**: [RAG-Fusion (arXiv:2402.03367)](https://arxiv.org/abs/2402.03367)

**Key Insight**: Generate multiple query variants, retrieve for each, combine with RRF. Provides broader context coverage by contextualizing the original query from various perspectives.

**Implementation**:
- [ ] Add query expansion via LLM (3-5 variants)
- [ ] Parallel retrieval for each variant
- [ ] RRF fusion of all results

**Files**: `src/cognitivefs/llm.py`

### 2.2 HyDE (Hypothetical Document Embeddings)
**Paper**: [HyDE (arXiv:2212.10496)](https://arxiv.org/abs/2212.10496)

**Key Insight**: Generate a hypothetical answer document, embed it, use for retrieval. Improves semantic matching for sparse/ambiguous queries.

**Trade-off**: ~50% slower but better semantic matching. Best for complex queries.

**Implementation**:
- [ ] Generate hypothetical document for query
- [ ] Embed hypothetical document
- [ ] Use embedding for similarity search

### 2.3 Improved Prompts
**Problem**: Answer relevancy at 0.28 suggests prompts need work.

**Implementation**:
- [ ] Add structured instructions (ONLY use context, cite sources)
- [ ] Few-shot examples for complex queries
- [ ] Chain-of-thought for multi-step reasoning

**Files**: `src/cognitivefs/llm.py:_build_query_prompt()`

**Expected Impact**: Answer relevancy 0.28 -> 0.60

---

## Phase 3: Adaptive Retrieval (P1 - High)

### 3.1 CRAG (Corrective RAG)
**Paper**: [CRAG (arXiv:2401.15884)](https://arxiv.org/abs/2401.15884)

**Key Insight**: Lightweight retrieval evaluator (0.77B) scores retrieval quality. Triggers corrective actions (web search, decomposition) when evidence is weak.

**Implementation**:
- [ ] Add retrieval quality evaluator (CORRECT/AMBIGUOUS/INCORRECT)
- [ ] Fallback to "I don't have enough information" for INCORRECT
- [ ] Optional: web search fallback for ambiguous queries

**Files**: `src/cognitivefs/llm.py`

**Expected Impact**: Faithfulness 0.56 -> 0.75 (reduce hallucination)

### 3.2 Self-RAG
**Paper**: [Self-RAG (arXiv:2310.11511)](https://arxiv.org/abs/2310.11511)

**Key Insight**: Train LM with reflection/control tokens to decide when to retrieve and how to critique evidence. Adaptive retrieval on-demand.

**Implementation** (Advanced):
- [ ] Add reflection tokens for retrieval decisions
- [ ] Self-critique generated responses
- [ ] Iterative refinement loop

---

## Phase 4: Advanced Chunking (P2 - Medium)

### 4.1 Late Chunking
**Paper**: [Late Chunking (arXiv:2409.04701)](https://arxiv.org/abs/2409.04701)

**Key Insight**: Embed full document first, then chunk and pool. Preserves contextual information across chunk boundaries. 3.6% improvement over naive chunking.

**Implementation**:
- [ ] Embed full document with long-context model
- [ ] Pool token embeddings into chunk embeddings
- [ ] Store contextual chunk embeddings

**Files**: `src/cognitivefs/processor.py`, `src/cognitivefs/embedder.py`

### 4.2 RAPTOR (Hierarchical Retrieval)
**Paper**: [RAPTOR (arXiv:2401.18059)](https://arxiv.org/abs/2401.18059) - ICLR 2024

**Key Insight**: Build summary tree by recursively clustering and summarizing chunks. Retrieve at different abstraction levels. 20% improvement on multi-hop QA.

**Implementation**:
- [ ] Cluster similar chunks
- [ ] Generate cluster summaries
- [ ] Build hierarchical tree structure
- [ ] Retrieve from multiple tree levels

---

## Phase 5: Graph-Enhanced RAG (P2 - Medium)

### 5.1 GraphRAG
**Paper**: [GraphRAG (arXiv:2404.16130)](https://arxiv.org/abs/2404.16130) - Microsoft

**Key Insight**: Extract entity knowledge graph, detect communities, pre-generate community summaries. Excels at "connecting the dots" across disparate information.

**CognitiveFS Advantage**: Already has knowledge graph with entities!

**Implementation**:
- [ ] Add community detection (Louvain via networkx)
- [ ] Generate community summaries
- [ ] Retrieve at entity + community level
- [ ] Combine local (entity) and global (community) retrieval

**Files**: `src/cognitivefs/knowledge_graph.py`

**Resources**: [Microsoft GraphRAG](https://github.com/microsoft/graphrag)

---

## Phase 6: Agentic RAG (P3 - Future)

### 6.1 Multi-Agent Architecture
**Paper**: [Agentic RAG Survey (arXiv:2501.09136)](https://arxiv.org/abs/2501.09136)

**Key Insight**: Autonomous AI agents manage retrieval using reflection, planning, tool use, and multi-agent collaboration. Dynamic, context-sensitive retrieval.

**Conceptual Design**:
```
Query Router Agent (classify: factual/exploratory/multi-hop)
         |
    +----+----+
    v    v    v
Simple  Entity  Multi-hop
Agent   Agent   Agent
    +----+----+
         v
   Synthesizer Agent
```

**Implementation**:
- [ ] Query classification agent
- [ ] Specialized retrieval agents
- [ ] Response synthesis agent
- [ ] Agent coordination framework

### 6.2 Reasoning RAG
**Paper**: [Reasoning RAG (arXiv:2506.10408)](https://arxiv.org/html/2506.10408v1)

**Key Insight**: System 1 (predefined modular pipelines) vs System 2 (autonomous tool orchestration). Model autonomously orchestrates tool interaction during inference.

---

## Target Metrics

| Metric | Current | Phase 1 | Phase 2 | Phase 3 | Phase 4+ |
|--------|---------|---------|---------|---------|----------|
| Faithfulness | 0.56 | 0.65 | 0.70 | 0.80 | 0.85 |
| Answer Relevancy | 0.28 | 0.45 | 0.60 | 0.70 | 0.75 |
| Context Precision | 0.10 | 0.40 | 0.55 | 0.65 | 0.70 |
| Context Recall | 0.20 | 0.35 | 0.50 | 0.60 | 0.65 |
| Avg Latency | 6000ms | 5000ms | 4000ms | 3500ms | 3000ms |

---

## Running Evaluations

```bash
# Quick evaluation with host Ollama
./scripts/run-eval.sh

# Or with Docker Compose
docker compose -f docker-compose.eval.yml run --rm \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -e RAGAS_MODEL=qwen2.5:14b-instruct-q4_K_M \
  cognitivefs-eval python tools/ragas_eval.py run \
    --kg /workspace/test-data/test.kg.db \
    --dataset /workspace/test-data/eval_dataset.json \
    --output /workspace/eval-results/results.json

# Generate new test dataset from KG
python tools/ragas_eval.py generate \
  --kg test-data/test.kg.db \
  --output test-data/eval_dataset.json \
  --num-samples 20
```

## References

- [RAGAS Documentation](https://docs.ragas.io/)
- [RAGAS Paper](https://arxiv.org/abs/2309.15217)
- [LangChain RAG Tutorial](https://python.langchain.com/docs/tutorials/rag/)
- [Ollama Documentation](https://ollama.ai/docs)
