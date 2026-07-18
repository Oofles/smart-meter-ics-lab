#!/usr/bin/env bash
# provision.sh — build/provision ONE kit from a fresh Raspberry Pi OS (64-bit, Bookworm/trixie).
#
# Run this ON each kit (git clone the repo first). No golden image, no cloning — every kit is
# built individually, so its wired IP, listener service, and Opta firmware are all stamped
# per-kit. This is the whole replication method: repeat it on each of the 45 kits.
#
# Usage:  sudo provision/provision.sh <kit-number> [phase ...]
#   <kit-number>  1..99 — sets this Pi's wired IP to 192.168.1.(100+kit)  (kit 9 -> .109);
#                 the Opta is flashed to 192.168.1.(200+kit)  (kit 9 -> .209).
#   phases (default all, in order): system serial net ssh service hw verify
#
# Every device is uniquely addressed (Pi .10N, Opta .20N), so the OT switches MAY be bridged
# into one management LAN if you want central reach; the exercise itself runs on isolated
# islands with LoRa RF as the only cross-kit path.
# Assumes: internet (WiFi) available for setup; Waveshare HAT seated; Opta on Pi USB.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
HOME_DIR="$(getent passwd "$RUN_USER" | cut -d: -f6)"

KIT="${1:-}"
[[ "$KIT" =~ ^[0-9]+$ ]] && [ "$KIT" -ge 1 ] && [ "$KIT" -le 99 ] || {
  echo "usage: sudo provision/provision.sh <kit-number 1..99> [phase ...]" >&2; exit 2; }
shift
PI_IP="192.168.1.$((100 + KIT))"
OPTA_OCTET="$((200 + KIT))"
OPTA_IP="192.168.1.${OPTA_OCTET}"

# Run a HAT command with the listener paused — it holds /dev/ttyAMA0 + the M0/M1 GPIO
# lines, so hat_config would hit "GPIO busy" while it runs (e.g. after a reboot on clones).
with_hat() {
  local was=0
  systemctl is-active --quiet smartmeter-listener && was=1
  [ "$was" = 1 ] && { sudo systemctl stop smartmeter-listener; sleep 1; }
  "$@"; local rc=$?
  [ "$was" = 1 ] && sudo systemctl start smartmeter-listener
  return $rc
}

phase_system() {
  echo "== system: packages =="
  sudo apt-get update
  sudo apt-get install -y dfu-util python3-serial python3-lgpio git curl openssh-server
}

phase_serial() {
  echo "== serial: enable UART hardware for the LoRa HAT, disable login console =="
  sudo raspi-config nonint do_serial_hw 0      # enable /dev/serial0 hardware
  sudo raspi-config nonint do_serial_cons 1    # disable serial login shell
  echo "   (a reboot is needed for the UART change to take effect)"
}

phase_net() {
  echo "== net: static wired IP $PI_IP/24 (kit $KIT) =="
  local CON; CON="$(nmcli -t -f NAME,TYPE con show | awk -F: '$2=="802-3-ethernet"{print $1; exit}')"
  [ -n "${CON:-}" ] || { echo "   no wired NetworkManager connection found — set static IP manually"; return; }
  # No gateway on the isolated switch (no router at .1) and never-default so eth0 does NOT
  # install a default route — otherwise it outranks WiFi and kills internet during setup
  # (DNS/docker pulls would go out the dead switch link). WiFi stays the only default route.
  sudo nmcli con mod "$CON" ipv4.addresses "$PI_IP/24" ipv4.method manual \
       ipv4.gateway "" ipv4.never-default yes
  sudo nmcli con up "$CON" || true
  echo "   wired IP set (WiFi left on DHCP for internet). Reach this kit at $PI_IP on the switch."
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

phase_service() {
  echo "== service: install + enable the LoRa listener at boot =="
  sudo tee /etc/systemd/system/smartmeter-listener.service >/dev/null <<UNIT
[Unit]
Description=Smart-meter LoRa update listener (mesh node)
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$REPO/listener
# Unbuffered so the listener's RX/APPLY lines hit journalctl live — facilitators can
# watch the attack land in real time (Python block-buffers stdout under systemd otherwise).
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 $REPO/listener/listener.py --host $OPTA_IP
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
  sudo systemctl daemon-reload
  sudo systemctl enable smartmeter-listener.service
  echo "   enabled (starts on boot; 'systemctl start smartmeter-listener' to run now)"
}

phase_hw() {
  echo "== hardware: flash this Opta ($OPTA_IP) + configure this HAT =="
  # HAT_CHANNEL overrides the mesh channel (default = GOLDEN ch 65 / 915.125 MHz, the
  # exercise fleet). Set HAT_CHANNEL=58 to build a kit onto the DV-demo mesh (908.125 MHz,
  # PHY-isolated from the exercise) — see DEMO.md. Empty => hat_config.py's default (65).
  local CH_ARG=""
  [ -n "${HAT_CHANNEL:-}" ] && { CH_ARG="--channel $HAT_CHANNEL"; echo "   (HAT_CHANNEL=$HAT_CHANNEL -> non-default mesh channel)"; }
  # Flash the Opta first — it's the deterministic, must-succeed step. Do NOT let a HAT
  # hiccup (jumpers/antenna) abort it under 'set -e'; HAT config warns and carries on.
  sudo "$HERE/opta_flash.sh" "$OPTA_OCTET"
  if ! with_hat sudo python3 "$HERE/hat_config.py" $CH_ARG; then
    echo "   WARNING: HAT config failed — check jumpers (UART-select=B, M0/M1 caps removed)," >&2
    echo "            HAT seating, and that it's on /dev/ttyAMA0. Opta flash already succeeded;" >&2
    echo "            re-run 'sudo python3 provision/hat_config.py' after fixing." >&2
  fi
}

phase_verify() {
  echo "== verify (kit $KIT: Pi $PI_IP, Opta $OPTA_IP) =="
  with_hat python3 "$HERE/hat_config.py" --read || echo "   (HAT read failed — check jumpers/seating)"
  sleep 6
  python3 "$REPO/scripts/mb_read.py" "$OPTA_IP" || echo "   (Opta not answering — check USB/Ethernet)"
}

PHASES="${*:-system serial net ssh service hw verify}"
for p in $PHASES; do "phase_$p"; done
echo "provision: kit $KIT, phases [$PHASES] complete."
