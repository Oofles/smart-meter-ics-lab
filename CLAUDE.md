# CLAUDE.md — smart-meter-ics-lab

Project memory for Claude Code. Read at the start of every session. Keep this file
high-signal: project overview, architecture, the interface contract, and the few
rules that are genuinely load-bearing. Detailed steps live in `PLAN.md`; the Modbus
contract lives in `docs/register-map.md`.

## What this is

A single-bench ICS security training rig that simulates a residential **smart meter**
and a **firmware-update-over-RF** attack path, for use in a hands-on cyber exercise.

- An **Arduino Opta PLC** runs a smart-meter simulation and serves **Modbus TCP**.
- A **Raspberry Pi 5** (Pironman 5 case) hosts **SCADA-LTS**, which polls the Opta and
  renders an operator view: a green/red power indicator and a live voltage/usage meter.
- A **LoRa HAT** (Waveshare SX1262) and a **Zigbee USB coordinator** (Sonoff ZBDongle-P)
  on the Pi are the simulated update channel. A payload delivered over that channel is
  the exploited path in the scenario.
- The scenario outcome: the "malicious firmware update" flips the meter to a fault
  state — indicator goes **red**, voltage/usage drop to **zero**.

This is an isolated training lab on owned hardware. The "attack" is a Modbus register
write against a simulated meter — there is no real infrastructure and no weaponized code.

## Architecture (data flow)

```
[2nd LoRa node / Zigbee device]  --RF payload-->  [Pi: update listener]
                                                        | writes FW_MODE (Modbus)
                                                        v
[Opta PLC: smart-meter sim + Modbus TCP server]  <---- polls ----  [Pi: SCADA-LTS view]
        ^ drives POWER_STATUS / VOLTAGE / POWER_W                   green light + meter
```

## The contract (source of truth: `docs/register-map.md`)

All four subsystems build against this Modbus map. Do not change addresses without
updating `docs/register-map.md` and every consumer.

| Type | Addr  | Name         | Meaning                                   | Writer   |
|------|-------|--------------|-------------------------------------------|----------|
| Coil | 00001 | POWER_STATUS | 1=powered(green) 0=fault(red)             | Opta     |
| HReg | 40001 | VOLTAGE_X10  | volts x10 (1200 = 120.0 V)                | Opta     |
| HReg | 40002 | POWER_W      | instantaneous watts                       | Opta     |
| HReg | 40010 | FW_MODE      | 0=normal 1=malicious ("updated firmware") | listener |
| Coil | 00016 | RESET        | write 1 to clear fault back to normal     | ops      |

Opta logic: `FW_MODE==0` -> POWER_STATUS=1, VOLTAGE_X10≈1200 w/ jitter, POWER_W random-walk.
`FW_MODE==1` -> POWER_STATUS=0, VOLTAGE_X10=0, POWER_W=0. `RESET`=1 -> FW_MODE=0.

## Repo layout

- `opta/`     — Opta smart-meter Arduino sketch (`smart_meter/`) + factory-firmware backup (`backup/`)
- `scada/`    — SCADA-LTS deployment (docker-compose, ARM64-adjusted) + exported view/datasource config
- `listener/` — Pi-side update service: LoRa (serial) + Zigbee (MQTT) -> Modbus write
- `scripts/`  — test/helper scripts (Modbus poll, trip inject, reset)
- `docs/`     — `register-map.md` (contract), `architecture.md`

## Tech stack

- Opta: **Arduino sketch** (`arduino:mbed_opta` core + ArduinoModbus), Modbus TCP server,
  static IP, flashed over USB via `arduino-cli`. (The PLC IDE / IEC 61131-3 path was
  abandoned — its online link would not connect on this bench; see `opta/README.md`.)
- Pi 5: Raspberry Pi OS (64-bit / ARM64), Docker + Docker Compose.
- SCADA-LTS: `scadalts/scadalts` image + a database container (see ARM64 note below).
- Listener: Python 3 (pymodbus, pyserial, paho-mqtt), Zigbee2MQTT + Mosquitto.

## Rules

- **IMPORTANT: model "modified firmware" as the `FW_MODE` register, not a real reflash.**
  The Opta has no OTA path over LoRa/Zigbee; the radios are on the Pi. The update
  listener writes `FW_MODE` to change Opta behavior. Never attempt to reflash the Opta
  over RF — it is unreliable and defeats the demo.
- Treat `docs/register-map.md` as the single source of truth. Any addressing change
  updates that file and all consumers in the same commit.
- Keep normal-state RF traffic benign-but-present (e.g., a version heartbeat) so the
  exercise teaches "the channel is unauthenticated," not "any traffic is malicious."
- Prefer Opta-side trip logic (via `FW_MODE`) over the Pi writing data registers
  directly, so a direct-Modbus attacker can also trigger the fault.
- Commit small and phase-by-phase; each phase in `PLAN.md` is a natural PR boundary.

## Environment notes / gotchas

- **ARM64 database (resolved):** current `scadalts/scadalts` and `mysql/mysql-server:8.0.32`
  are **native multi-arch (arm64)** — no emulation, no MySQL-5.7 workaround. `scada/`
  pins those tags and runs natively on the Pi 5. (The old "budget time here" worry is moot.)
- **Serial for LoRa:** enable the serial hardware and disable the login shell so the
  SX1262 HAT gets a clean `/dev/ttyAMA0` on the Pi 5.
- **Zigbee is USB, not GPIO** — the LoRa HAT owns the GPIO/UART pins.
- **Solo testing:** full over-the-air delivery needs a second LoRa node / Zigbee source.
  Until then, validate the trip chain by injecting the payload locally (publish the MQTT
  message by hand, or feed the LoRa parser a canned frame), then wire real RF last.
- SCADA-LTS default login is admin/admin — change it.

## Status

- [x] Phase 1 — Opta smart-meter program + Modbus TCP server (Arduino **sketch**, not PLC IDE — see `opta/README.md`)
- [x] Phase 2 — Verify Modbus (read + trip + reset confirmed via `mbpoll` and `scripts/mb_*.py`; run from the Pi to reconfirm)
- [x] Phase 3 — SCADA-LTS on the Pi (Docker, native arm64) + Modbus data source (5 points, verified vs `mb_read.py`; attack→reset reflected in SCADA)
- [ ] Phase 4 — Graphical view: green/red indicator + voltage meter (data points live; graphic/images remain)
- [ ] Phase 5 — RF update listener (LoRa serial + Zigbee MQTT) -> FW_MODE write
- [ ] Phase 6 — End-to-end trip + reset, then real RF delivery

Update this checklist as phases land.
