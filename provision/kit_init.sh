#!/usr/bin/env bash
# kit_init.sh <kit-number> — per-clone initializer. Run on a kit booted from the GOLDEN image.
#
# The golden image already carries the Pi software (SCADA-LTS + config, listener service, SSH
# server, UART enabled). This applies the per-kit bits: the kit's own IP + SSH keys, this HAT's
# NVM config, and this Opta's firmware — then verifies. ~1-2 min per kit.
#
#   sudo provision/kit_init.sh 9      # kit 9 -> Pi 192.168.1.109, HAT + Opta flashed, verified
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
KIT="${1:?usage: sudo provision/kit_init.sh <kit-number>}"
exec sudo "$HERE/provision.sh" "$KIT" net ssh hw verify
