#!/usr/bin/env python3
"""
MoTunes Mount Diagnostic
Run this while iPhone is mounted to see exactly what the scanner sees.
"""
import os
import sys
import time
from pathlib import Path

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".aiff"}

# Find the active mount
import glob
mounts = glob.glob("/tmp/motunes_media_*")
if not mounts:
    print("ERROR: No motunes mount found. Mount the device first.")
    sys.exit(1)

mount = mounts[0]
print(f"Mount point: {mount}")
print(f"Contents: {os.listdir(mount)}")
print()

# Test each candidate path exactly as the scanner does
candidates = [
    os.path.join(mount, "Purchases"),
    os.path.join(mount, "Music"),
    os.path.join(mount, "iTunes_Control", "Music"),
    os.path.join(mount, "Media", "iTunes_Control", "Music"),
    os.path.join(mount, "Media", "Music"),
    os.path.join(mount, "Media", "Purchases"),
]

print("=== Search Root Check ===")
found = []
for path in candidates:
    exists = os.path.isdir(path)
    print(f"  {'✅' if exists else '❌'}  {path}")
    if exists:
        if "iTunes_Control" in path:
            try:
                subdirs = [
                    os.path.join(path, d)
                    for d in os.listdir(path)
                    if os.path.isdir(os.path.join(path, d))
                ]
                found.extend(subdirs if subdirs else [path])
                print(f"      -> iTunes subdirs: {[os.path.basename(s) for s in subdirs]}")
            except Exception as e:
                print(f"      -> listdir error: {e}")
                found.append(path)
        else:
            found.append(path)

print()
print(f"=== Final search roots ({len(found)}) ===")
for r in found:
    print(f"  {r}")

print()
print("=== Walking for audio files ===")
total_found = 0
t0 = time.time()
for root in found:
    print(f"  Walking: {root}")
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            audio = [f for f in filenames if Path(f).suffix.lower() in AUDIO_EXTENSIONS]
            if audio:
                print(f"    {dirpath}: {len(audio)} audio files -> {audio[:3]}")
                total_found += len(audio)
            elapsed = time.time() - t0
            if elapsed > 10:
                print(f"    WARNING: Walk taking {elapsed:.1f}s, stopping early")
                break
    except Exception as e:
        print(f"    Walk error: {e}")

print()
print(f"Total audio files found: {total_found}")
print(f"Time elapsed: {time.time() - t0:.2f}s")
