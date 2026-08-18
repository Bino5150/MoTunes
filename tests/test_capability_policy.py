"""
Regression coverage for the pure policy layer in core/capability.py —
decide_policy() and parse_ifuse_version() are plain functions of their
input, deliberately kept free of subprocess/Qt/filesystem I/O, so every
branch of the version/dependency table is directly testable without
touching a real environment.

Covers spec items 1-9 of the Phase 0B Slice 2 checkpoint: the exact
1.2.0 hard block, the 1.2.1 write-eligible floor, a hypothetical future
version not being penalized for being newer, the conservative legacy
default, and the various "can't tell" / "missing" failure-closed states.
"""
import subprocess as subprocess_module

import pytest

from core.capability import (
    RuntimeCapability,
    WritePolicy,
    decide_policy,
    parse_ifuse_version,
    probe_capability,
    KNOWN_CORRUPTING_IFUSE_VERSION,
    MIN_VERIFIED_SAFE_IFUSE_VERSION,
)


def _capability(**overrides) -> RuntimeCapability:
    """A fully-present, fully-healthy baseline — override just the fact
    under test so each test's intent stays legible."""
    base = dict(
        ifuse_present=True,
        ifuse_version_raw="ifuse 1.2.1",
        ifuse_version=(1, 2, 1),
        idevice_id_present=True,
        ideviceinfo_present=True,
        unmount_binary="fusermount3",
    )
    base.update(overrides)
    return RuntimeCapability(**base)


# ── 1. Exact 1.2.0 is hard-blocked ───────────────────────────────────────────

def test_exact_1_2_0_is_hard_blocked():
    cap = _capability(ifuse_version_raw="ifuse 1.2.0", ifuse_version=(1, 2, 0))
    decision = decide_policy(cap)
    assert decision.write_policy == WritePolicy.BLOCKED_KNOWN_CORRUPTING
    assert decision.can_mount is False
    assert decision.can_write is False
    assert "1.2.0" in decision.reason
    assert "corrupt" in decision.reason.lower()


# ── 2. 1.2.1 is write-eligible ───────────────────────────────────────────────

def test_1_2_1_is_write_eligible():
    cap = _capability(ifuse_version_raw="ifuse 1.2.1", ifuse_version=(1, 2, 1))
    decision = decide_policy(cap)
    assert decision.write_policy == WritePolicy.WRITE_ENABLED
    assert decision.can_mount is True
    assert decision.can_write is True
    assert decision.is_read_only is False


# ── 3. A future version above 1.2.1 is not penalized for being newer ────────

@pytest.mark.parametrize("version", [(1, 2, 2), (1, 3, 0), (2, 0, 0)])
def test_future_version_above_1_2_1_is_not_rejected(version):
    cap = _capability(ifuse_version_raw=f"ifuse {'.'.join(map(str, version))}", ifuse_version=version)
    decision = decide_policy(cap)
    assert decision.write_policy == WritePolicy.WRITE_ENABLED, (
        f"version {version} is newer than the verified-safe floor "
        f"{MIN_VERIFIED_SAFE_IFUSE_VERSION} and must not be rejected merely for being unfamiliar"
    )
    assert decision.can_write is True


# ── 4. Legacy (<1.2.0) defaults to conservative read-only ───────────────────

@pytest.mark.parametrize("version", [(1, 1, 3), (1, 0, 0), (0, 9, 5)])
def test_legacy_pre_1_2_0_is_read_only_not_corrupt(version):
    cap = _capability(ifuse_version_raw=f"ifuse {'.'.join(map(str, version))}", ifuse_version=version)
    decision = decide_policy(cap)
    assert decision.write_policy == WritePolicy.READ_ONLY_LEGACY, (
        "an old version must not be lumped in with the known-corrupting 1.2.0 block"
    )
    assert decision.can_mount is True, "legacy must still be mountable for reads"
    assert decision.can_write is False
    assert decision.is_read_only is True


# ── 5. Missing ifuse ──────────────────────────────────────────────────────────

def test_missing_ifuse_blocks_mount_entirely():
    cap = _capability(ifuse_present=False, ifuse_version_raw="", ifuse_version=None)
    decision = decide_policy(cap)
    assert decision.write_policy == WritePolicy.BLOCKED_MISSING_IFUSE
    assert decision.can_mount is False
    assert decision.can_write is False
    assert "ifuse" in decision.reason.lower()


# ── 6. Unparseable ifuse version fails closed for writes, not for mounting ──

@pytest.mark.parametrize("garbage", ["", "not a version", "ifuse", "garbled\x00output"])
def test_unparseable_version_fails_closed_for_writes(garbage):
    cap = _capability(ifuse_version_raw=garbage, ifuse_version=parse_ifuse_version(garbage))
    decision = decide_policy(cap)
    assert decision.write_policy == WritePolicy.READ_ONLY_UNVERIFIED_VERSION
    assert decision.can_mount is True, "an unparseable version must not itself block mounting"
    assert decision.can_write is False, "unknown must never be treated as 'probably safe'"


def test_parse_ifuse_version_handles_ordinary_distro_suffixes():
    # Real binaries self-report a clean X.Y.Z even when the distro package
    # version carries packaging-revision junk (verified: this sandbox's
    # `ifuse --version` prints "ifuse 1.1.3" while dpkg's package version
    # is "1.1.4~git20181007.3b00243-1ubuntu3" — the two are not the same
    # string and only the binary's own self-report is authoritative here).
    assert parse_ifuse_version("ifuse 1.2.1") == (1, 2, 1)
    assert parse_ifuse_version("1.2.1-1build2") == (1, 2, 1)
    assert parse_ifuse_version("ifuse version 1.2") == (1, 2, 0)
    assert parse_ifuse_version("") is None
    assert parse_ifuse_version("no digits here") is None


# ── 7. Probe timeout / nonzero failure is a normal result, not an exception ─

def test_probe_capability_survives_subprocess_timeout(monkeypatch):
    def _raise_timeout(*a, **kw):
        raise subprocess_module.TimeoutExpired(cmd=["ifuse", "--version"], timeout=5)

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(subprocess_module, "run", _raise_timeout)

    capability = probe_capability()  # must not raise
    assert capability.ifuse_present is True
    assert capability.ifuse_version is None
    decision = decide_policy(capability)
    assert decision.write_policy == WritePolicy.READ_ONLY_UNVERIFIED_VERSION


def test_probe_capability_survives_subprocess_nonzero_exit(monkeypatch):
    class _FakeResult:
        returncode = 1
        stdout = ""
        stderr = ""

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(subprocess_module, "run", lambda *a, **kw: _FakeResult())

    capability = probe_capability()
    assert capability.ifuse_version is None
    decision = decide_policy(capability)
    assert decision.can_write is False


def test_probe_capability_reads_ifuse_version_from_stderr(monkeypatch):
    """ifuse prints its version line to stderr, not stdout — a probe that
    only checked stdout would see 'no version' on every real install."""
    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = "ifuse 1.2.1\n"

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(subprocess_module, "run", lambda *a, **kw: _FakeResult())

    capability = probe_capability()
    assert capability.ifuse_version == (1, 2, 1)


# ── 8. Missing discovery tool(s) ─────────────────────────────────────────────

@pytest.mark.parametrize("idevice_id_present,ideviceinfo_present", [
    (False, True), (True, False), (False, False),
])
def test_missing_discovery_tools_reported_not_looped(idevice_id_present, ideviceinfo_present):
    from core.capability import discovery_unavailable_reason
    cap = _capability(idevice_id_present=idevice_id_present, ideviceinfo_present=ideviceinfo_present)
    assert cap.discovery_available is False
    reason = discovery_unavailable_reason(cap)
    assert reason is not None
    if not idevice_id_present:
        assert "idevice_id" in reason
    if not ideviceinfo_present:
        assert "ideviceinfo" in reason


def test_discovery_available_when_both_tools_present():
    from core.capability import discovery_unavailable_reason
    cap = _capability()
    assert cap.discovery_available is True
    assert discovery_unavailable_reason(cap) is None


# ── 9. No usable unmount mechanism ───────────────────────────────────────────

def test_no_unmount_binary_is_a_mount_safety_failure():
    cap = _capability(unmount_binary=None)
    assert cap.has_unmount is False
    decision = decide_policy(cap)
    assert decision.write_policy == WritePolicy.BLOCKED_NO_UNMOUNT
    assert decision.can_mount is False, (
        "MoTunes must not create a mount it cannot demonstrate it can safely tear down"
    )


def test_unmount_binary_prefers_fusermount3_but_accepts_fusermount_fallback(monkeypatch):
    """Presence-only probing (shutil.which) — a system with only the
    legacy binary name must still be usable, not treated as 'no unmount
    tool found'."""
    def _which(name):
        return "/usr/bin/fusermount" if name == "fusermount" else None

    monkeypatch.setattr("shutil.which", _which)

    capability = probe_capability()
    assert capability.unmount_binary == "fusermount"
    assert capability.has_unmount is True
