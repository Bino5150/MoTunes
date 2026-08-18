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

from core.capability import CapabilityDecision, RuntimeCapability, decide_policy, probe_capability


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
    def __init__(self, capability_provider: Optional[Callable[[], CapabilityDecision]] = None):
        self._device: Optional[DeviceInfo] = None
        self._mount_dir: Optional[str] = None
        # Defaults to the real probe; tests inject a synthetic provider so
        # behavior never depends on what happens to be installed on the
        # machine running the suite. Starts decided against an all-absent
        # RuntimeCapability (fails closed — "not yet probed" must never
        # read as "probably fine") until refresh_capability() actually runs.
        self._capability_provider = capability_provider or (lambda: decide_policy(probe_capability()))
        self._capability_lock = threading.Lock()
        self._capability: CapabilityDecision = decide_policy(RuntimeCapability())
        # Guards self._mount_dir. mount_media() can run on the Qt main
        # thread (via MainWindow's "Mount Device" button) at the same time
        # the poll thread's _poll_loop calls unmount_current() on a real
        # disconnect — without this, a lost update could leave a freshly
        # set mount_dir cleared, or a stale one still tracked as active.
        self._mount_lock = threading.Lock()
        self._on_connected: Optional[Callable] = None
        self._on_disconnected: Optional[Callable] = None
        # Guards _poll_thread so start_polling() can't spawn a second
        # concurrent worker, and so stop_polling() reads a consistent
        # thread reference. Never held across thread.join().
        self._poll_lock = threading.Lock()
        self._poll_thread: Optional[threading.Thread] = None
        self._poll_interval = 3.0
        # Set by stop_polling() to end the loop; cleared by start_polling()
        # for a fresh run. A real synchronization primitive rather than a
        # shared bool + time.sleep(): stop_polling() can wake a sleeping
        # poll iteration immediately instead of waiting out the rest of
        # the interval, and — critically — can confirm via thread.join()
        # that the worker has actually exited before returning, rather
        # than a caller having to assume that setting a flag "eventually"
        # means stopped. That gap (poll thread still alive and later
        # calling back into a bridge/QObject whose MainWindow has already
        # started tearing down) is what produced the segfault CI caught.
        self._stop_event = threading.Event()

    def set_callbacks(self, on_connected: Callable, on_disconnected: Callable):
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected

    @property
    def capability(self) -> CapabilityDecision:
        """The most recently computed capability decision. Never None —
        before the first refresh_capability() call this reads as the
        fail-closed 'nothing detected yet' state, not an assumption of
        safety."""
        with self._capability_lock:
            return self._capability

    def refresh_capability(self) -> CapabilityDecision:
        """
        Re-run the capability probe now and cache the result. Cheap
        fact-gathering (PATH lookups + one bounded `ifuse --version`
        call) — safe to call at startup for the UI's initial state, and
        again immediately before mount_media() actually shells out to
        ifuse, so a stale startup-time probe can never authorize a mount
        the current environment wouldn't. Never call this from the
        device poll loop — it must stay a cheap connect/disconnect
        check, not a dependency-diagnostics benchmark on every tick.
        """
        decision = self._capability_provider()
        with self._capability_lock:
            self._capability = decision
        return decision

    @property
    def is_polling(self) -> bool:
        """True if a poll worker is currently alive."""
        with self._poll_lock:
            thread = self._poll_thread
        return thread is not None and thread.is_alive()

    def start_polling(self, interval: float = 3.0):
        """
        Begin polling for device connect/disconnect in a background
        thread. Idempotent: a no-op if a poll worker is already running —
        never spawns a second concurrent poller.
        """
        with self._poll_lock:
            if self._poll_thread is not None and self._poll_thread.is_alive():
                return
            self._poll_interval = interval
            self._stop_event.clear()
            thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread = thread
        thread.start()

    def stop_polling(self, timeout: float = 10.0) -> bool:
        """
        Request the poll worker to stop and wait for it to actually
        terminate before returning. Returns True once confirmed stopped
        (or if no worker was running), False if it didn't stop within
        `timeout` — callers on a shutdown path should treat False as "do
        not assume it is safe to tear down anything the worker might
        still call back into."

        `timeout` defaults generously above the worst realistic single
        poll iteration (a handful of subprocess calls to idevice_id /
        ideviceinfo, each with its own 5s timeout) rather than being an
        arbitrary guess — the interruptible wait below means the common
        case returns almost immediately regardless.
        """
        self._stop_event.set()
        with self._poll_lock:
            thread = self._poll_thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            # A callback invoked from the poll thread itself calling back
            # into stop_polling() can't wait for its own thread to end —
            # Thread.join() would raise RuntimeError for exactly this.
            # Report "not confirmed" rather than let that propagate.
            return False
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def _poll_loop(self):
        was_connected = False
        while not self._stop_event.is_set():
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
            # Interruptible wait: stop_polling() setting the event wakes
            # this immediately instead of sleeping out the rest of the
            # interval, so a stop request is never left waiting behind an
            # in-progress sleep.
            self._stop_event.wait(timeout=self._poll_interval)

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
        """Mount iPhone media (Music, DCIM) via ifuse.

        Capability is re-probed right here, immediately before the ifuse
        subprocess call — not just trusted from whatever a startup-time
        probe found — so a hard-blocked or otherwise unmountable
        environment (exact ifuse 1.2.0, ifuse missing, no viable unmount
        tool) can never reach the actual ifuse invocation, regardless of
        who calls this method or when. This check lives in mount_media()
        itself rather than only in its UI caller specifically so that
        directly invoking this method can't bypass it.

        On success, records the mount as this manager's single tracked
        active mount (self._mount_dir) so unmount_current()/disconnect()
        actually have something to tear down. A failed mount never leaves
        self._mount_dir pointing at a directory that isn't really mounted.
        """
        decision = self.refresh_capability()
        if not decision.can_mount:
            print(f"[DeviceManager] Mount refused: {decision.reason}")
            return None

        mount_dir = None
        try:
            mount_dir = tempfile.mkdtemp(prefix="motunes_media_")
            result = subprocess.run(
                ["ifuse", mount_dir],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                with self._mount_lock:
                    self._mount_dir = mount_dir
                return mount_dir
            else:
                print(f"[DeviceManager] Media mount error: {result.stderr}")
                os.rmdir(mount_dir)
                return None
        except Exception as e:
            print(f"[DeviceManager] Media mount error: {e}")
            if mount_dir and os.path.isdir(mount_dir):
                try:
                    os.rmdir(mount_dir)
                except Exception:
                    pass
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

    def _do_unmount(self, path: str):
        """Best-effort unmount + rmdir. Never raises — a path that's
        already unmounted or already removed is not an error here.

        Tries fusermount3 first (the libfuse3 generation current ifuse
        depends on), falling back to fusermount (legacy libfuse2 installs,
        or distros that only ship the older name) — a system may
        genuinely have only one of the two, so this doesn't blindly
        assume either one's presence."""
        for binary in ("fusermount3", "fusermount"):
            try:
                subprocess.run([binary, "-u", path],
                               capture_output=True, timeout=5)
                break
            except FileNotFoundError:
                continue
            except Exception:
                break
        try:
            os.rmdir(path)
        except Exception:
            pass

    def unmount_current(self):
        """
        Idempotent: unmount whatever this manager currently has tracked as
        the active mount, if anything. Clears the tracked state up front
        (under lock, so this can't race mount_media() setting a fresh
        mount_dir concurrently — e.g. the poll thread noticing a real
        disconnect while the main thread is mid-mount), so a second call
        is a safe no-op rather than re-running fusermount on a stale path.
        """
        with self._mount_lock:
            mount_dir = self._mount_dir
            self._mount_dir = None
        if mount_dir:
            self._do_unmount(mount_dir)

    def unmount_path(self, path: str):
        """
        Unmount an arbitrary mount path — used for stale mounts left over
        from a previous session. If it happens to be the mount this manager
        is currently tracking, clears that tracked state too so the two
        never drift out of sync.
        """
        with self._mount_lock:
            if path == self._mount_dir:
                self._mount_dir = None
        self._do_unmount(path)

    def _unmount(self):
        self.unmount_current()

    def disconnect(self):
        self.unmount_current()
        self._device = None

    @property
    def mount_dir(self) -> Optional[str]:
        """The single source of truth for 'what is currently mounted', or
        None if nothing is mounted. Set by mount_media() on success, cleared
        by unmount_current()/unmount_path()/disconnect()."""
        with self._mount_lock:
            return self._mount_dir

    @property
    def device(self) -> Optional[DeviceInfo]:
        return self._device
