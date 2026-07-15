#!/usr/bin/env bash
# drone.sh — provision ONE Pi as the RF "drone" / injection node.
#
# The drone is the ATTACKER: it transmits malicious firmware-update frames over LoRa
# (`listener.py --send malicious`) which every field kit in range hears, applies
# (FW_MODE trip over Modbus), and flood-relays hop-by-hop to the rest of the fleet.
#
# It differs from a field kit (provision.sh) in three ways:
#   - NO Opta         — it injects; it doesn't run a meter. Nothing to flash, no Opta IP.
#   - NO listener SERVICE — the mesh-node listener beacons + holds the radio; the drone
#                       injects ON DEMAND, so we make sure that service is OFF (a Pi that
#                       was previously a field kit gets its leftover service disabled).
#   - IP is optional  — the drone attacks over RF and serves nothing, so its wired IP is
#                       only for facilitator SSH. Set one if you like, or leave it as-is.
# What it still needs, same as a kit: UART header on / login console off, pyserial+lgpio,
# SSH management keys, and the HAT on the GOLDEN config so its frames interoperate.
#
# Run this ON the drone Pi (git clone the repo first), same spirit as provision.sh:
#   sudo provision/drone.sh [octet] [phase ...]
#     octet   optional 1..254 — set this Pi's wired IP to 192.168.1.<octet>. OMIT to
#             leave networking untouched (e.g. this Pi is already addressed).
#     phases  default all, in order: system serial net ssh undo-kit hat verify
#             ('net' is a no-op when no octet is given.)
#
# Works on a fresh Pi OR on a Pi previously built as a field kit. The backup drone
# (Pi Zero) is built exactly the same way.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
HOME_DIR="$(getent passwd "$RUN_USER" | cut -d: -f6)"

OCTET=""
if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
  OCTET="$1"; shift
  { [ "$OCTET" -ge 1 ] && [ "$OCTET" -le 254 ]; } || {
    echo "octet must be 1..254 (got '$OCTET')" >&2; exit 2; }
fi

phase_system() {
  echo "== system: packages (no dfu-util — the drone has no Opta) =="
  sudo apt-get update
  sudo apt-get install -y python3-serial python3-lgpio git curl openssh-server
}

phase_serial() {
  echo "== serial: enable UART hardware for the LoRa HAT, disable login console =="
  sudo raspi-config nonint do_serial_hw 0      # enable the header UART (/dev/ttyAMA0)
  sudo raspi-config nonint do_serial_cons 1    # disable serial login shell
  echo "   (a reboot is needed for the UART change to take effect)"
}

phase_net() {
  if [ -z "$OCTET" ]; then
    echo "== net: no octet given — leaving wired networking unchanged =="
    return
  fi
  local PI_IP="192.168.1.${OCTET}"
  echo "== net: static wired IP $PI_IP/24 =="
  local CON; CON="$(nmcli -t -f NAME,TYPE con show | awk -F: '$2=="802-3-ethernet"{print $1; exit}')"
  [ -n "${CON:-}" ] || { echo "   no wired NetworkManager connection found — set static IP manually"; return; }
  # never-default so eth0 does NOT install a default route (WiFi stays the internet path
  # during setup) — same rationale as provision.sh phase_net.
  sudo nmcli con mod "$CON" ipv4.addresses "$PI_IP/24" ipv4.method manual \
       ipv4.gateway "" ipv4.never-default yes
  sudo nmcli con up "$CON" || true
  echo "   wired IP set to $PI_IP (WiFi left on DHCP for internet)."
}

phase_ssh() {
  echo "== ssh: enable server + install management keys =="
  sudo systemctl enable --now ssh
  install -d -m 700 -o "$RUN_USER" -g "$RUN_USER" "$HOME_DIR/.ssh"
  sudo touch "$HOME_DIR/.ssh/authorized_keys"
  while IFS= read -r k; do
    [ -z "$k" ] && continue
    case "$k" in \#*) continue ;; esac
    sudo grep -qF "$k" "$HOME_DIR/.ssh/authorized_keys" || echo "$k" | sudo tee -a "$HOME_DIR/.ssh/authorized_keys" >/dev/null
  done < "$HERE/authorized_keys"
  sudo chmod 600 "$HOME_DIR/.ssh/authorized_keys"
  sudo chown -R "$RUN_USER:$RUN_USER" "$HOME_DIR/.ssh"
  echo "   ssh up; keys from provision/authorized_keys installed for $RUN_USER"
}

phase_undo_kit() {
  echo "== undo-kit: ensure the mesh-node listener is OFF (the drone injects on demand) =="
  if systemctl list-unit-files smartmeter-listener.service 2>/dev/null | grep -q smartmeter-listener; then
    sudo systemctl disable --now smartmeter-listener 2>/dev/null || true
    echo "   disabled smartmeter-listener.service (this Pi had been built as a field kit)"
  else
    echo "   no listener service present — nothing to disable"
  fi
}

phase_hat() {
  echo "== hat: configure the LoRa HAT to GOLDEN so its frames interoperate with the fleet =="
  # No --rssi (that's the central collector) and no Opta flash (the drone has none).
  if ! sudo python3 "$HERE/hat_config.py"; then
    echo "   WARNING: HAT config failed — check jumpers (UART-select=B, M0/M1 caps removed)," >&2
    echo "            seating, antenna, and that it's on /dev/ttyAMA0. Re-run this phase after fixing:" >&2
    echo "            sudo provision/drone.sh hat" >&2
  fi
}

phase_verify() {
  echo "== verify: HAT config + benign TX smoke test (no trip) =="
  python3 "$HERE/hat_config.py" --read || echo "   (HAT read failed — check jumpers/seating)"
  echo "   -- benign inject (no meter trips; proves the TX path) --"
  python3 "$REPO/listener/listener.py" --send benign || echo "   (TX failed — check HAT)"
}

PHASES="${*:-system serial net ssh undo-kit hat verify}"
for p in $PHASES; do "phase_${p//-/_}"; done
echo
echo "drone: phases [$PHASES] complete."
echo "Inject with:  cd $REPO/listener && python3 listener.py --send malicious [--exercise]"
