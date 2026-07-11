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
- A **LoRa HAT** (Waveshare SX1262) on the Pi is the simulated update channel. A payload
  delivered over that channel is the exploited path in the scenario.
- The scenario outcome: the "malicious firmware update" flips the meter to a fault
  state — indicator goes **red**, voltage/usage drop to **zero**.

This is an isolated training lab on owned hardware. The "attack" is a Modbus register
write against a simulated meter — there is no real infrastructure and no weaponized code.

## Architecture (data flow)

```
[2nd LoRa node]  --------RF payload-------->  [Pi: update listener]
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
| Coil | 00001 | POWER_STATUS | 1=powered/healthy 0=faulted(attack)       | Opta     |
| HReg | 40001 | VOLTAGE_X10  | volts x10 (1200 = 120.0 V), dial-driven   | Opta     |
| HReg | 40002 | POWER_W      | instantaneous watts                       | Opta     |
| HReg | 40010 | FW_MODE      | 0=normal, 1=malicious TEST, 2=malicious LOCK | listener |
| Coil | 00016 | RESET        | 1 clears a TEST trip; ignored when FW_MODE=2 | ops      |
| DIn  | 10001 | LAMP_B/G/Y/R | O1..O4 lamp states (mirror, DIn 0..3)     | Opta     |
| DIn  | 10005 | SW_BLUE/GREEN| I1/I2 switch positions (mirror, DIn 4..5) | Opta     |

Opta logic — the panel is an **operator HMI** (blue team's Day-1 setup task). `FW_MODE==0`
(normal): POWER_STATUS=1, VOLTAGE_X10 dial-driven w/ jitter, POWER_W random-walk; lamps
**O1 blue=I1 switch, O2 green=I2 switch, O3 yellow=dial≥6(of 0–10), O4 red=off**. `FW_MODE!=0`
(malicious update, via Modbus/RF payload — **no local trip switch**): POWER_STATUS=0,
VOLTAGE_X10=0, POWER_W=0, **O1/O2/O3 off, O4 red on**. Two attack modes: **FW_MODE=1 TEST** — `RESET`
(coil or I3) clears it; **FW_MODE=2 EXERCISE LOCK** — operator RESET ignored, cleared **only** by a
direct `FW_MODE:=0` write (facilitator "re-flash", `scripts/mb_unlock.py`). Drone selects mode via
`listener.py --send malicious [--exercise]`. (LOCK is RAM-only for now — a power-cycle clears it too;
flash-persistence across reboots is a planned follow-up: `Arduino_KVStore` hard-faults on the H7, so
use a reserved internal-flash sector via `FlashIAP`, bench-tested first.)

## Repo layout

- `opta/`     — Opta smart-meter Arduino sketch (`smart_meter/`) + prebuilt firmware (`firmware/`) + factory backup (`backup/`)
- `scada/`    — SCADA-LTS deployment (docker-compose, ARM64) + `emport-config.json` + `emport.py` (headless Emport)
- `listener/` — field-kit Pi service: LoRa (serial) -> Modbus write; also **beacons kit status**
- `central/` — facilitator **fleet console**: `collector.py` (aggregates status beacons + local Kit 00 meter) + `fleet.html` live dashboard
- `drone/`    — RF injection experiments (`beacon/` dead end, `rxsweep/` diagnostic — see `drone/README.md`)
- `provision/`— kit build/replication: `provision.sh` (golden kit), `kit_init.sh` (per clone), `hat_config.py`, `opta_flash.sh`
- `scripts/`  — test/helper scripts (Modbus poll, trip inject, reset)
- `docs/`     — `register-map.md` (contract), `architecture.md`

Kit replication (1 -> 45): **isolated islands, per-kit addressing** — see `PROVISION.md`. Kit N
-> Pi `192.168.1.(100+N)`, Opta `192.168.1.(200+N)`. Golden SD image + per-clone
`sudo provision/kit_init.sh <N>` (Pi IP, SSH keys, HAT config, and flashes the Opta with its IP
stamped into the firmware — one prebuilt `.bin` serves all kits via a patchable `KITCFGv1`
marker; SCADA + listener are pointed at the kit's Opta IP too). RF is the cross-kit attack path;
unique IPs mean the OT switches *may* be bridged for management if wanted.

## Tech stack

- Opta: **Arduino sketch** (`arduino:mbed_opta` core + ArduinoModbus), Modbus TCP server,
  static IP, flashed over USB via `arduino-cli`. (The PLC IDE / IEC 61131-3 path was
  abandoned — its online link would not connect on this bench; see `opta/README.md`.)
- Pi 5: Raspberry Pi OS (64-bit / ARM64), Docker + Docker Compose.
- SCADA-LTS: `scadalts/scadalts` image + a database container (see ARM64 note below).
- Listener: Python 3 (pyserial + the dependency-free `scripts/mb.py` Modbus client).

## Rules

- **IMPORTANT: model "modified firmware" as the `FW_MODE` register, not a real reflash.**
  The Opta has no OTA path over LoRa; the radio is on the Pi. The update
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
  SX1262 HAT gets a clean `/dev/ttyAMA0` on the Pi 5. **Address `/dev/ttyAMA0` directly, not
  `/dev/serial0`.** On Bookworm `serial0`→`ttyAMA0` (the RP1 header UART), but on **Debian 13
  (trixie)** `serial0`→`ttyAMA10`, which is the **Bluetooth** SoC UART — talking to it reaches
  nothing (silent HAT). `ttyAMA0` is the GPIO14/15 header UART on both OSes; `listener/lora.py`
  and `provision/hat_config.py` use it. (Bit us on kit 9 — trixie image; diagnosed via `dmesg`
  UART MMIO map + a config-mode probe against a known-good Bookworm kit.)
- **Solo testing:** full over-the-air delivery needs a second LoRa node. Until then,
  validate the trip chain by feeding the listener a canned frame (`listener.py --simulate`),
  then wire real RF last.
- **The RF drone must be a 2nd EBYTE/Waveshare UART HAT — NOT a raw SX1262 radio.** The
  Waveshare "SX1262 868M LoRa HAT" is an EBYTE E22-900T module: an SX1262 behind an onboard
  MCU that speaks proprietary (non-standard) LoRa framing and only interoperates with other
  EBYTE modules. A Heltec WiFi LoRa 32 V4 (raw SX1262 + RadioLib) was tested both directions
  across the full SF/BW×sync grid → **0 reception**; this matches documented experience
  (RadioLib #1612) and is unfixable by any PHY setting. Full write-up + the diagnostic sketch:
  `drone/README.md` and `drone/rxsweep/`.
- SCADA-LTS login is **intentionally left `admin/admin`** for this exercise — a planted
  default-credential weakness for the defenders to discover and flag. (Change it only if this
  rig ever leaves the isolated lab.)

## Status

- [x] Phase 1 — Opta smart-meter program + Modbus TCP server (Arduino **sketch**, not PLC IDE — see `opta/README.md`)
- [x] Phase 2 — Verify Modbus (read + trip + reset confirmed via `mbpoll` and `scripts/mb_*.py`; run from the Pi to reconfirm)
- [x] Phase 3 — SCADA-LTS on the Pi (Docker, native arm64) + Modbus data source (5 points, verified vs `mb_read.py`; attack→reset reflected in SCADA)
- [x] Phase 4 — Graphical operator view (green/red indicator + voltage gauge + usage); attack/reset reflected live in SCADA
- [~] Phase 5 — RF update listener: **LoRa half built + validated** (`listener/`: SX1262 868M UART HAT alive + TX on the Pi; malicious frame → `FW_MODE=1` trip proven via `--simulate`). Remaining: real over-the-air. **The 2nd node MUST be another EBYTE/Waveshare UART HAT** — a raw-SX1262 ESP32 (Heltec) drone was tried and is a **dead end** (see `drone/README.md`)
- [ ] Phase 6 — End-to-end trip + reset, then real RF delivery

Update this checklist as phases land.
