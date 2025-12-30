#!/usr/bin/env python3
"""
Import benchmark documents into CognitiveFS knowledge graph.

This allows running RAG evaluations against actual benchmark documents.

Usage:
  python tools/import_benchmark_docs.py --kg test.kg.db --dataset ragbench --max-docs 100
"""

import argparse
import os
import sys
import hashlib
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from datasets import load_dataset
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False

from cognitivefs.knowledge_graph import KnowledgeGraph


def import_ragbench(kg: KnowledgeGraph, subset: str = None, max_docs: int = 100) -> int:
    """Import RAGBench documents into knowledge graph."""
    print(f"Loading RAGBench dataset{f' ({subset})' if subset else ''}...")

    try:
        if subset:
            ds = load_dataset('galileo-ai/ragbench', subset, split='test')
        else:
            # Load techqa and finqa
            subsets = ['techqa', 'finqa']
            ds = []
            for sub in subsets:
                try:
                    sub_ds = load_dataset('galileo-ai/ragbench', sub, split='test')
                    ds.extend(list(sub_ds))
                except Exception as e:
                    print(f"  Warning: Could not load {sub}: {e}")
    except Exception as e:
        print(f"ERROR: Failed to load RAGBench: {e}")
        return 0

    imported = 0
    seen_hashes = set()

    for i, item in enumerate(ds):
        if imported >= max_docs:
            break

        # Get contexts/documents from the sample
        contexts = item.get('contexts', item.get('documents', []))
        if not contexts:
            continue

        for j, ctx in enumerate(contexts):
            if imported >= max_docs:
                break

            if not ctx or len(ctx) < 50:
                continue

            # Create unique path based on content hash
            content_hash = hashlib.md5(ctx.encode()).hexdigest()[:12]
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)

            path = f"/benchmark/ragbench/doc_{i}_{j}_{content_hash}.txt"

            # Check if already exists
            existing = kg.get_file(path)
            if existing:
                continue

            # Index the document
            kg.upsert_file(
                path=path,
                inode=None,  # Virtual file
                size=len(ctx),
                content_hash=content_hash,
                extracted_text=ctx,
                summary=ctx[:500] if len(ctx) > 500 else ctx,
            )
            imported += 1

            if imported % 10 == 0:
                print(f"  Imported {imported} documents...")

    return imported


def import_squad(kg: KnowledgeGraph, max_docs: int = 100) -> int:
    """Import SQuAD contexts into knowledge graph."""
    print("Loading SQuAD dataset...")

    ds = load_dataset('squad', split='validation')

    imported = 0
    seen_hashes = set()

    for i, item in enumerate(ds):
        if imported >= max_docs:
            break

        ctx = item.get('context', '')
        if not ctx or len(ctx) < 50:
            continue

        content_hash = hashlib.md5(ctx.encode()).hexdigest()[:12]
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)

        title = item.get('title', 'unknown').replace(' ', '_')[:50]
        path = f"/benchmark/squad/{title}_{content_hash}.txt"

        existing = kg.get_file(path)
        if existing:
            continue

        kg.upsert_file(
            path=path,
            inode=None,
            size=len(ctx),
            content_hash=content_hash,
            extracted_text=ctx,
            summary=ctx[:500],
        )
        imported += 1

        if imported % 10 == 0:
            print(f"  Imported {imported} documents...")

    return imported


def main():
    parser = argparse.ArgumentParser(description="Import benchmark docs into KG")
    parser.add_argument('--kg', required=True, help='Path to knowledge graph')
    parser.add_argument('--dataset', default='ragbench',
                       choices=['ragbench', 'squad'],
                       help='Dataset to import')
    parser.add_argument('--subset', help='Dataset subset (e.g., techqa)')
    parser.add_argument('--max-docs', type=int, default=100, help='Max docs to import')

    args = parser.parse_args()

    if not HF_AVAILABLE:
        print("ERROR: Install datasets: pip install datasets")
        return 1

    print(f"Opening knowledge graph: {args.kg}")
    kg = KnowledgeGraph(args.kg)
    kg.open()

    try:
        if args.dataset == 'ragbench':
            imported = import_ragbench(kg, args.subset, args.max_docs)
        elif args.dataset == 'squad':
            imported = import_squad(kg, args.max_docs)
        else:
            print(f"Unknown dataset: {args.dataset}")
            return 1

        print(f"\nImported {imported} documents into knowledge graph")
        print("You can now run evaluation against these documents.")

    finally:
        kg.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
