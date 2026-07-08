# Resume notes

Paused after **Phase 4**. The full scenario works end to end on the bench:
`mb_trip.py` → Opta trips (red lamp, meter→0) → SCADA-LTS operator view flips red/zero →
`mb_reset.py` recovers. Next up: **Phase 5** (RF listener).

## What persists (safe — nothing to do)

- **Repo:** all code/docs/scripts/assets on GitHub `main` (`Oofles/smart-meter-ics-lab`).
- **Opta program:** the sketch is in the board's flash — survives power-off.
- **SCADA config:** data source + 5 points + operator view live in the Docker named volumes
  `scada_db_data` / `scada_tomcat_log` — survive reboots and `docker compose up/down`.
- **Pi access:** the WSL SSH key is in the Pi's `authorized_keys`; passwordless sudo and
  Docker are installed. All persist.

## Lives ONLY on the laptop (bring it / don't wipe it)

- `opta/backup/opta_qspi_flash.bin` (16 MiB, **git-ignored**) — the QSPI half of the factory
  backup. The important half (internal flash) *is* in git; QSPI is laptop-only.
- WSL SSH **private** key `~/.ssh/id_ed25519` — needed to reach the Pi. (If the laptop
  changes, generate a new key and re-add the pubkey to the Pi.)
- Windows toolchain: `arduino-cli` + the sketch staging in `C:\Users\amazi\Documents\smart_meter`
  (source is in the repo, so re-creatable).

## Network change checklist (new site tomorrow)

Our config assumes the bench subnet **192.168.1.0/24** (Opta static `.210`, Pi was `.94`).
When the network differs, the network-dependent knobs are:

1. **Opta IP** — static `192.168.1.210` is hardcoded in `opta/smart_meter/smart_meter.ino`
   (`ip`/`dns`/`gateway`). Either keep the bench on `192.168.1.0/24` (isolated switch), or
   edit those and **re-flash** over USB from the laptop:
   `arduino-cli compile/upload --fqbn arduino:mbed_opta:opta -p COM4 opta/smart_meter`.
   Keep the Opta and Pi on the **same subnet**.
2. **Pi IP** — DHCP, will change. Find it (site router / Pi screen), then `ssh vivicat@<new-ip>`
   (key still works).
3. **SCADA data source host** — set to `192.168.1.210`; if the Opta IP changes, update it
   (Data Sources → *Opta Smart Meter* → host). Config persists, so only that field changes.
4. **Script defaults** — `scripts/mb.py` `DEFAULT_HOST=192.168.1.210`; pass a host arg
   (`python3 scripts/mb_read.py <ip>`) or edit the default.
5. **SCADA URL** — `http://<pi-ip>:8080/Scada-LTS` (login `admin/admin`, left intentionally).

## Resume point — Phase 5 (RF listener)

1. Enable the Pi serial for the SX1262 LoRa HAT (serial hardware on, login console off → clean
   `/dev/ttyAMA0`); reboot. 2. Detect the LoRa HAT + Sonoff Zigbee dongle. 3. Zigbee2MQTT +
   Mosquitto. 4. `listener/` service (pyserial + paho-mqtt) → benign heartbeat normally, and on
   a recognized malicious payload write `FW_MODE=1` (reuse `scripts/mb.py`). 5. Test locally
   (hand-published MQTT / canned LoRa frame) before wiring real RF.
