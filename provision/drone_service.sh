#!/usr/bin/env bash
# drone_service.sh — install the autonomous drone-payload boot service on THIS drone Pi.
#
# The deployed drone is headless and off the network (RF is its only link), so the attack
# has to start with no SSH. This installs a systemd unit that, on boot, waits a countdown
# (time to launch) and then runs the injection loop (listener.py --send ... --loop). The
# payload/timing live in /etc/default/smartmeter-drone — one line to swap TEST -> LOCK.
#
# SAFETY: the unit is installed **DISABLED**. A normal boot does NOTHING, so you can build
# and configure the drone at the bench without it attacking. ENABLING the service is the
# deliberate "arm for the field" step — after that, every power-on runs the payload.
#
#   sudo provision/drone_service.sh        # install unit + default config (leaves it DISABLED)
#
# Then, at the end of bench prep, arm it for the field:
#   sudo systemctl enable smartmeter-drone         # arm: will run on every boot
#   sudo systemctl disable smartmeter-drone        # disarm: back to inert boots
#   sudo systemctl start smartmeter-drone          # start now (also honors the countdown)
#   journalctl -u smartmeter-drone -f              # watch the countdown + injections
#
# Swap the payload (do this before exercise day):
#   sudoedit /etc/default/smartmeter-drone   # set DRONE_MODE=--exercise for EXERCISE LOCK
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
CONF=/etc/default/smartmeter-drone
UNIT=/etc/systemd/system/smartmeter-drone.service

[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }

# Config: written once, never clobbered on re-run (so a re-install keeps your payload choice).
if [ -e "$CONF" ]; then
  echo "== config: $CONF exists — keeping it (edit it to change payload/timing) =="
else
  echo "== config: writing $CONF (TEST trip by default) =="
  cat > "$CONF" <<'CONF'
# /etc/default/smartmeter-drone — autonomous drone payload settings.
# Read by smartmeter-drone.service. Change here, then reboot (or: systemctl restart).

# What to send. malicious = the attack; benign = harmless version heartbeat (safe dry run).
DRONE_SEND=malicious

# Attack severity. Leave EMPTY for a TEST trip (operator RESET clears it).
# Set to --exercise for the full EXERCISE LOCK (operator RESET disabled; only a
# facilitator re-flash / `listener.py --send reset` recovers). *** Swap to --exercise
# before exercise day. ***
DRONE_MODE=

# Hop limit. 1 = trip only kits in the drone's DIRECT range as it passes (no mesh relay).
# Raise (2-3) to also flood out-of-range kits via neighbours' relays.
DRONE_TTL=1

# Seconds between re-injections while flying (fresh msg_id each pass -> newly-in-range kits trip).
DRONE_INTERVAL=5

# Launch countdown: seconds after the service starts before the FIRST injection — the
# window to get the drone airborne/placed before the payload begins.
DRONE_DELAY=60
CONF
  chown "$RUN_USER:$RUN_USER" "$CONF" 2>/dev/null || true
fi

echo "== unit: writing $UNIT =="
cat > "$UNIT" <<UNIT
[Unit]
Description=Smart-meter RF drone — autonomous payload injector (boot-armed)
After=network.target
# never run alongside the mesh-node listener — they'd fight over the one HAT
Conflicts=smartmeter-listener.service

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$REPO/listener
EnvironmentFile=$CONF
Environment=PYTHONUNBUFFERED=1
# \$DRONE_MODE is unbraced on purpose: empty -> no arg (TEST), '--exercise' -> LOCK.
ExecStart=/usr/bin/python3 $REPO/listener/listener.py --send \${DRONE_SEND} --loop \
  --ttl \${DRONE_TTL} --interval \${DRONE_INTERVAL} --start-delay \${DRONE_DELAY} \$DRONE_MODE
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
# make sure a leftover mesh-node listener can't also grab the radio
systemctl disable --now smartmeter-listener.service 2>/dev/null || true
# installed DISABLED — enabling is the deliberate "arm for the field" step
systemctl disable smartmeter-drone.service 2>/dev/null || true

echo
echo "installed + DISABLED (a normal boot does nothing — safe for bench setup)."
echo "  payload : $(grep -E '^DRONE_SEND|^DRONE_MODE' "$CONF" | tr '\n' ' ')"
echo "  arm     : sudo systemctl enable smartmeter-drone     (runs on every boot)"
echo "  test now: sudo systemctl start smartmeter-drone  &&  journalctl -u smartmeter-drone -f"
echo "  swap LOCK: set DRONE_MODE=--exercise in $CONF"
