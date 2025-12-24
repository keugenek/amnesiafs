#!/usr/bin/env python3
"""Test device access."""
import sys
import os
import ctypes

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

print("=" * 50)
print("CognitiveFS Device Test")
print("=" * 50)

# Check admin
is_admin = ctypes.windll.shell32.IsUserAnAdmin() if sys.platform == 'win32' else os.geteuid() == 0
print(f"Running as Admin: {bool(is_admin)}")

if not is_admin:
    print("ERROR: Must run as Administrator!")
    sys.exit(1)

device_path = r"\\.\PhysicalDrive1"
print(f"\nTesting device: {device_path}")

# Test WMI size
from cognitivefs.fuse_ops import get_device_size_wmi
wmi_size = get_device_size_wmi(device_path)
print(f"WMI reported size: {wmi_size:,} bytes ({wmi_size / 1e9:.2f} GB)")

# Test BlockDevice
from cognitivefs.blockdev import BlockDevice
print("\nOpening device...")
dev = BlockDevice(device_path, read_only=True)
dev.open()
print(f"Device opened. Size: {dev.size:,} bytes")

# Read block 0
print("\nReading block 0 (superblock)...")
data = dev.read_block(0)
print(f"Block 0 length: {len(data)} bytes")
print(f"First 32 bytes: {data[:32]}")
print(f"Magic bytes: {data[:8]}")

# Check magic
if data[:8] == b'COGFS001':
    print("\n✓ Valid CognitiveFS magic!")
else:
    print(f"\n✗ Invalid magic: {data[:8]}")
    print("Expected: b'COGFS001'")

dev.close()
print("\nDevice closed.")
