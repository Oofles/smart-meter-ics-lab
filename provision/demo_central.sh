#!/usr/bin/env bash
# demo_central.sh — turn a field kit into the DV-DEMO central node (collector + dashboard +
# RF console), on the isolated DEMO mesh channel. This is the demo's Kit 43.
#
# The DV demo (Kits 43-45) is a SEPARATE mesh from the live exercise: it runs on channel 58
# (908.125 MHz), fully PHY-isolated from the exercise's channel 65 (915.125 MHz), so demo
# payloads never touch the blue-team kits. See DEMO.md for the whole runbook.
#
# Run this ON the demo central Pi AFTER it's been built as a field kit on the demo channel:
#     sudo HAT_CHANNEL=58 provision/provision.sh 43     # base build on the demo channel
#     sudo provision/demo_central.sh 43 58              # convert to central (this script)
#
#   sudo provision/demo_central.sh [kit] [channel]
#     kit      default 43 — Pi 192.168.1.(100+kit), own Opta 192.168.1.(200+kit)
#     channel  default 58 (908.125 MHz) — the demo mesh channel
#
# It converts a field kit into a central node the same way drone.sh repurposes one:
#   - stops/disables the mesh listener (the collector owns the HAT instead);
#   - writes the HAT to --rssi + --channel <ch> (central needs RSSI-append for the range map);
#   - installs + enables smartmeter-collector.service pointed at THIS kit's own Opta;
#   - the collector serves the dashboard on :8090 and injects payloads via its RF console
#     (POST /api/send), so the same node aggregates status AND pushes the demo attack.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"

KIT="${1:-43}"
CHANNEL="${2:-58}"
[[ "$KIT" =~ ^[0-9]+$ ]] && [ "$KIT" -ge 1 ] && [ "$KIT" -le 99 ] || {
  echo "usage: sudo provision/demo_central.sh [kit 1..99] [channel]" >&2; exit 2; }
[[ "$CHANNEL" =~ ^[0-9]+$ ]] || { echo "channel must be a number (got '$CHANNEL')" >&2; exit 2; }
OPTA_IP="192.168.1.$((200 + KIT))"
PI_IP="192.168.1.$((100 + KIT))"

echo "== demo central: Kit $KIT (Pi $PI_IP, own Opta $OPTA_IP) on channel $CHANNEL =="

echo "-- stop/disable the mesh listener (the collector owns the HAT) --"
if systemctl list-unit-files smartmeter-listener.service 2>/dev/null | grep -q smartmeter-listener; then
  sudo systemctl disable --now smartmeter-listener 2>/dev/null || true
  echo "   disabled smartmeter-listener.service (this Pi was built as a field kit)"
else
  echo "   no listener service present — nothing to disable"
fi

echo "-- configure HAT: RSSI-append + demo channel $CHANNEL --"
if ! sudo python3 "$HERE/hat_config.py" --rssi --channel "$CHANNEL"; then
  echo "   WARNING: HAT config failed — check jumpers (UART-select=B, M0/M1 caps removed)," >&2
  echo "            seating, antenna, /dev/ttyAMA0. Re-run: sudo python3 provision/hat_config.py --rssi --channel $CHANNEL" >&2
fi

echo "-- install + enable smartmeter-collector.service (own Opta $OPTA_IP, dashboard :8090) --"
sudo tee /etc/systemd/system/smartmeter-collector.service >/dev/null <<UNIT
[Unit]
# DV-demo central node (Kit $KIT): RX status beacons over LoRa, poll own Opta, serve the
# dashboard + /api/fleet, and inject payloads via the RF console (POST /api/send). Runs on
# the isolated demo mesh (channel $CHANNEL) — see DEMO.md.
Description=Smart-meter fleet collector (DV-demo central: beacon RX + dashboard + RF console)
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$REPO
# Unbuffered so RX-beacon/TX lines hit journalctl live (Python block-buffers under systemd).
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 $REPO/central/collector.py --host $OPTA_IP --port 8090
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now smartmeter-collector.service

echo
echo "demo central up: Kit $KIT on channel $CHANNEL."
echo "  dashboard:  http://$PI_IP:8090/   (open this for the DVs)"
echo "  RF console: the dashboard buttons, or:"
echo "     curl -s -XPOST localhost:8090/api/send -d '{\"type\":\"malicious\",\"ttl\":1}'   # trip (TEST)"
echo "     curl -s -XPOST localhost:8090/api/send -d '{\"type\":\"reset\",\"ttl\":1}'       # recover"
echo "  logs:       journalctl -u smartmeter-collector -f"
