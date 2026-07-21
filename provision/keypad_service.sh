#!/usr/bin/env bash
# keypad_service.sh — install the USB-macropad RF-trigger service on THIS central node (Kit 00).
#
# The 4-key pad becomes a physical shortcut for the dashboard's send button: each key
# POSTs to the local collector's /api/send, which broadcasts the payload over LoRa (and
# trips Kit 00's own Opta). See central/keypad.py for the full data path.
#
# This installs python3-evdev, puts the run user in the `input` group (so it can read
# /dev/input/*), and installs the systemd unit. It does NOT save a key mapping — you do
# that once, interactively, with --learn (the unit won't start until you have).
#
#   sudo provision/keypad_service.sh          # install deps + unit (leaves it stopped)
#   sudo python3 central/keypad.py --learn    # press each pad key to bind it
#   sudo systemctl enable --now smartmeter-keypad   # start now + arm on boot
#   journalctl -u smartmeter-keypad -f              # watch keypresses fire
#
# Rebind any time by re-running --learn, then: sudo systemctl restart smartmeter-keypad
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
UNIT=/etc/systemd/system/smartmeter-keypad.service
CONFIG=/etc/smartmeter-keypad.json

[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }

echo "== deps: python3-evdev =="
if ! python3 -c "import evdev" 2>/dev/null; then
  apt-get install -y python3-evdev
else
  echo "python3-evdev already present"
fi

echo "== input group: add $RUN_USER (read /dev/input/*) =="
usermod -aG input "$RUN_USER"

echo "== unit: $UNIT (User=$RUN_USER) =="
# Stamp the run user into the unit so it matches this box (default in-repo unit is vivicat).
sed "s/^User=.*/User=$RUN_USER/" "$REPO/central/smartmeter-keypad.service" > "$UNIT"
systemctl daemon-reload

echo
echo "installed (stopped). Next:"
if [ -e "$CONFIG" ]; then
  echo "  mapping present at $CONFIG — re-run --learn to change it, or just start:"
else
  echo "  1) bind your keys:   sudo python3 $REPO/central/keypad.py --learn"
fi
echo "  2) start + arm:      sudo systemctl enable --now smartmeter-keypad"
echo "  3) watch:            journalctl -u smartmeter-keypad -f"
echo
echo "NOTE: $RUN_USER was just added to 'input' — if the daemon can't read the pad,"
echo "      log out/in (or reboot) so the new group membership takes effect."
