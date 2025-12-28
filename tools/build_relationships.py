#!/usr/bin/env python3
"""
Build relationships for existing indexed files.

Run this to create co-occurrence and similarity relationships
for files that were indexed before relationship detection was added.
"""

import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cognitivefs.knowledge_graph import KnowledgeGraph
from cognitivefs.relationship_detector import build_relationship_graph


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Build relationships for existing files')
    parser.add_argument('db_path', help='Path to knowledge graph database (e.g., brain.kg.db)')
    args = parser.parse_args()

    if not os.path.exists(args.db_path):
        print(f"Database not found: {args.db_path}")
        sys.exit(1)

    print(f"Opening knowledge graph: {args.db_path}")
    kg = KnowledgeGraph(args.db_path)
    kg.open()

    try:
        stats_before = kg.get_stats()
        print(f"Before: {stats_before['relationships']} relationships")

        print("Building relationships...")
        result = build_relationship_graph(kg)

        stats_after = kg.get_stats()
        print(f"After: {stats_after['relationships']} relationships")
        print(f"Created: {result}")

    finally:
        kg.close()


if __name__ == '__main__':
    main()
