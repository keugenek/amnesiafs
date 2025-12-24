#!/usr/bin/env python3
"""
Integration test for knowledge extraction pipeline.
"""
import sys
sys.path.insert(0, 'src')

import os
import tempfile
import time

from cognitivefs.blockdev import BlockDevice
from cognitivefs.diskformat import Superblock
from cognitivefs.knowledge_graph import KnowledgeGraph
from cognitivefs.processor import SyncProcessor

def main():
    # Open test.img to get its UUID
    device_path = 'test.img'
    with BlockDevice(device_path, read_only=True) as dev:
        sb_data = dev.read_block(0)
        sb = Superblock.unpack(sb_data)
        uuid_hex = sb.uuid.hex()

    # Open KG database
    kg_path = device_path.replace('.img', '.kg.db')
    print(f'Knowledge graph path: {kg_path}')
    kg = KnowledgeGraph(kg_path)
    kg.open()

    # Create sync processor
    proc = SyncProcessor(kg)

    # Simulate a file being created/written
    test_content = b'''
CognitiveFS Development Notes - December 2024

Today I implemented the knowledge extraction pipeline. Key components:
- ContentExtractor: Extracts text from various file types
- EntityExtractor: Uses regex patterns to find named entities
- EmbeddingGenerator: Creates vector embeddings (optional dependency)
- BackgroundProcessor: Async worker that processes the queue

Team members: Alice Johnson (alice@cognitivefs.dev), Bob Smith
Meeting scheduled for 2024-12-24

Next steps:
1. Test integration with FUSE operations
2. Add FAISS support for similarity search
3. Implement spaCy-based NER for better entity extraction
'''

    # Process the file
    print('\nProcessing test file...')
    proc.process_file('/docs/notes.txt', 999, test_content)

    # Check results
    stats = kg.get_stats()
    print()
    print('Knowledge Graph Statistics:')
    print(f'  Files indexed: {stats["files_indexed"]}')
    print(f'  Entities: {stats["entities"]}')
    print(f'  Relationships: {stats["relationships"]}')
    print(f'  Embeddings: {stats["embeddings"]}')
    print()
    print('Entities by type:')
    for etype, count in stats['entities_by_type'].items():
        print(f'  {etype}: {count}')

    # Search for the file
    files = kg.search_files('development notes')
    print()
    print(f'Search "development notes": {len(files)} results')

    # Get entities from the file
    file_record = kg.get_file('/docs/notes.txt')
    if file_record:
        entities = kg.get_file_entities(file_record.id)
        print()
        print(f'Entities in /docs/notes.txt:')
        for entity, rel_type, confidence in entities[:10]:
            print(f'  - [{entity.entity_type.value}] {entity.name} (conf: {confidence:.2f})')

    # Test queue stats
    queue_stats = kg.get_queue_stats()
    print()
    print('Processing Queue:')
    for status, count in queue_stats.items():
        print(f'  {status}: {count}')

    kg.close()
    print()
    print('Integration test passed!')
    return 0

if __name__ == '__main__':
    sys.exit(main())
