#!/usr/bin/env python3
"""
CognitiveFS Main Entry Point

Command-line interface for mounting and managing CognitiveFS.
"""

import sys
import os


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='CognitiveFS - AI-Native File System',
        epilog='For more information, see README.md'
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Mount command
    mount_parser = subparsers.add_parser('mount', help='Mount CognitiveFS')
    mount_parser.add_argument('device', help='Device path')
    mount_parser.add_argument('mountpoint', help='Mount point directory')
    mount_parser.add_argument('--debug', action='store_true', help='Enable debug output')

    # Format command
    format_parser = subparsers.add_parser('format', help='Format device')
    format_parser.add_argument('device', help='Device path')
    format_parser.add_argument('--force', action='store_true', help='Skip confirmation')

    # List devices
    list_parser = subparsers.add_parser('list', help='List available devices')

    # Status command
    status_parser = subparsers.add_parser('status', help='Show filesystem status')
    status_parser.add_argument('device', help='Device path')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == 'mount':
        from .fuse_ops import mount_cognitivefs
        try:
            mount_cognitivefs(args.device, args.mountpoint, debug=args.debug)
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            if args.debug:
                import traceback
                traceback.print_exc()
            return 1

    elif args.command == 'format':
        # Import format tool
        tools_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'tools')
        sys.path.insert(0, tools_dir)
        from format_device import format_device
        success = format_device(args.device, force=args.force)
        return 0 if success else 1

    elif args.command == 'list':
        from .blockdev import list_physical_drives
        print("Available devices:")
        print()
        for drive in list_physical_drives():
            if 'number' in drive:
                print(f"  {drive['path']}")
                print(f"    Model: {drive['model']}")
                print(f"    Size:  {drive['size']:,} bytes ({drive['size'] / 1e9:.2f} GB)")
            else:
                print(f"  {drive['path']}")
                print(f"    Size: {drive['size']:,} bytes ({drive['size'] / 1e9:.2f} GB)")
            print()
        return 0

    elif args.command == 'status':
        from .blockdev import BlockDevice
        from .diskformat import Superblock
        import uuid

        try:
            with BlockDevice(args.device, read_only=True) as dev:
                superblock_data = dev.read_block(0)
                sb = Superblock.unpack(superblock_data)

                if not sb.is_valid():
                    print("Error: Not a valid CognitiveFS filesystem")
                    return 1

                print("CognitiveFS Status")
                print("=" * 70)
                print(f"Device: {args.device}")
                print(f"UUID: {uuid.UUID(bytes=sb.uuid)}")
                print(f"Version: {sb.version}")
                print(f"Block size: {sb.block_size:,} bytes")
                print(f"Total blocks: {sb.total_blocks:,}")
                print(f"Free blocks: {sb.free_blocks:,} ({sb.free_blocks * sb.block_size / 1e9:.2f} GB)")
                print(f"Total inodes: {sb.total_inodes:,}")
                print(f"Free inodes: {sb.free_inodes:,}")
                print()
                print(f"Created: {sb.created_at}")
                print(f"Last mounted: {sb.mounted_at if sb.mounted_at else 'Never'}")
                print(f"Last check: {sb.last_check}")

                return 0

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
