#!/usr/bin/env bash
# demo_channel_update.sh — push (or read back) a kit's HAT mesh channel over SSH.
#
# The DV demo (Kits 43-45) runs on a SEPARATE mesh channel from the live exercise so its
# payloads never reach the blue-team kits: demo = channel 58 (908.125 MHz), exercise =
# channel 65 (915.125 MHz). Different channels are fully PHY-isolated (a radio only
# demodulates its own centre frequency). This tool sets a kit onto the demo channel, and —
# in `read` mode — reads back a kit's current channel so you can PROVE the two meshes don't
# overlap before showing the demo. See DEMO.md.
#
# Run this FROM THE FACILITATOR LAPTOP while on that kit's (isolated) switch. It copies THIS
# laptop's committed provision/hat_config.py to the kit and runs it there (writes NVM; no reboot).
#
# Usage:  provision/demo_channel_update.sh <kit-number> [read]
#   <kit-number>  1..99 — kit N is Pi 192.168.1.(100+N).
#   read          optional — just read back the kit's current HAT config, change nothing.
#
# Env overrides:
#   DEMO_CHANNEL   mesh channel to write            (default: 58 = 908.125 MHz)
#   DEMO_CENTRAL   which kit is the demo central     (default: 43 — gets --rssi + collector svc)
#   KIT_USER       SSH login user on the kit         (default: cs26)
#   KIT_KEY        management private key path        (default: ssh's normal resolution)
#   KIT_REPO       repo path on the kit               (default: /home/$KIT_USER/smart-meter-ics-lab)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LOCAL_HATCFG="$HERE/hat_config.py"

KIT="${1:-}"
MODE="${2:-write}"
[[ "$KIT" =~ ^[0-9]+$ ]] && [ "$KIT" -ge 1 ] && [ "$KIT" -le 99 ] || {
  echo "usage: $0 <kit-number 1..99> [read]" >&2; exit 2; }

DEMO_CHANNEL="${DEMO_CHANNEL:-58}"
DEMO_CENTRAL="${DEMO_CENTRAL:-43}"
[[ "$DEMO_CHANNEL" =~ ^[0-9]+$ ]] || { echo "DEMO_CHANNEL must be a number (got '$DEMO_CHANNEL')" >&2; exit 2; }

SSH_USER="${KIT_USER:-cs26}"
PI_IP="192.168.1.$((100 + KIT))"
REMOTE_REPO="${KIT_REPO:-/home/$SSH_USER/smart-meter-ics-lab}"

# The demo central runs the collector (RSSI-append HAT); field kits run the plain listener.
if [ "$KIT" -eq "$DEMO_CENTRAL" ]; then SERVICE="smartmeter-collector"; RSSI="--rssi"
else                                    SERVICE="smartmeter-listener";  RSSI=""; fi

SSH_OPTS=(-o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)
[ -n "${KIT_KEY:-}" ] && SSH_OPTS+=(-i "$KIT_KEY")
TARGET="$SSH_USER@$PI_IP"

# Guard: the local hat_config.py must support --channel (older copies don't). Prevents pushing
# a stale file that would silently write GOLDEN (ch 65 = the EXERCISE mesh) onto a demo kit.
grep -q -- '--channel' "$LOCAL_HATCFG" || {
  echo "REFUSING: $LOCAL_HATCFG has no --channel support (stale copy)." >&2
  echo "          Run 'git pull' on this laptop first." >&2; exit 3; }

echo "== Kit $KIT  ->  $TARGET   (service: $SERVICE ${RSSI:-}, channel: $DEMO_CHANNEL)"
echo "   reaching the kit..."
ssh "${SSH_OPTS[@]}" "$TARGET" true || {
  echo "CANNOT REACH $TARGET — are you on Kit $KIT's switch, and is KIT_USER right?" >&2; exit 4; }

# read-only mode: stop service, read HAT config, restart. Changes nothing.
if [ "$MODE" = "read" ]; then
  scp "${SSH_OPTS[@]}" "$LOCAL_HATCFG" "$TARGET:$REMOTE_REPO/provision/hat_config.py" >/dev/null
  ssh -t "${SSH_OPTS[@]}" "$TARGET" "
    sudo systemctl stop '$SERVICE' 2>/dev/null || true; sleep 1
    sudo python3 '$REMOTE_REPO/provision/hat_config.py' --read
    sudo systemctl start '$SERVICE' 2>/dev/null || true"
  echo "   (channel byte is the 6th: 3a=ch58 demo, 41=ch65 exercise)"
  exit 0
fi

echo "   copying hat_config.py to the kit..."
scp "${SSH_OPTS[@]}" "$LOCAL_HATCFG" "$TARGET:$REMOTE_REPO/provision/hat_config.py" >/dev/null

echo "   stopping $SERVICE, writing HAT NVM (channel $DEMO_CHANNEL), verifying, restarting..."
# -t so sudo can prompt if this kit's user isn't NOPASSWD. hat_config.py exits non-zero on a
# readback mismatch; capture that but ALWAYS restart the service.
ssh -t "${SSH_OPTS[@]}" "$TARGET" "
  set -u
  sudo systemctl stop '$SERVICE' 2>/dev/null || true
  sleep 1
  sudo python3 '$REMOTE_REPO/provision/hat_config.py' $RSSI --channel $DEMO_CHANNEL
  rc=\$?
  echo '--- readback ---'
  sudo python3 '$REMOTE_REPO/provision/hat_config.py' --read || true
  sudo systemctl start '$SERVICE' 2>/dev/null || true
  exit \$rc" && {
    echo
    echo "OK — Kit $KIT is on channel $DEMO_CHANNEL, $SERVICE restarted."
    exit 0
  } || {
    echo >&2
    echo "FAILED on Kit $KIT — HAT config did not verify (see readback above)." >&2
    echo "The $SERVICE service was restarted regardless. Check HAT jumpers/wiring and retry." >&2
    exit 5
  }
