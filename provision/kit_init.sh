#!/usr/bin/env bash
# kit_init.sh — per-clone initializer. Run on a kit that booted from the GOLDEN SD image.
#
# The golden image already carries the Pi software (SCADA-LTS + config, listener service,
# static IP, UART enabled). Two things live in the physical hardware, NOT on the SD, so they
# must be done on every kit: (1) the HAT's own NVM config, (2) the Opta's firmware. This does
# both, then verifies. ~1-2 minutes per kit.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "==> [1/3] configure this kit's LoRa HAT"
sudo python3 "$HERE/hat_config.py"

echo "==> [2/3] flash this kit's Opta"
sudo "$HERE/opta_flash.sh"

echo "==> [3/3] verify (give the Opta ~8s to boot + bring up Ethernet)"
sleep 8
python3 "$HERE/../scripts/mb_read.py" || echo "  (Opta not answering yet — check USB/Ethernet, re-run mb_read.py)"
echo "==> kit_init done."
