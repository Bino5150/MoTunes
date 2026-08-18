# MoTunes

iPhone manager for Linux. A PySide6 desktop app for backing up music, photos, and videos
from an iPhone to Linux via `libimobiledevice` + `ifuse`, and for managing music on the device.

By BINO of Mo Thugs South.

## Features

- Auto-detects a connected iPhone over USB and mounts it via `ifuse`
- Browse and export the music library (search, ID3/tag editing, VLC-based playback)
- Browse photos/videos grouped by month, with click / ctrl+click / shift+click range-select
- Export selected or all photos & videos, with original timestamps preserved on copy
- Delete selected photos/videos directly from the iPhone (toolbar button or right-click menu)
- Send local audio files to the iPhone via a built-in file browser
- Duplicate-cleanup tools for the on-device music library

## Requirements

### System packages (apt)

```bash
sudo apt install libimobiledevice-utils ifuse fuse usbmuxd
```

- `libimobiledevice-utils` — `idevice_id` / `ideviceinfo` CLI tools used for device detection and info
- `ifuse` — FUSE driver that mounts the iPhone filesystem at `/tmp/motunes_media_*`. **See
  [Device Write Safety](#device-write-safety) below — MoTunes checks the installed ifuse version
  before mounting or writing anything.**
- `fuse` — kernel module and unmount tooling. Depending on your distro this provides `fusermount3`
  (current libfuse3-based installs), `fusermount` (legacy libfuse2 installs), or both — MoTunes
  detects whichever is actually present rather than assuming one name.
- `usbmuxd` — USB multiplexer daemon iOS devices communicate through

### Python packages

```bash
pip install -r requirements.txt
```

PySide6 (Qt6 GUI), eyeD3 + mutagen (audio tag reading), Pillow (photo thumbnails).
`python-vlc` is optional — enables in-app music playback via VLC if installed.

Tested on Python 3.12, Linux Mint.

## Device Write Safety

MoTunes checks the installed `ifuse` version (and a few other runtime facts) before it will mount
the iPhone or perform any write to it — sending music, deleting photos/videos, or editing tags all
go through the same check, not just the buttons that normally trigger them.

**Why:** upstream ([libimobiledevice/ifuse](https://github.com/libimobiledevice/ifuse)) identifies
exact version **1.2.0** as having a serious data-corruption bug and says not to use it in
production; it's fixed in **1.2.1**. That warning isn't scoped to writes only, so MoTunes refuses
to mount at all when it detects exactly 1.2.0 — the mount command is never even run.

**What MoTunes does, by what it detects:**

| Detected environment                          | Mount | Device writes |
|------------------------------------------------|:-----:|:--------------:|
| ifuse ≥ 1.2.1                                   | ✅    | ✅             |
| ifuse exactly 1.2.0 (known data-corruption bug) | ❌    | ❌             |
| ifuse < 1.2.0 (older, unverified for writes)    | ✅    | ❌ (read-only) |
| ifuse version can't be determined               | ✅    | ❌ (read-only) |
| ifuse not installed                             | ❌    | ❌             |
| no usable unmount tool found                    | ❌    | ❌             |

"Read-only" here means MoTunes' own write paths refuse to run — exporting from the iPhone still
works. It does **not** mean the ifuse mount itself was requested or verified as read-only at the
OS/FUSE level; ifuse doesn't document a mechanically-enforced read-only mount option, so MoTunes
hasn't assumed or claimed one exists.

The check runs once at startup and again immediately before each mount attempt, so it always
reflects your currently-installed ifuse — not just whatever was there when MoTunes launched. It
never runs on the 3-second device-connection poll.

MoTunes never installs, upgrades, or otherwise modifies system packages on its own — if a write is
blocked, the app tells you why (usually "upgrade ifuse to 1.2.1+") and leaves the fix to you.

## Running

```bash
python3 motunes.py
```

## Diagnostics

- `motunes_diag.py` — inspect what the music scanner sees on a mounted device
- `storage_diag.py` — dump raw device storage keys from `ideviceinfo`

## Development

Install the development dependencies and run the test suite:

pip install -r requirements-dev.txt

QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v
