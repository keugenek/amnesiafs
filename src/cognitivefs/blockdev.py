"""
Block Device Access Layer

Provides low-level read/write access to raw block devices.
Works on both Windows (via win32file) and Linux (via direct file I/O).
"""

import os
import sys
import struct
from typing import Optional
from pathlib import Path

# Platform-specific imports
if sys.platform == 'win32':
    import win32file
    import win32con
    import pywintypes


class BlockDeviceError(Exception):
    """Exception raised for block device errors."""
    pass


class BlockDevice:
    """
    Low-level block device access.

    Supports:
    - Windows: \\.\PhysicalDriveN via win32file
    - Linux: /dev/sdX via standard file I/O
    - Cross-platform: Regular files for testing
    """

    SECTOR_SIZE = 512  # Standard disk sector size
    BLOCK_SIZE = 4096  # Our filesystem block size (8 sectors)

    def __init__(self, device_path: str, read_only: bool = False):
        """
        Initialize block device.

        Args:
            device_path: Path to device
                Windows: r"\\.\PhysicalDrive1"
                Linux: "/dev/sdb"
                Testing: "disk.img"
            read_only: Open in read-only mode
        """
        self.device_path = device_path
        self.read_only = read_only
        self.handle = None
        self.size = 0
        self._is_physical_device = self._detect_device_type()

    def _detect_device_type(self) -> bool:
        """Detect if this is a physical device or regular file."""
        if sys.platform == 'win32':
            return self.device_path.startswith(r"\\.\PhysicalDrive")
        else:
            return self.device_path.startswith('/dev/')

    def open(self):
        """Open the block device."""
        if self.handle is not None:
            raise BlockDeviceError("Device already open")

        if sys.platform == 'win32':
            self._open_windows()
        else:
            self._open_posix()

        self._get_device_size()

    def _open_windows(self):
        """Open device on Windows using win32file."""
        try:
            # Build access flags
            if self.read_only:
                access = win32con.GENERIC_READ
            else:
                access = win32con.GENERIC_READ | win32con.GENERIC_WRITE

            # Share mode - allow other readers
            share_mode = win32file.FILE_SHARE_READ

            # Creation disposition
            if self._is_physical_device:
                creation = win32con.OPEN_EXISTING
            else:
                creation = win32con.OPEN_ALWAYS

            # Flags
            flags = win32con.FILE_FLAG_NO_BUFFERING if self._is_physical_device else 0

            self.handle = win32file.CreateFile(
                self.device_path,
                access,
                share_mode,
                None,
                creation,
                flags,
                None
            )

        except pywintypes.error as e:
            if e.winerror == 5:  # Access denied
                raise BlockDeviceError(
                    f"Access denied to {self.device_path}. "
                    "Administrator privileges required for physical drives."
                ) from e
            raise BlockDeviceError(f"Failed to open device: {e}") from e

    def _open_posix(self):
        """Open device on POSIX systems."""
        flags = os.O_RDONLY if self.read_only else os.O_RDWR

        # Use O_DIRECT for physical devices (bypasses cache)
        if self._is_physical_device and hasattr(os, 'O_DIRECT'):
            flags |= os.O_DIRECT

        try:
            self.handle = os.open(self.device_path, flags)
        except PermissionError as e:
            raise BlockDeviceError(
                f"Permission denied to {self.device_path}. "
                "Root/sudo required for block devices."
            ) from e
        except FileNotFoundError as e:
            # Create regular file if it doesn't exist
            if not self._is_physical_device:
                self.handle = os.open(self.device_path, flags | os.O_CREAT, 0o666)
            else:
                raise BlockDeviceError(f"Device not found: {self.device_path}") from e

    def _get_device_size(self):
        """Determine device size."""
        if sys.platform == 'win32':
            if self._is_physical_device:
                # Use WMI first - most reliable on Windows
                self.size = self._get_size_via_wmi()
                if self.size > 0:
                    return

                # Fallback to IOCTL
                try:
                    IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x000700A0
                    geometry = win32file.DeviceIoControl(
                        self.handle,
                        IOCTL_DISK_GET_DRIVE_GEOMETRY_EX,
                        None,
                        1024
                    )
                    self.size = struct.unpack('<Q', geometry[24:32])[0]
                except Exception:
                    try:
                        IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
                        length_info = win32file.DeviceIoControl(
                            self.handle,
                            IOCTL_DISK_GET_LENGTH_INFO,
                            None,
                            8
                        )
                        self.size = struct.unpack('<Q', length_info)[0]
                    except Exception:
                        self.size = 0
            else:
                # Regular file
                try:
                    self.size = win32file.GetFileSize(self.handle)
                except Exception:
                    self.size = 0
        else:
            # POSIX
            if self._is_physical_device:
                # Try to get block device size
                try:
                    import fcntl
                    import array
                    # BLKGETSIZE64 ioctl
                    buf = array.array('L', [0])
                    fcntl.ioctl(self.handle, 0x80081272, buf)  # BLKGETSIZE64
                    self.size = buf[0]
                except Exception:
                    # Fallback to seeking
                    self.size = os.lseek(self.handle, 0, os.SEEK_END)
                    os.lseek(self.handle, 0, os.SEEK_SET)
            else:
                self.size = os.lseek(self.handle, 0, os.SEEK_END)
                os.lseek(self.handle, 0, os.SEEK_SET)

    def _get_size_via_wmi(self) -> int:
        """Get device size via WMI (Windows fallback)."""
        try:
            import wmi
            import re
            # Extract drive number from path like \\.\PhysicalDrive1 or \.\PhysicalDrive1
            match = re.search(r'PhysicalDrive(\d+)', self.device_path)
            if match:
                drive_num = int(match.group(1))
                c = wmi.WMI()
                for disk in c.Win32_DiskDrive():
                    if disk.Index == drive_num:
                        return int(disk.Size) if disk.Size else 0
        except Exception:
            pass
        return 0

    def close(self):
        """Close the device."""
        if self.handle is None:
            return

        if sys.platform == 'win32':
            win32file.CloseHandle(self.handle)
        else:
            os.close(self.handle)

        self.handle = None

    def read_block(self, block_num: int) -> bytes:
        """
        Read a single block.

        Args:
            block_num: Block number to read (0-indexed)

        Returns:
            Block data (BLOCK_SIZE bytes)
        """
        if self.handle is None:
            raise BlockDeviceError("Device not open")

        offset = block_num * self.BLOCK_SIZE
        if offset + self.BLOCK_SIZE > self.size:
            raise BlockDeviceError(f"Block {block_num} out of range")

        return self.read_bytes(offset, self.BLOCK_SIZE)

    def write_block(self, block_num: int, data: bytes):
        """
        Write a single block.

        Args:
            block_num: Block number to write (0-indexed)
            data: Block data (must be BLOCK_SIZE bytes)
        """
        if self.read_only:
            raise BlockDeviceError("Device opened in read-only mode")

        if len(data) != self.BLOCK_SIZE:
            raise BlockDeviceError(f"Data must be exactly {self.BLOCK_SIZE} bytes")

        offset = block_num * self.BLOCK_SIZE
        if offset + self.BLOCK_SIZE > self.size:
            raise BlockDeviceError(f"Block {block_num} out of range")

        self.write_bytes(offset, data)

    def read_bytes(self, offset: int, size: int) -> bytes:
        """
        Read arbitrary bytes from device.

        Args:
            offset: Byte offset
            size: Number of bytes to read

        Returns:
            Data read
        """
        if self.handle is None:
            raise BlockDeviceError("Device not open")

        if sys.platform == 'win32':
            # For physical devices with O_DIRECT, ensure sector-aligned reads
            if self._is_physical_device:
                # Calculate aligned offset and size
                align = self.SECTOR_SIZE
                aligned_offset = (offset // align) * align
                aligned_size = ((size + (offset - aligned_offset) + align - 1) // align) * align

                # Read aligned
                win32file.SetFilePointer(self.handle, aligned_offset, win32file.FILE_BEGIN)
                _, data = win32file.ReadFile(self.handle, aligned_size)

                # Extract requested portion
                start = offset - aligned_offset
                return data[start:start + size]
            else:
                win32file.SetFilePointer(self.handle, offset, win32file.FILE_BEGIN)
                _, data = win32file.ReadFile(self.handle, size)
                return data
        else:
            os.lseek(self.handle, offset, os.SEEK_SET)
            return os.read(self.handle, size)

    def write_bytes(self, offset: int, data: bytes):
        """
        Write arbitrary bytes to device.

        Args:
            offset: Byte offset
            data: Data to write
        """
        if self.handle is None:
            raise BlockDeviceError("Device not open")

        if self.read_only:
            raise BlockDeviceError("Device opened in read-only mode")

        if sys.platform == 'win32':
            # For physical devices, ensure sector-aligned writes
            if self._is_physical_device:
                align = self.SECTOR_SIZE
                if offset % align != 0 or len(data) % align != 0:
                    raise BlockDeviceError(
                        f"Physical device requires sector-aligned writes "
                        f"(offset={offset}, size={len(data)}, sector={align})"
                    )

            win32file.SetFilePointer(self.handle, offset, win32file.FILE_BEGIN)
            win32file.WriteFile(self.handle, data)
        else:
            os.lseek(self.handle, offset, os.SEEK_SET)
            os.write(self.handle, data)

    def sync(self):
        """Flush all writes to disk."""
        if self.handle is None:
            raise BlockDeviceError("Device not open")

        if sys.platform == 'win32':
            win32file.FlushFileBuffers(self.handle)
        else:
            os.fsync(self.handle)

    def get_total_blocks(self) -> int:
        """Get total number of blocks on device."""
        return self.size // self.BLOCK_SIZE

    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def __repr__(self):
        """String representation."""
        return (
            f"BlockDevice(path='{self.device_path}', "
            f"size={self.size:,} bytes, "
            f"blocks={self.get_total_blocks():,}, "
            f"read_only={self.read_only})"
        )


def list_physical_drives():
    """
    List all physical drives on the system.

    Returns:
        List of (drive_number, model, size) tuples
    """
    drives = []

    if sys.platform == 'win32':
        import wmi
        try:
            c = wmi.WMI()
            for disk in c.Win32_DiskDrive():
                drives.append({
                    'number': disk.Index,
                    'path': f"\\\\.\\PhysicalDrive{disk.Index}",
                    'model': disk.Model,
                    'size': int(disk.Size) if disk.Size else 0,
                    'interface': disk.InterfaceType
                })
        except Exception:
            # Fallback without WMI
            for i in range(10):
                try:
                    with BlockDevice(f"\\\\.\\PhysicalDrive{i}", read_only=True) as dev:
                        drives.append({
                            'number': i,
                            'path': f"\\\\.\\PhysicalDrive{i}",
                            'model': 'Unknown',
                            'size': dev.size,
                            'interface': 'Unknown'
                        })
                except BlockDeviceError:
                    continue
    else:
        # Linux - parse /proc/partitions or /sys/block
        import glob
        for dev in glob.glob('/dev/sd?') + glob.glob('/dev/nvme?n?'):
            try:
                with BlockDevice(dev, read_only=True) as bd:
                    drives.append({
                        'path': dev,
                        'size': bd.size,
                        'model': 'Unknown'
                    })
            except BlockDeviceError:
                continue

    return drives
