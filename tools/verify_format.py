#!/usr/bin/env python3
"""Verify CognitiveFS format on a device."""

import sys
import os
import uuid

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cognitivefs.blockdev import BlockDevice, BlockDeviceError
from cognitivefs.diskformat import Superblock, MAGIC

def get_device_size_wmi(device_path: str) -> int:
    """Get device size via WMI."""
    import re
    try:
        import wmi
        match = re.search(r'PhysicalDrive(\d+)', device_path)
        if match:
            drive_num = int(match.group(1))
            c = wmi.WMI()
            for disk in c.Win32_DiskDrive():
                if disk.Index == drive_num:
                    return int(disk.Size) if disk.Size else 0
    except Exception:
        pass
    return 0


def verify_device(device_path: str):
    """Verify a device has valid CognitiveFS format."""
    print(f"Verifying CognitiveFS on {device_path}...")

    try:
        # Get size via WMI first
        device_size = get_device_size_wmi(device_path)

        device = BlockDevice(device_path, read_only=True)
        device.open()

        # Override size if needed
        if device.size == 0 and device_size > 0:
            device.size = device_size

        # Read superblock
        sb_data = device.read_block(0)

        # Check magic
        magic = sb_data[:8]
        if magic != MAGIC:
            print(f"ERROR: Invalid magic: {magic} (expected {MAGIC})")
            return False

        # Parse superblock
        sb = Superblock.unpack(sb_data)

        print(f"\nCognitiveFS Superblock:")
        print(f"  Magic: {sb.magic}")
        print(f"  Version: {sb.version}")
        print(f"  Block size: {sb.block_size}")
        print(f"  Total blocks: {sb.total_blocks:,}")
        print(f"  UUID: {uuid.UUID(bytes=sb.uuid)}")
        print(f"  Free blocks: {sb.free_blocks:,}")
        print(f"  Total inodes: {sb.total_inodes:,}")
        print(f"  Free inodes: {sb.free_inodes:,}")
        print(f"\nFilesystem is valid!")

        device.close()
        return True

    except BlockDeviceError as e:
        print(f"Error: {e}")
        return False

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: verify_format.py <device>")
        sys.exit(1)

    success = verify_device(sys.argv[1])
    sys.exit(0 if success else 1)
