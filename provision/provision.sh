#!/usr/bin/env bash
# provision.sh — build ONE golden kit from a baseline Raspberry Pi OS (Bookworm, 64-bit).
# Run this once on the reference Pi, verify, then image its SD card and clone to the rest
# (clones only need provision/kit_init.sh — see PROVISION.md).
#
# Assumes: internet available; Waveshare SX1262 HAT seated; Opta connected by USB; Pi + Opta
# on the kit's switch. Run from the repo root:  sudo provision/provision.sh [phase]
# Phases (default runs all in order): system serial net scada service hw verify
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
PI_IP="192.168.1.94/24"; GW="192.168.1.1"

phase_system() {
  echo "== system: packages =="
  sudo apt-get update
  sudo apt-get install -y dfu-util python3-serial python3-lgpio git curl
  if ! command -v docker >/dev/null; then
    echo "== installing docker =="
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$RUN_USER"
  fi
}

phase_serial() {
  echo "== serial: enable UART hardware for the LoRa HAT, disable login console =="
  sudo raspi-config nonint do_serial_hw 0      # enable /dev/serial0 hardware
  sudo raspi-config nonint do_serial_cons 1    # disable serial login shell
  echo "   (a reboot is needed for the UART change to take effect)"
}

phase_net() {
  echo "== net: static IP $PI_IP on the wired connection =="
  local CON; CON="$(nmcli -t -f NAME,TYPE con show | awk -F: '$2=="802-3-ethernet"{print $1; exit}')"
  [ -n "${CON:-}" ] || { echo "   no wired NM connection found — set static IP manually"; return; }
  sudo nmcli con mod "$CON" ipv4.addresses "$PI_IP" ipv4.gateway "$GW" ipv4.method manual
  sudo nmcli con up "$CON" || true
}

phase_scada() {
  echo "== scada: bring up SCADA-LTS + import config (first boot builds the DB, ~5 min) =="
  ( cd "$REPO/scada" && docker compose up -d )
  echo "   waiting for SCADA-LTS to answer..."
  for _ in $(seq 1 60); do
    curl -s -o /dev/null "http://127.0.0.1:8080/Scada-LTS/login.htm" && break
    sleep 10
  done
  SCADA_URL="http://127.0.0.1:8080/Scada-LTS" python3 "$REPO/scada/emport.py" import "$REPO/scada/emport-config.json" || \
    echo "   (emport import failed — run it manually once SCADA is fully up)"
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
ExecStart=/usr/bin/python3 $REPO/listener/listener.py
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
  echo "== hardware: configure this HAT + flash this Opta =="
  sudo python3 "$HERE/hat_config.py"
  sudo "$HERE/opta_flash.sh"
}

phase_verify() {
  echo "== verify =="
  python3 "$HERE/hat_config.py" --read
  sleep 6
  python3 "$REPO/scripts/mb_read.py" || echo "   (Opta not answering — check USB/Ethernet)"
}

PHASES="${*:-system serial net scada service hw verify}"
for p in $PHASES; do "phase_$p"; done
echo "provision: phases [$PHASES] complete."
