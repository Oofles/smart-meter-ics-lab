#!/usr/bin/env bash
# Flash the Opta smart-meter firmware from the Pi over USB — no Arduino toolchain needed,
# just dfu-util + the prebuilt binary (opta/firmware/smart_meter.ino.bin).
#
# The Opta must be connected to the Pi by USB. A 1200-baud "touch" drops it into its DFU
# bootloader (VID:PID 2341:0364), then dfu-util writes the image to 0x08040000 and leaves DFU.
#
#   sudo ./opta_flash.sh                       # uses ../opta/firmware/smart_meter.ino.bin
#   sudo ./opta_flash.sh /path/to/firmware.bin
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="${1:-$HERE/../opta/firmware/smart_meter.ino.bin}"
PORT="${OPTA_PORT:-/dev/ttyACM0}"
DFU_ID="2341:0364"
DFU_ADDR="0x08040000"

[ -f "$BIN" ] || { echo "[opta] firmware not found: $BIN" >&2; exit 1; }
command -v dfu-util >/dev/null || { echo "[opta] dfu-util missing: sudo apt install -y dfu-util" >&2; exit 1; }

echo "[opta] firmware: $BIN ($(stat -c%s "$BIN") bytes)"

# If not already in DFU, do the 1200-baud touch on the CDC port to trigger the bootloader.
if ! dfu-util -l 2>/dev/null | grep -q "$DFU_ID"; then
  if [ -e "$PORT" ]; then
    echo "[opta] 1200-baud touch on $PORT -> DFU..."
    python3 -c "import serial,time; serial.Serial('$PORT',1200).close(); time.sleep(2)" || true
  else
    echo "[opta] $PORT not present — is the Opta USB-connected to the Pi?" >&2
  fi
fi

echo "[opta] waiting for DFU device $DFU_ID..."
for _ in $(seq 1 15); do
  dfu-util -l 2>/dev/null | grep -q "$DFU_ID" && break
  sleep 1
done
dfu-util -l 2>/dev/null | grep -q "$DFU_ID" || { echo "[opta] DFU device not found" >&2; exit 1; }

echo "[opta] flashing..."
dfu-util --device "0x${DFU_ID%%:*}:0x${DFU_ID##*:}" -a0 --dfuse-address="${DFU_ADDR}:leave" -D "$BIN"
echo "[opta] done — Opta rebooting into the smart-meter sketch (Modbus TCP @ 192.168.1.210:502)."
