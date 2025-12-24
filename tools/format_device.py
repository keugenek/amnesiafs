#!/usr/bin/env python3
"""
Format Device Tool

Initializes a raw block device with CognitiveFS format.

WARNING: This will erase all data on the target device!
"""

import sys
import os
import time
import uuid

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cognitivefs.blockdev import BlockDevice, BlockDeviceError, list_physical_drives
from cognitivefs.diskformat import (
    Superblock, Inode, InodeType, AllocationBitmap,
    calculate_layout, BLOCK_SIZE
)


def get_device_size_wmi(device_path: str) -> int:
    """Get device size via WMI (works without opening device)."""
    import sys
    if sys.platform != 'win32':
        return 0
    try:
        import wmi
        import re
        match = re.search(r'PhysicalDrive(\d+)', device_path)
        if match:
            drive_num = int(match.group(1))
            c = wmi.WMI()
            for disk in c.Win32_DiskDrive():
                if disk.Index == drive_num:
                    return int(disk.Size) if disk.Size else 0
    except Exception as e:
        print(f"WMI error: {e}")
    return 0


def create_image_file(path: str, size_bytes: int):
    """Create an empty image file."""
    print(f"Creating image file: {path} ({size_bytes / 1e9:.2f} GB)")
    with open(path, 'wb') as f:
        # Write in chunks to avoid memory issues
        chunk_size = 1024 * 1024 * 10  # 10MB chunks
        remaining = size_bytes
        while remaining > 0:
            write_size = min(chunk_size, remaining)
            f.write(b'\x00' * write_size)
            remaining -= write_size
    print("Image file created.")


def format_device(device_path: str, force: bool = False, image_size: int = 0):
    """
    Format a device with CognitiveFS.

    Args:
        device_path: Path to device or image file
        force: Skip confirmation prompt
        image_size: If > 0, create image file of this size
    """
    print("=" * 70)
    print("CognitiveFS Device Formatter")
    print("=" * 70)

    # Check if this is an image file (not a physical device)
    is_image = not device_path.startswith("\\\\.\\") and not device_path.startswith("/dev/")

    if is_image and image_size > 0:
        # Create new image file
        create_image_file(device_path, image_size)
        device_size = image_size
    elif is_image and os.path.exists(device_path):
        # Existing image file
        device_size = os.path.getsize(device_path)
    else:
        # Physical device - get size via WMI
        device_size = get_device_size_wmi(device_path)

        # Open device to verify access
        try:
            device = BlockDevice(device_path, read_only=True)
            device.open()
            if device.size > 0:
                device_size = device.size
            device.close()
        except BlockDeviceError as e:
            print(f"Error: {e}")
            return False

    if device_size == 0:
        print(f"Error: Could not determine size of {device_path}")
        return False

    # Calculate layout
    layout = calculate_layout(device_size)

    # Display information
    print(f"\nDevice: {device_path}")
    print(f"Size: {device_size:,} bytes ({device_size / 1e9:.2f} GB)")
    print(f"Total blocks: {layout['total_blocks']:,} ({BLOCK_SIZE} bytes each)")
    print()
    print("Layout:")
    print(f"  Superblock:        {layout['superblock'][1]:>8} blocks  ({layout['superblock'][1] * BLOCK_SIZE / 1e6:>8.2f} MB)")
    print(f"  Allocation Bitmap: {layout['bitmap'][1]:>8} blocks  ({layout['bitmap'][1] * BLOCK_SIZE / 1e6:>8.2f} MB)")
    print(f"  Inode Table:       {layout['inode_table'][1]:>8} blocks  ({layout['inode_table'][1] * BLOCK_SIZE / 1e6:>8.2f} MB)")
    print(f"  Knowledge Graph:   {layout['knowledge_graph'][1]:>8} blocks  ({layout['knowledge_graph'][1] * BLOCK_SIZE / 1e9:>8.2f} GB)")
    print(f"  Embedding Store:   {layout['embedding_store'][1]:>8} blocks  ({layout['embedding_store'][1] * BLOCK_SIZE / 1e9:>8.2f} GB)")
    print(f"  Version Store:     {layout['version_store'][1]:>8} blocks  ({layout['version_store'][1] * BLOCK_SIZE / 1e9:>8.2f} GB)")
    print(f"  Data Blocks:       {layout['data_blocks'][1]:>8} blocks  ({layout['data_blocks'][1] * BLOCK_SIZE / 1e9:>8.2f} GB)")
    print(f"  Journal:           {layout['journal'][1]:>8} blocks  ({layout['journal'][1] * BLOCK_SIZE / 1e6:>8.2f} MB)")
    print()

    # Confirm
    if not force:
        print("WARNING: This will ERASE ALL DATA on the device!")
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            return False

    print("\nFormatting device...")

    try:
        # Open device for writing
        device = BlockDevice(device_path, read_only=False)
        device.open()
        # Override size with pre-computed WMI value
        if device.size == 0:
            device.size = device_size

        # 1. Create and write superblock
        print("  [1/5] Writing superblock...")
        superblock = Superblock()
        superblock.total_blocks = layout['total_blocks']
        superblock.created_at = int(time.time())
        superblock.mounted_at = 0
        superblock.last_check = superblock.created_at
        superblock.uuid = uuid.uuid4().bytes

        # Set all layout pointers from calculated layout
        superblock.bitmap_start = layout['bitmap'][0]
        superblock.bitmap_blocks = layout['bitmap'][1]
        superblock.inode_table_start = layout['inode_table'][0]
        superblock.inode_table_blocks = layout['inode_table'][1]
        superblock.knowledge_graph_start = layout['knowledge_graph'][0]
        superblock.knowledge_graph_blocks = layout['knowledge_graph'][1]
        superblock.embedding_store_start = layout['embedding_store'][0]
        superblock.embedding_store_blocks = layout['embedding_store'][1]
        superblock.version_store_start = layout['version_store'][0]
        superblock.version_store_blocks = layout['version_store'][1]
        superblock.data_blocks_start = layout['data_blocks'][0]
        superblock.journal_start = layout['journal'][0]
        superblock.journal_blocks = layout['journal'][1]

        # Calculate free blocks (total - metadata)
        metadata_blocks = (
            layout['superblock'][1] +
            layout['bitmap'][1] +
            layout['inode_table'][1] +
            layout['knowledge_graph'][1] +
            layout['embedding_store'][1] +
            layout['version_store'][1] +
            layout['journal'][1]
        )
        superblock.free_blocks = layout['total_blocks'] - metadata_blocks

        # Max inodes
        superblock.total_inodes = layout['inode_table'][1] * (BLOCK_SIZE // Inode.INODE_SIZE)
        superblock.free_inodes = superblock.total_inodes - 1  # -1 for root

        device.write_block(0, superblock.pack())

        # 2. Initialize allocation bitmap
        print("  [2/5] Initializing allocation bitmap...")
        bitmap = AllocationBitmap(layout['total_blocks'])

        # Mark metadata regions as allocated
        for block in range(0, layout['data_blocks'][0]):
            bitmap.allocate(block)

        # Mark journal as allocated
        for block in range(layout['journal'][0], layout['journal'][0] + layout['journal'][1]):
            bitmap.allocate(block)

        # Write bitmap
        bitmap_bytes = bitmap.to_bytes()
        offset = layout['bitmap'][0] * BLOCK_SIZE
        device.write_bytes(offset, bitmap_bytes)

        # 3. Initialize inode table
        print("  [3/5] Creating root inode...")

        # Create root directory inode
        root_inode = Inode()
        root_inode.inode_num = 1
        root_inode.inode_type = InodeType.DIRECTORY
        root_inode.mode = 0o755
        root_inode.uid = 0
        root_inode.gid = 0
        root_inode.created_at = int(time.time())
        root_inode.modified_at = root_inode.created_at
        root_inode.accessed_at = root_inode.created_at
        root_inode.size = BLOCK_SIZE
        root_inode.nlinks = 2  # . and ..

        # Allocate a data block for root directory
        root_data_block = layout['data_blocks'][0]
        bitmap.allocate(root_data_block)
        root_inode.direct_blocks[0] = root_data_block
        root_inode.blocks_allocated = 1

        # Write root inode
        inode_block = layout['inode_table'][0]
        inode_data = bytearray(BLOCK_SIZE)
        inode_data[Inode.INODE_SIZE:2 * Inode.INODE_SIZE] = root_inode.pack()
        device.write_block(inode_block, bytes(inode_data))

        # Initialize root directory data (empty)
        device.write_block(root_data_block, b'\x00' * BLOCK_SIZE)

        # 4. Initialize knowledge graph region (empty SQLite will be created later)
        print("  [4/5] Reserving knowledge graph region...")
        # Just ensure it's marked as allocated in bitmap (already done)

        # 5. Sync to disk
        print("  [5/5] Syncing to disk...")
        device.sync()

        device.close()

        print("\nFormat complete!")
        print(f"Filesystem UUID: {uuid.UUID(bytes=superblock.uuid)}")
        print(f"Total capacity: {superblock.free_blocks * BLOCK_SIZE / 1e9:.2f} GB")
        print(f"Available inodes: {superblock.free_inodes:,}")

        return True

    except Exception as e:
        print(f"\nError during format: {e}")
        import traceback
        traceback.print_exc()
        return False


def list_devices():
    """List available devices."""
    print("Available devices:")
    print()

    drives = list_physical_drives()

    if not drives:
        print("  No devices found.")
        return

    for drive in drives:
        if 'number' in drive:
            # Windows
            print(f"  {drive['path']}")
            print(f"    Model: {drive['model']}")
            print(f"    Size:  {drive['size']:,} bytes ({drive['size'] / 1e9:.2f} GB)")
            print(f"    Interface: {drive['interface']}")
        else:
            # Linux
            print(f"  {drive['path']}")
            print(f"    Size: {drive['size']:,} bytes ({drive['size'] / 1e9:.2f} GB)")
        print()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Format a block device with CognitiveFS',
        epilog='WARNING: This will erase all data on the device!'
    )

    parser.add_argument(
        'device',
        nargs='?',
        help=r'Device path (e.g., \\.\PhysicalDrive1 or /dev/sdb)'
    )

    parser.add_argument(
        '--list',
        action='store_true',
        help='List available devices'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompt'
    )

    parser.add_argument(
        '--size',
        type=str,
        help='Size for image file (e.g., 1G, 500M, 1073741824). Creates new image if specified.'
    )

    args = parser.parse_args()

    if args.list:
        list_devices()
        return 0

    if not args.device:
        parser.print_help()
        print()
        list_devices()
        return 1

    # Parse size argument
    image_size = 0
    if args.size:
        size_str = args.size.upper().strip()
        if size_str.endswith('G'):
            image_size = int(float(size_str[:-1]) * 1024 * 1024 * 1024)
        elif size_str.endswith('M'):
            image_size = int(float(size_str[:-1]) * 1024 * 1024)
        elif size_str.endswith('K'):
            image_size = int(float(size_str[:-1]) * 1024)
        else:
            image_size = int(size_str)

    success = format_device(args.device, force=args.force, image_size=image_size)
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
