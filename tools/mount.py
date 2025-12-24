#!/usr/bin/env python3
"""
Mount CognitiveFS filesystem.

Usage:
    mount.py <device> <mountpoint> [--debug]
    mount.py --list
"""

import sys
import os
import argparse

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cognitivefs.fuse_ops import mount_cognitivefs
from cognitivefs.blockdev import list_physical_drives


def main():
    parser = argparse.ArgumentParser(
        description='Mount CognitiveFS filesystem',
        epilog='Example: mount.py \\\\.\\PhysicalDrive1 C:\\mnt\\cognitive'
    )

    parser.add_argument(
        'device',
        nargs='?',
        help='Device path (e.g., \\\\.\\PhysicalDrive1 or /dev/sdb)'
    )

    parser.add_argument(
        'mountpoint',
        nargs='?',
        help='Mount point directory'
    )

    parser.add_argument(
        '--list',
        action='store_true',
        help='List available devices'
    )

    parser.add_argument(
        '--debug', '-d',
        action='store_true',
        help='Enable debug output'
    )

    parser.add_argument(
        '--background', '-b',
        action='store_true',
        help='Run in background (default: foreground)'
    )

    args = parser.parse_args()

    if args.list:
        print("Available devices:\n")
        for drive in list_physical_drives():
            print(f"  {drive['path']}")
            print(f"    Model: {drive['model']}")
            print(f"    Size:  {drive['size']:,} bytes ({drive['size'] / 1e9:.2f} GB)")
            print(f"    Interface: {drive['interface']}")
            print()
        return 0

    if not args.device or not args.mountpoint:
        parser.print_help()
        return 1

    # Validate mount point
    if sys.platform == 'win32':
        # On Windows, mount point can be a drive letter or directory
        if len(args.mountpoint) == 2 and args.mountpoint[1] == ':':
            # Drive letter like "Z:"
            pass
        else:
            os.makedirs(args.mountpoint, exist_ok=True)
    else:
        os.makedirs(args.mountpoint, exist_ok=True)

    # Check for admin privileges on Windows
    if sys.platform == 'win32':
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("WARNING: Not running as Administrator!")
            print("Physical drive access requires admin privileges.")
            print("Please run this command in an elevated terminal.\n")

    print(f"Mounting CognitiveFS...")
    print(f"  Device: {args.device}")
    print(f"  Mount point: {args.mountpoint}")
    print(f"  Debug: {args.debug}")
    print()

    try:
        mount_cognitivefs(
            args.device,
            args.mountpoint,
            debug=args.debug,
            foreground=not args.background
        )
    except KeyboardInterrupt:
        print("\nUnmounting...")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        if "Access denied" in str(e) or "Access is denied" in str(e):
            print("\nHint: Run this command as Administrator:")
            print(f"  python tools/mount.py {args.device} {args.mountpoint}")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
