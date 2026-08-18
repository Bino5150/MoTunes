"""
MoTunes - Runtime Capability & Write-Safety Policy

Determines what the installed iPhone/FUSE environment can safely do
before MoTunes enables or performs any device operation.

Detected facts (RuntimeCapability — what's actually installed) are kept
separate from the policy decision (CapabilityDecision — what MoTunes is
willing to do about it), so a refusal is always traceable to a concrete,
testable input rather than one opaque boolean.

Upstream facts this policy is built on (verified against
https://github.com/libimobiledevice/ifuse README/NEWS/releases):
  - ifuse 1.2.0 ("Switch to libfuse 3", requires libimobiledevice 1.4.0)
    has a serious data-corruption bug; upstream's own release notes say
    "Do not use in production." The warning is not qualified as
    writes-only, so MoTunes treats exact 1.2.0 as unusable for mounting
    at all, not just for writes.
  - ifuse 1.2.1 is a bugfix release ("Fix FUSE capability flags set
    during initialization causing data corruption") and is the version
    upstream considers fixed.
No broader incompatibility beyond what upstream documents is assumed.
"""
import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

# Exact version upstream identifies as data-corrupting, and the first
# version upstream considers fixed. Tuple comparison below means any
# version >= this fixed version is treated as write-eligible, including
# versions upstream hasn't been released yet — it is not a fixed
# allowlist of known-good numbers.
KNOWN_CORRUPTING_IFUSE_VERSION: Tuple[int, int, int] = (1, 2, 0)
MIN_VERIFIED_SAFE_IFUSE_VERSION: Tuple[int, int, int] = (1, 2, 1)

PROBE_TIMEOUT_SECONDS = 5.0


class WritePolicy(Enum):
    """
    READ_ONLY_* states mean MoTunes itself refuses every device-write
    call — TransferEngine TO_DEVICE jobs, PhotoDeleteWorker, tag saves —
    at the application layer. They do NOT mean the ifuse mount was
    requested or verified as read-only at the OS/FUSE level: ifuse's own
    documentation does not describe a mechanically-enforced read-only
    mount option, so MoTunes has not verified one exists and does not
    claim one is in effect. If that ever changes upstream, this is the
    one place to update — do not have callers assume it independently.
    """
    WRITE_ENABLED = "write_enabled"
    READ_ONLY_LEGACY = "read_only_legacy"
    READ_ONLY_UNVERIFIED_VERSION = "read_only_unverified_version"
    BLOCKED_KNOWN_CORRUPTING = "blocked_known_corrupting"
    BLOCKED_MISSING_IFUSE = "blocked_missing_ifuse"
    BLOCKED_NO_UNMOUNT = "blocked_no_unmount"


# Policy states that must never allow ifuse to be invoked at all.
_MOUNT_BLOCKED = frozenset({
    WritePolicy.BLOCKED_KNOWN_CORRUPTING,
    WritePolicy.BLOCKED_MISSING_IFUSE,
    WritePolicy.BLOCKED_NO_UNMOUNT,
})


@dataclass(frozen=True)
class RuntimeCapability:
    """Detected facts only — no policy judgment lives here."""
    ifuse_present: bool = False
    ifuse_version_raw: str = ""
    ifuse_version: Optional[Tuple[int, int, int]] = None
    idevice_id_present: bool = False
    ideviceinfo_present: bool = False
    unmount_binary: Optional[str] = None   # "fusermount3", "fusermount", or None

    @property
    def discovery_available(self) -> bool:
        """Whether device detection (idevice_id + ideviceinfo) can work at all."""
        return self.idevice_id_present and self.ideviceinfo_present

    @property
    def has_unmount(self) -> bool:
        return self.unmount_binary is not None


@dataclass(frozen=True)
class CapabilityDecision:
    """The single authoritative policy decision the rest of MoTunes consumes."""
    capability: RuntimeCapability
    write_policy: WritePolicy
    reason: str

    @property
    def can_mount(self) -> bool:
        return self.write_policy not in _MOUNT_BLOCKED

    @property
    def can_write(self) -> bool:
        return self.write_policy == WritePolicy.WRITE_ENABLED

    @property
    def is_read_only(self) -> bool:
        """Mountable, but device writes are withheld as a precaution."""
        return self.can_mount and not self.can_write


def parse_ifuse_version(raw_output: str) -> Optional[Tuple[int, int, int]]:
    """
    Extract a (major, minor, patch) tuple from ifuse's self-reported
    version string (e.g. "ifuse 1.2.1"). Deliberately reads only the
    leading X.Y[.Z] pattern so ordinary distro/build suffixes after it
    don't prevent a match. Returns None for anything that doesn't
    contain a recognizable version number — callers must treat that as
    "unknown", never as "probably fine".
    """
    if not raw_output:
        return None
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', raw_output)
    if not match:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch or 0))


def _probe_ifuse_version_raw() -> str:
    """
    Run `ifuse --version` and return its combined output, or "" on any
    failure. ifuse prints its version line to stderr, not stdout, so
    both streams are captured and combined — relying on stdout alone
    would silently see "no version" on every real install.
    """
    try:
        result = subprocess.run(
            ["ifuse", "--version"],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS,
        )
        return (result.stdout + result.stderr).strip()
    except Exception:
        return ""


def probe_capability() -> RuntimeCapability:
    """
    Bounded, never-raising inspection of what's actually installed.
    Executable presence is checked via PATH lookup (no subprocess spawn,
    no timeout needed, trivially mockable); only the ifuse version check
    needs an actual subprocess call. A missing executable or malformed
    version string is a normal, representable result here — never an
    exception a caller has to handle.
    """
    ifuse_present = shutil.which("ifuse") is not None
    idevice_id_present = shutil.which("idevice_id") is not None
    ideviceinfo_present = shutil.which("ideviceinfo") is not None

    # Prefer fusermount3 (the libfuse3 generation current ifuse depends
    # on) but fall back to fusermount (legacy libfuse2 installs, or
    # distros that only ship the older name) — a system may genuinely
    # have only one of the two, so neither presence is assumed.
    unmount_binary = None
    if shutil.which("fusermount3") is not None:
        unmount_binary = "fusermount3"
    elif shutil.which("fusermount") is not None:
        unmount_binary = "fusermount"

    ifuse_version_raw = ""
    ifuse_version = None
    if ifuse_present:
        ifuse_version_raw = _probe_ifuse_version_raw()
        ifuse_version = parse_ifuse_version(ifuse_version_raw)

    return RuntimeCapability(
        ifuse_present=ifuse_present,
        ifuse_version_raw=ifuse_version_raw,
        ifuse_version=ifuse_version,
        idevice_id_present=idevice_id_present,
        ideviceinfo_present=ideviceinfo_present,
        unmount_binary=unmount_binary,
    )


def decide_policy(capability: RuntimeCapability) -> CapabilityDecision:
    """
    Turn detected facts into the one policy decision MoTunes acts on.
    Pure function of its input — no I/O — so every branch below is
    reachable and testable without touching a real environment.
    """
    if not capability.ifuse_present:
        return CapabilityDecision(
            capability, WritePolicy.BLOCKED_MISSING_IFUSE,
            "ifuse is not installed — MoTunes cannot mount the iPhone. "
            "Install it with your package manager (e.g. sudo apt install ifuse).",
        )

    if not capability.has_unmount:
        return CapabilityDecision(
            capability, WritePolicy.BLOCKED_NO_UNMOUNT,
            "No usable unmount tool (fusermount or fusermount3) was found — "
            "MoTunes will not create a mount it cannot safely tear down.",
        )

    version = capability.ifuse_version
    if version is None:
        return CapabilityDecision(
            capability, WritePolicy.READ_ONLY_UNVERIFIED_VERSION,
            "Could not determine the installed ifuse version"
            + (f" ({capability.ifuse_version_raw!r})" if capability.ifuse_version_raw else "")
            + " — device writes are disabled until this can be verified. "
              "Exporting from the iPhone is still available.",
        )

    if version == KNOWN_CORRUPTING_IFUSE_VERSION:
        return CapabilityDecision(
            capability, WritePolicy.BLOCKED_KNOWN_CORRUPTING,
            "Installed ifuse is exactly 1.2.0, which upstream has identified as "
            "having a serious data-corruption bug (\"do not use in production\"). "
            "MoTunes will not mount the iPhone until ifuse is upgraded to 1.2.1 "
            "or later.",
        )

    if version >= MIN_VERIFIED_SAFE_IFUSE_VERSION:
        return CapabilityDecision(
            capability, WritePolicy.WRITE_ENABLED,
            "Compatible ifuse version detected.",
        )

    # Anything else is < 1.2.0: the pre-libfuse3 legacy generation. Not
    # known-corrupt, but not verified for writes either — conservative
    # read-only default rather than assuming old means safe.
    version_str = capability.ifuse_version_raw or ".".join(map(str, version))
    return CapabilityDecision(
        capability, WritePolicy.READ_ONLY_LEGACY,
        f"Installed ifuse ({version_str}) predates the version MoTunes has "
        "verified for device writes. Writes are disabled as a precaution — "
        "exporting from the iPhone is still available. Upgrade to ifuse "
        "1.2.1+ to enable writes.",
    )


def discovery_unavailable_reason(capability: RuntimeCapability) -> Optional[str]:
    """
    None if device discovery tools are present; otherwise a concise,
    user-facing explanation of what's missing. Kept separate from
    WritePolicy because missing idevice_id/ideviceinfo prevents device
    *detection*, not specifically writes to an already-mounted device.
    """
    missing = []
    if not capability.idevice_id_present:
        missing.append("idevice_id")
    if not capability.ideviceinfo_present:
        missing.append("ideviceinfo")
    if not missing:
        return None
    return (
        f"{' and '.join(missing)} not found — device detection is unavailable. "
        "Install libimobiledevice-utils."
    )
