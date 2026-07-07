# Implementation Plan

Phased build for the smart-meter ICS training rig. Each phase is a natural commit/PR
boundary. Build in order — later phases read from earlier ones. The Modbus contract in
`docs/register-map.md` is fixed first and everything builds against it.

## Phase 1 — Opta smart-meter program

Author in the Arduino PLC IDE (Windows) on the Opta. Implement the behavior logic in
`docs/register-map.md`, enable the **Modbus TCP server**, set the static IP, and expose
POWER_STATUS, VOLTAGE_X10, POWER_W, FW_MODE, RESET. Wire the HMI board so the green/red
state can also show physically. Optionally sound the buzzer on fault.

- Deliverable: versioned Opta project in `opta/` + a short `opta/README.md` documenting
  the IP, unit ID, and how to flash.
- Done when: the Opta serves Modbus and normal-state values look alive.

## Phase 2 — Verify Modbus from the Pi

Before SCADA touches anything, confirm the data from the Pi:

```
mbpoll -m tcp -a 1 -r 1 -c 2 192.168.1.10        # read holding regs
# or a short pymodbus script in scripts/
```

Read voltage/watts, flip FW_MODE, confirm the Opta trips and RESET clears it. This
isolates "is the PLC right" from "is SCADA configured right."

- Deliverable: `scripts/mb_read.py`, `scripts/mb_trip.py`, `scripts/mb_reset.py`.
- Done when: you can read live values and trip/reset over Modbus by hand.

## Phase 3 — SCADA-LTS on the Pi

Deploy via Docker Compose (services: database + scadalts, image `scadalts/scadalts`).

- **ARM64 first:** the stock compose pins `mysql-server:5.7` (no clean arm64 build).
  Swap for an arm64 MariaDB / MySQL 8 or emulate, and pin an arm64 `scadalts` tag.
  Persist volumes. Change the default admin/admin login.
- Add a **Modbus IP data source** pointing at the Opta; create data points for
  POWER_STATUS, VOLTAGE_X10, POWER_W.

- Deliverable: `scada/docker-compose.yml` (+ any DB init), notes in `scada/README.md`,
  exported data source/point config once built.
- Done when: SCADA-LTS shows live point values matching the Opta.

## Phase 4 — Graphical view (the operator page)

Build the view SCADA-LTS hosts:

- Binary/multistate image bound to POWER_STATUS: green PNG at 1, red PNG at 0.
- Analog readout / dynamic-graphic bar bound to VOLTAGE_X10 (render /10) for the meter;
  optionally POWER_W too.
- Poll ~1 s so the gauge moves in normal state and collapses on trip.

- Deliverable: exported graphical view in `scada/`, image assets, `scada/README.md` steps.
- Done when: the normal-state demo works end to end (green + moving meter).

## Phase 5 — RF update listener

One Pi-side service listening on both transports; on a recognized malicious update it
writes `FW_MODE = 1` via Modbus. Benign updates/heartbeats write 0 (or no-op).

- LoRa: read the SX1262 HAT on `/dev/ttyAMA0` (enable serial hardware, disable login shell).
- Zigbee: Sonoff dongle -> Zigbee2MQTT -> subscribe to the topic.
- Optionally give the payload a firmware-like shape (magic bytes, version header,
  checksum the listener "validates") to sharpen the integrity lesson.

- Deliverable: `listener/` service (Python: pymodbus, pyserial, paho-mqtt), config,
  `listener/README.md`.
- Done when: injecting a malicious payload flips SCADA to red and zero.

## Phase 6 — End-to-end trip + reset, then real RF

- Bind RESET to a button/script to re-arm between runs.
- Solo testing: inject the payload locally first (hand-publish MQTT / canned LoRa frame)
  to prove the chain, then wire real over-the-air delivery with a second LoRa node /
  Zigbee source.

- Done when: the full normal -> attack -> reset loop runs on demand.

## Out of scope (for now)

- Fleet replication to the other exercise kits (handled separately).
- Physical enclosure/mounting (Pironman 5 already handles the Pi).
