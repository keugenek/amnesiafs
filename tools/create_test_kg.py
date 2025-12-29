#!/usr/bin/env python3
"""
Create a test knowledge graph with sample data for RAGAS evaluation.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cognitivefs.knowledge_graph import KnowledgeGraph
from cognitivefs.processor import SyncProcessor


def create_test_kg(kg_path: str) -> None:
    """Create and populate a test knowledge graph."""
    print(f"Creating test knowledge graph at: {kg_path}")

    kg = KnowledgeGraph(kg_path)
    kg.open()

    proc = SyncProcessor(kg)

    # Sample documents that match our eval_dataset.json questions
    documents = [
        ("/docs/cognitivefs_overview.md", b"""
# CognitiveFS Overview

CognitiveFS is an AI-native filesystem built on FUSE (Filesystem in Userspace).
It provides semantic search and knowledge graph capabilities for your files.

## Key Features
- Semantic file search using natural language queries
- Automatic content extraction and indexing
- Knowledge graph with entity relationships
- Vector embeddings for similarity search

## Architecture
CognitiveFS consists of:
- FUSE layer for filesystem operations
- SQLite-backed knowledge graph
- Optional Ollama integration for LLM queries
- Background processor for async indexing
"""),
        ("/docs/installation_guide.md", b"""
# Installation Guide

## Prerequisites
- Python 3.8 or higher
- FUSE support (fuse3 package on Linux)
- SQLite3

## Installation Steps

1. Clone the repository:
   git clone https://github.com/keugenek/amnesiafs.git
   cd amnesiafs

2. Install dependencies:
   pip install -r requirements.txt

3. Format a device:
   python -m cognitivefs format /path/to/device

4. Mount the filesystem:
   python -m cognitivefs mount /path/to/device /mnt/point

## Docker Installation
Use the provided Docker setup for development:
   docker compose up -d
   docker exec -it cognitivefs bash
"""),
        ("/docs/semantic_search.md", b"""
# Semantic Search in CognitiveFS

CognitiveFS implements semantic search using vector embeddings and natural language processing.

## How Semantic Search Works

1. Content Extraction: Files are processed to extract text content
2. Embedding Generation: Text is converted to vector embeddings
3. Indexing: Embeddings are stored in the knowledge graph
4. Query Processing: User queries are embedded and compared

## Query Examples
- "Find all documents about Python"
- "Show me meeting notes from December"
- "What files mention machine learning?"

## Architecture
The semantic search is powered by:
- sentence-transformers for embeddings
- FAISS for vector similarity search (optional)
- SQLite FTS5 for full-text search fallback
"""),
        ("/docs/knowledge_graph_api.md", b"""
# Knowledge Graph API

The KnowledgeGraph class provides the core storage and retrieval functionality.

## Main Methods

### File Operations
- `add_file(path, inode, content)` - Add a file to the graph
- `get_file(path)` - Retrieve file metadata
- `search_files(query)` - Semantic file search
- `delete_file(path)` - Remove file from graph

### Entity Operations
- `add_entity(name, type)` - Add named entity
- `get_entities(type)` - List entities by type
- `link_file_entity(file_id, entity_id)` - Create relationship

### Query Methods
- `query_with_context(question)` - LLM-powered question answering
- `find_related_files(file_path)` - Get related files

## Example Usage
```python
from cognitivefs.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph("mydata.kg.db")
kg.open()

# Search for files
results = kg.search_files("meeting notes")
for file_record in results:
    print(file_record.path, file_record.summary)

kg.close()
```
"""),
        ("/projects/ml_project/readme.md", b"""
# Machine Learning Project

This project implements a neural network for image classification.

## Dependencies
- PyTorch 2.0+
- torchvision
- numpy
- matplotlib

## Model Architecture
The model uses a ResNet-50 backbone with custom classification head.

## Training
Run training with:
   python train.py --epochs 100 --batch-size 32

## Results
- Training accuracy: 95.2%
- Validation accuracy: 92.8%
"""),
        ("/notes/meeting_2024_12_20.md", b"""
# Team Meeting Notes - December 20, 2024

Attendees: Alice Johnson (alice@company.com), Bob Smith, Carol Davis

## Discussion Topics

### 1. CognitiveFS Progress
- Knowledge graph implementation complete
- RAGAS evaluation framework added
- Docker development environment working

### 2. Next Steps
- Improve semantic search accuracy
- Add more entity types to extraction
- Performance optimization for large files

### 3. Action Items
- Alice: Complete documentation by Dec 24
- Bob: Review RAGAS test results
- Carol: Set up CI/CD pipeline

Next meeting: December 27, 2024 at 2pm
"""),
        ("/config/settings.yaml", b"""
# CognitiveFS Configuration

filesystem:
  block_size: 4096
  max_file_size: 10GB
  cache_size: 256MB

knowledge_graph:
  database: default.kg.db
  embedding_model: all-MiniLM-L6-v2
  enable_faiss: true

llm:
  provider: ollama
  model: llama3:8b
  base_url: http://localhost:11434
  temperature: 0.7

processing:
  async_workers: 4
  batch_size: 10
  max_queue_size: 1000
"""),
        ("/docs/entity_extraction.md", b"""
# Entity Extraction in CognitiveFS

CognitiveFS automatically extracts named entities from indexed files.

## Supported Entity Types
- PERSON: People's names (e.g., "Alice Johnson")
- EMAIL: Email addresses (e.g., "user@example.com")
- DATE: Dates in various formats
- ORGANIZATION: Company and org names
- LOCATION: Geographic locations
- URL: Web addresses

## Extraction Methods
1. Regex patterns for structured data (emails, dates, URLs)
2. NER models for unstructured text (optional spaCy integration)

## Entity Relationships
Entities are linked to files through the file_entities table.
This enables queries like "find all files mentioning Alice".

## Configuration
Entity extraction is configurable in settings.yaml:
```yaml
extraction:
  enable_ner: true
  min_confidence: 0.7
  entity_types: [PERSON, EMAIL, DATE, ORG]
```
"""),
        ("/projects/web_app/api_docs.md", b"""
# Web Application API Documentation

## REST Endpoints

### Files API
- GET /api/files - List all indexed files
- GET /api/files/{id} - Get file details
- POST /api/files/search - Search files by query
- DELETE /api/files/{id} - Remove file from index

### Knowledge Graph API
- GET /api/entities - List all entities
- GET /api/entities/{type} - Get entities by type
- POST /api/query - Natural language query

## Authentication
All endpoints require Bearer token authentication.
Token format: `Authorization: Bearer <jwt_token>`

## Example Requests

### Search Files
```bash
curl -X POST /api/files/search \\
  -H "Authorization: Bearer $TOKEN" \\
  -d '{"query": "machine learning"}'
```

### Query Knowledge Graph
```bash
curl -X POST /api/query \\
  -H "Authorization: Bearer $TOKEN" \\
  -d '{"question": "What projects use PyTorch?"}'
```
"""),
        ("/notes/research_ideas.md", b"""
# Research Ideas and Notes

## Potential Improvements to CognitiveFS

### 1. Advanced Embedding Models
- Explore using larger models like E5-large
- Test multilingual embedding support
- Compare sentence-transformers vs OpenAI embeddings

### 2. Graph Neural Networks
- Apply GNN for relationship prediction
- Use entity co-occurrence for implicit relationships
- Explore knowledge graph completion techniques

### 3. Query Understanding
- Implement query expansion
- Add support for complex boolean queries
- Natural language to SQL translation

### 4. Performance Optimization
- Implement embedding caching
- Use approximate nearest neighbors (FAISS, ScaNN)
- Batch processing for bulk imports

## References
- "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
- "Dense Passage Retrieval for Open-Domain Question Answering"
- "BERT: Pre-training of Deep Bidirectional Transformers"
"""),
    ]

    print(f"Adding {len(documents)} test documents...")

    for i, (path, content) in enumerate(documents):
        print(f"  [{i+1}/{len(documents)}] Processing {path}")
        proc.process_file(path, 1000 + i, content)

    # Get stats
    stats = kg.get_stats()
    print("\nKnowledge Graph Statistics:")
    print(f"  Files indexed: {stats['files_indexed']}")
    print(f"  Entities: {stats['entities']}")
    print(f"  Relationships: {stats['relationships']}")
    print(f"  Embeddings: {stats['embeddings']}")

    if stats['entities_by_type']:
        print("\nEntities by type:")
        for etype, count in stats['entities_by_type'].items():
            print(f"  {etype}: {count}")

    kg.close()
    print(f"\nTest knowledge graph created: {kg_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Create test knowledge graph")
    parser.add_argument("--output", "-o", default="test-data/test.kg.db",
                        help="Output path for knowledge graph")
    args = parser.parse_args()

    create_test_kg(args.output)
