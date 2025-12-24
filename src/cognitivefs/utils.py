"""
Utility Functions

Common utilities for CognitiveFS.
"""

import os
import sys
import hashlib
from typing import Optional, Tuple


def is_admin() -> bool:
    """Check if running with administrator/root privileges."""
    if sys.platform == 'win32':
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    else:
        return os.geteuid() == 0


def require_admin(error_message: str = "This operation requires administrator privileges"):
    """Require admin privileges or exit."""
    if not is_admin():
        print(f"Error: {error_message}", file=sys.stderr)
        if sys.platform == 'win32':
            print("Please run this program as Administrator.", file=sys.stderr)
        else:
            print("Please run this program with sudo.", file=sys.stderr)
        sys.exit(1)


def format_bytes(size: int) -> str:
    """
    Format byte size as human-readable string.

    Args:
        size: Size in bytes

    Returns:
        Formatted string (e.g., "1.5 GB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def calculate_sha256(data: bytes) -> bytes:
    """Calculate SHA256 hash."""
    return hashlib.sha256(data).digest()


def calculate_sha256_hex(data: bytes) -> str:
    """Calculate SHA256 hash as hex string."""
    return hashlib.sha256(data).hexdigest()


def align_up(value: int, alignment: int) -> int:
    """Round up to nearest multiple of alignment."""
    return ((value + alignment - 1) // alignment) * alignment


def align_down(value: int, alignment: int) -> int:
    """Round down to nearest multiple of alignment."""
    return (value // alignment) * alignment


def is_sector_aligned(value: int, sector_size: int = 512) -> bool:
    """Check if value is sector-aligned."""
    return value % sector_size == 0


def get_platform_device_path(device_identifier: str) -> str:
    """
    Convert device identifier to platform-specific path.

    Args:
        device_identifier: Drive number (Windows) or device name (Linux)

    Returns:
        Platform-specific device path
    """
    if sys.platform == 'win32':
        # If already a full path, return as-is
        if device_identifier.startswith(r'\\.\PhysicalDrive'):
            return device_identifier

        # Otherwise, assume it's a drive number
        try:
            drive_num = int(device_identifier)
            return f'\\\\.\\PhysicalDrive{drive_num}'
        except ValueError:
            raise ValueError(f"Invalid device identifier: {device_identifier}")
    else:
        # Linux
        if device_identifier.startswith('/dev/'):
            return device_identifier
        else:
            return f'/dev/{device_identifier}'


def parse_size_string(size_str: str) -> int:
    """
    Parse size string (e.g., "10MB", "1.5GB") to bytes.

    Args:
        size_str: Size string

    Returns:
        Size in bytes
    """
    size_str = size_str.upper().strip()

    multipliers = {
        'B': 1,
        'KB': 1024,
        'MB': 1024 ** 2,
        'GB': 1024 ** 3,
        'TB': 1024 ** 4,
    }

    for suffix, multiplier in multipliers.items():
        if size_str.endswith(suffix):
            try:
                value = float(size_str[:-len(suffix)])
                return int(value * multiplier)
            except ValueError:
                break

    # Try to parse as plain number
    try:
        return int(size_str)
    except ValueError:
        raise ValueError(f"Invalid size string: {size_str}")


class ProgressBar:
    """Simple progress bar for terminal."""

    def __init__(self, total: int, prefix: str = '', width: int = 50):
        """
        Initialize progress bar.

        Args:
            total: Total number of items
            prefix: Prefix string
            width: Bar width in characters
        """
        self.total = total
        self.prefix = prefix
        self.width = width
        self.current = 0

    def update(self, current: int):
        """Update progress."""
        self.current = current
        self.render()

    def increment(self):
        """Increment by 1."""
        self.current += 1
        self.render()

    def render(self):
        """Render progress bar."""
        if self.total == 0:
            percent = 100
        else:
            percent = (self.current / self.total) * 100

        filled = int(self.width * self.current // self.total) if self.total > 0 else 0
        bar = '=' * filled + '-' * (self.width - filled)

        print(f'\r{self.prefix}[{bar}] {percent:.1f}%', end='', file=sys.stderr)

        if self.current >= self.total:
            print(file=sys.stderr)  # Newline when complete

    def finish(self):
        """Mark as complete."""
        self.update(self.total)
