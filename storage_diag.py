#!/usr/bin/env python3
"""Quick storage key diagnostic — run while iPhone is connected."""
import subprocess

result = subprocess.run(["idevice_id", "-l"], capture_output=True, text=True)
udid = result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else None

if not udid:
    print("No device found")
    exit(1)

print(f"UDID: {udid}\n")

# Test all candidate keys
keys = [
    "TotalDiskCapacity", "TotalDataCapacity", "AmountDataAvailable",
    "TotalDataAvailable", "DeviceName", "ProductType", "ProductVersion",
]
for key in keys:
    r = subprocess.run(["ideviceinfo", "-u", udid, "-k", key],
                       capture_output=True, text=True, timeout=5)
    val = r.stdout.strip()
    print(f"{key}: '{val}'")

print("\n--- com.apple.disk_usage domain ---")
r = subprocess.run(["ideviceinfo", "-u", udid, "-d", "com.apple.disk_usage"],
                   capture_output=True, text=True, timeout=10)
# Print only capacity-related lines
for line in r.stdout.splitlines():
    if any(x in line for x in ["Capacity", "Available", "Used", "Total", "Amount"]):
        print(line.strip())
