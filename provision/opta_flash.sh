#!/usr/bin/env bash
# Flash the Opta smart-meter firmware from the Pi over USB, with this kit's IP stamped in —
# no Arduino toolchain, just dfu-util + the prebuilt binary (opta/firmware/smart_meter.ino.bin).
#
# The IP host octet is patched into a copy of the .bin at flash time (patch_ip.py finds the
# KITCFGv1 marker), so one firmware serves every kit. A 1200-baud "touch" drops the Opta into
# its DFU bootloader (2341:0364); dfu-util writes to 0x08040000 and leaves DFU.
#
#   sudo ./opta_flash.sh <opta-ip-last-octet> [firmware.bin]
#   sudo ./opta_flash.sh 209                 # kit 9 -> Opta 192.168.1.209
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
OCTET="${1:?usage: sudo ./opta_flash.sh <opta-ip-last-octet> [firmware.bin]}"
BIN="${2:-$HERE/../opta/firmware/smart_meter.ino.bin}"
PORT="${OPTA_PORT:-/dev/ttyACM0}"
DFU_ID="2341:0364"
DFU_ADDR="0x08040000"

[ -f "$BIN" ] || { echo "[opta] firmware not found: $BIN" >&2; exit 1; }
command -v dfu-util >/dev/null || { echo "[opta] dfu-util missing: sudo apt install -y dfu-util" >&2; exit 1; }

PATCHED="$(mktemp --suffix=.bin)"
trap 'rm -f "$PATCHED"' EXIT
echo "[opta] $(python3 "$HERE/patch_ip.py" "$BIN" "$OCTET" "$PATCHED")"

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
dfu-util --device "0x${DFU_ID%%:*}:0x${DFU_ID##*:}" -a0 --dfuse-address="${DFU_ADDR}:leave" -D "$PATCHED"
echo "[opta] done — Opta rebooting; Modbus TCP @ 192.168.1.${OCTET}:502."
