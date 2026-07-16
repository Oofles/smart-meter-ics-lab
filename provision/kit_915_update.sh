#!/usr/bin/env bash
# kit_915_update.sh — push the 915 MHz HAT re-channel to ONE already-built kit, over SSH.
#
# Run this FROM THE FACILITATOR LAPTOP while connected to that kit's (isolated) switch.
# The kits are segregated islands with no internet, so this does NOT `git pull` on the kit —
# it copies THIS laptop's committed provision/hat_config.py to the kit and runs it there,
# writing channel 65 / 915.125 MHz into the HAT's NVM (persists across reboots; no reboot needed).
#
# Usage:  provision/kit_915_update.sh <kit-number> [read]
#   <kit-number>  0..99 — kit N is Pi 192.168.1.(100+N). Kit 0 is the central node
#                 (smartmeter-collector service + --rssi HAT config); 1..99 are field kits.
#   read          optional — just read back the kit's current HAT config, change nothing.
#
# Env overrides:
#   KIT_USER   SSH login user on the kit           (default: pi)
#   KIT_KEY    path to the management private key   (default: ssh's normal resolution)
#   KIT_REPO   repo path on the kit                 (default: /home/$KIT_USER/smart-meter-ics-lab)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LOCAL_HATCFG="$HERE/hat_config.py"

KIT="${1:-}"
MODE="${2:-write}"
[[ "$KIT" =~ ^[0-9]+$ ]] && [ "$KIT" -ge 0 ] && [ "$KIT" -le 99 ] || {
  echo "usage: $0 <kit-number 0..99> [read]" >&2; exit 2; }

SSH_USER="${KIT_USER:-pi}"
PI_IP="192.168.1.$((100 + KIT))"
REMOTE_REPO="${KIT_REPO:-/home/$SSH_USER/smart-meter-ics-lab}"

# Kit 0 = central collector (RSSI-append HAT + different service); field kits are plain.
if [ "$KIT" -eq 0 ]; then SERVICE="smartmeter-collector"; RSSI="--rssi"
else                       SERVICE="smartmeter-listener";  RSSI=""; fi

SSH_OPTS=(-o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)
[ -n "${KIT_KEY:-}" ] && SSH_OPTS+=(-i "$KIT_KEY")
TARGET="$SSH_USER@$PI_IP"

# Guard: never push a stale hat_config.py — the local copy MUST be the 915 (0x41) version.
grep -q '0x41' "$LOCAL_HATCFG" || {
  echo "REFUSING: $LOCAL_HATCFG is not the 915 MHz version (no 0x41 channel byte)." >&2
  echo "          Run 'git pull' on this laptop first." >&2; exit 3; }

echo "== Kit $KIT  ->  $TARGET   (service: $SERVICE ${RSSI:-})"
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
  exit 0
fi

echo "   copying the 915 MHz hat_config.py to the kit..."
scp "${SSH_OPTS[@]}" "$LOCAL_HATCFG" "$TARGET:$REMOTE_REPO/provision/hat_config.py" >/dev/null

echo "   stopping listener, writing HAT NVM, verifying, restarting..."
# -t so sudo can prompt for a password if this kit's user isn't NOPASSWD.
# hat_config.py exits non-zero on a readback mismatch; we capture that but ALWAYS restart the service.
ssh -t "${SSH_OPTS[@]}" "$TARGET" "
  set -u
  sudo systemctl stop '$SERVICE' 2>/dev/null || true
  sleep 1
  sudo python3 '$REMOTE_REPO/provision/hat_config.py' $RSSI
  rc=\$?
  echo '--- readback ---'
  sudo python3 '$REMOTE_REPO/provision/hat_config.py' --read || true
  sudo systemctl start '$SERVICE' 2>/dev/null || true
  exit \$rc" && {
    echo
    echo "OK — Kit $KIT is on channel 65 / 915.125 MHz, $SERVICE restarted."
    exit 0
  } || {
    echo >&2
    echo "FAILED on Kit $KIT — HAT config did not verify (see readback above)." >&2
    echo "The $SERVICE service was restarted regardless. Check HAT jumpers/wiring and retry." >&2
    exit 5
  }
