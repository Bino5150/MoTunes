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
- `ifuse` — FUSE driver that mounts the iPhone filesystem at `/tmp/motunes_media_*`
- `fuse` — kernel module + `fusermount`, used to unmount on disconnect/exit
- `usbmuxd` — USB multiplexer daemon iOS devices communicate through

### Python packages

```bash
pip install -r requirements.txt
```

PySide6 (Qt6 GUI), eyeD3 + mutagen (audio tag reading), Pillow (photo thumbnails).
`python-vlc` is optional — enables in-app music playback via VLC if installed.

Tested on Python 3.12, Linux Mint.

## Running

```bash
python3 motunes.py
```

## Diagnostics

- `motunes_diag.py` — inspect what the music scanner sees on a mounted device
- `storage_diag.py` — dump raw device storage keys from `ideviceinfo`
