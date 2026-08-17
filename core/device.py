"""
MoTunes - Device Connection Manager
Handles iPhone detection, mounting, and disconnection via libimobiledevice + ifuse
"""

import subprocess
import os
import tempfile
import threading
from dataclasses import dataclass
from typing import Optional, Callable


# ── iPhone model name lookup ──────────────────────────────────────────────────
# Maps ProductType identifiers to marketing names
IPHONE_MODELS = {
    # iPhone 16 series
    "iPhone17,1": "iPhone 16 Pro Max",
    "iPhone17,2": "iPhone 16 Pro",
    "iPhone17,3": "iPhone 16",
    "iPhone17,4": "iPhone 16 Plus",
    # iPhone 15 series
    "iPhone16,1": "iPhone 15",
    "iPhone16,2": "iPhone 15 Plus",
    "iPhone16,3": "iPhone 15 Pro",
    "iPhone16,4": "iPhone 15 Pro Max",
    # iPhone 14 series
    "iPhone15,2": "iPhone 14 Pro",
    "iPhone15,3": "iPhone 14 Pro Max",
    "iPhone14,7": "iPhone 14",
    "iPhone14,8": "iPhone 14 Plus",
    # iPhone 13 series
    "iPhone14,4": "iPhone 13 mini",
    "iPhone14,5": "iPhone 13",
    "iPhone14,2": "iPhone 13 Pro",
    "iPhone14,3": "iPhone 13 Pro Max",
    # iPhone 12 series
    "iPhone13,1": "iPhone 12 mini",
    "iPhone13,2": "iPhone 12",
    "iPhone13,3": "iPhone 12 Pro",
    "iPhone13,4": "iPhone 12 Pro Max",
    # iPhone 11 series
    "iPhone12,1": "iPhone 11",
    "iPhone12,3": "iPhone 11 Pro",
    "iPhone12,5": "iPhone 11 Pro Max",
    # iPhone XS/XR
    "iPhone11,2": "iPhone XS",
    "iPhone11,4": "iPhone XS Max",
    "iPhone11,6": "iPhone XS Max",
    "iPhone11,8": "iPhone XR",
    # iPhone X
    "iPhone10,3": "iPhone X",
    "iPhone10,6": "iPhone X",
    # iPhone 8
    "iPhone10,1": "iPhone 8",
    "iPhone10,2": "iPhone 8 Plus",
    "iPhone10,4": "iPhone 8",
    "iPhone10,5": "iPhone 8 Plus",
    # iPhone 7
    "iPhone9,1":  "iPhone 7",
    "iPhone9,2":  "iPhone 7 Plus",
    "iPhone9,3":  "iPhone 7",
    "iPhone9,4":  "iPhone 7 Plus",
    # iPhone SE
    "iPhone14,6": "iPhone SE (3rd gen)",
    "iPhone12,8": "iPhone SE (2nd gen)",
    "iPhone8,4":  "iPhone SE (1st gen)",
}

def model_name(product_type: str) -> str:
    """Return marketing name for a ProductType string, or the raw string if unknown."""
    return IPHONE_MODELS.get(product_type, product_type)


# ── Storage key fallback chain ────────────────────────────────────────────────
# iOS 18+ renamed/restructured capacity keys. We try multiple in order.
CAPACITY_KEYS = [
    "TotalDiskCapacity",          # iOS 17 and earlier
    "TotalDataCapacity",          # iOS 18+
    "com.apple.disk_usage.factory.total_bytes",  # some builds
]
AVAILABLE_KEYS = [
    "AmountDataAvailable",        # iOS 17 and earlier
    "TotalDataAvailable",         # iOS 18+
    "com.apple.disk_usage.factory.free_bytes",
]


@dataclass
class DeviceInfo:
    udid: str = ""
    name: str = "iPhone"
    product_type: str = ""
    ios_version: str = ""
    serial: str = ""
    capacity_bytes: int = 0
    used_bytes: int = 0
    mount_point: str = ""
    connected: bool = False

    @property
    def model_name(self) -> str:
        return model_name(self.product_type)

    @property
    def capacity_gb(self) -> float:
        return round(self.capacity_bytes / (1024 ** 3), 1)

    @property
    def used_gb(self) -> float:
        return round(self.used_bytes / (1024 ** 3), 1)

    @property
    def free_gb(self) -> float:
        return round(self.capacity_gb - self.used_gb, 1)

    @property
    def used_percent(self) -> float:
        if self.capacity_bytes == 0:
            return 0.0
        return round((self.used_bytes / self.capacity_bytes) * 100, 1)


class DeviceManager:
    def __init__(self):
        self._device: Optional[DeviceInfo] = None
        self._mount_dir: Optional[str] = None
        self._on_connected: Optional[Callable] = None
        self._on_disconnected: Optional[Callable] = None
        self._polling = False
        self._poll_thread: Optional[threading.Thread] = None

    def set_callbacks(self, on_connected: Callable, on_disconnected: Callable):
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected

    def start_polling(self, interval: float = 3.0):
        self._polling = True
        self._poll_interval = interval
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True
        )
        self._poll_thread.start()

    def stop_polling(self):
        self._polling = False

    def _poll_loop(self):
        import time
        was_connected = False
        while self._polling:
            try:
                udid = self._get_udid()
                is_connected = udid is not None
                if is_connected and not was_connected:
                    device = self._fetch_device_info(udid)
                    if device:
                        self._device = device
                        if self._on_connected:
                            self._on_connected(device)
                elif not is_connected and was_connected:
                    self._unmount()
                    self._device = None
                    if self._on_disconnected:
                        self._on_disconnected()
                was_connected = is_connected
            except Exception as e:
                print(f"[DeviceManager] Poll error: {e}")
            time.sleep(self._poll_interval)

    def _get_udid(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["idevice_id", "-l"],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().splitlines()
            return lines[0].strip() if lines else None
        except Exception:
            return None

    def _fetch_device_info(self, udid: str) -> Optional[DeviceInfo]:
        try:
            base_keys = ["DeviceName", "ProductType", "ProductVersion", "SerialNumber"]
            info = {}
            for key in base_keys:
                result = subprocess.run(
                    ["ideviceinfo", "-u", udid, "-k", key],
                    capture_output=True, text=True, timeout=5
                )
                info[key] = result.stdout.strip()

            # Storage is not available from ideviceinfo on iOS 26+.
            # We read it from the mount point after mounting instead.
            return DeviceInfo(
                udid=udid,
                name=info.get("DeviceName", "iPhone"),
                product_type=info.get("ProductType", ""),
                ios_version=info.get("ProductVersion", ""),
                serial=info.get("SerialNumber", ""),
                capacity_bytes=0,
                used_bytes=0,
                connected=True,
            )
        except Exception as e:
            print(f"[DeviceManager] Error fetching device info: {e}")
            return None

    def _fetch_storage_key(self, udid: str, keys: list) -> int:
        """Try each key in order, return first non-zero int result."""
        for key in keys:
            try:
                result = subprocess.run(
                    ["ideviceinfo", "-u", udid, "-k", key],
                    capture_output=True, text=True, timeout=5
                )
                val = result.stdout.strip()
                if val and val.isdigit():
                    n = int(val)
                    if n > 0:
                        return n
            except Exception:
                pass
        return 0

    def _fetch_disk_usage(self, udid: str) -> tuple:
        """
        Fallback: run ideviceinfo with -d com.apple.disk_usage domain
        and parse TotalDiskCapacity / AmountDataAvailable from output.
        """
        try:
            result = subprocess.run(
                ["ideviceinfo", "-u", udid, "-d", "com.apple.disk_usage"],
                capture_output=True, text=True, timeout=10
            )
            capacity = 0
            available = 0
            for line in result.stdout.splitlines():
                line = line.strip()
                if "TotalDiskCapacity" in line or "TotalDataCapacity" in line:
                    parts = line.split(":")
                    if len(parts) == 2:
                        try:
                            capacity = int(parts[1].strip())
                        except ValueError:
                            pass
                elif "AmountDataAvailable" in line or "TotalDataAvailable" in line:
                    parts = line.split(":")
                    if len(parts) == 2:
                        try:
                            available = int(parts[1].strip())
                        except ValueError:
                            pass
            return capacity, available
        except Exception as e:
            print(f"[DeviceManager] disk_usage fallback error: {e}")
            return 0, 0

    def mount_media(self) -> Optional[str]:
        """Mount iPhone media (Music, DCIM) via ifuse."""
        try:
            mount_dir = tempfile.mkdtemp(prefix="motunes_media_")
            result = subprocess.run(
                ["ifuse", mount_dir],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                return mount_dir
            else:
                print(f"[DeviceManager] Media mount error: {result.stderr}")
                os.rmdir(mount_dir)
                return None
        except Exception as e:
            print(f"[DeviceManager] Media mount error: {e}")
            return None

    def storage_from_mount(self, mount_path: str) -> tuple:
        """
        Read storage stats directly from the ifuse mount.
        Returns (capacity_bytes, used_bytes).
        Works on all iOS versions including iOS 26.
        """
        try:
            import shutil
            usage = shutil.disk_usage(mount_path)
            return usage.total, usage.used
        except Exception as e:
            print(f"[DeviceManager] storage_from_mount error: {e}")
            return 0, 0

    def _unmount(self):
        if self._mount_dir and os.path.exists(self._mount_dir):
            try:
                subprocess.run(["fusermount", "-u", self._mount_dir],
                               capture_output=True, timeout=5)
                os.rmdir(self._mount_dir)
            except Exception:
                pass
            self._mount_dir = None

    def unmount_path(self, path: str):
        try:
            subprocess.run(["fusermount", "-u", path],
                           capture_output=True, timeout=5)
            os.rmdir(path)
        except Exception:
            pass

    def disconnect(self):
        self._unmount()
        self._device = None

    @property
    def device(self) -> Optional[DeviceInfo]:
        return self._device
