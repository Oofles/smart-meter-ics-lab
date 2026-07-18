# CLAUDE.md — smart-meter-ics-lab

Project memory for Claude Code. Read at the start of every session. Keep this file
high-signal: project overview, architecture, the interface contract, and the few
rules that are genuinely load-bearing. Detailed steps live in `PLAN.md`; the Modbus
contract lives in `docs/register-map.md`.

## What this is

A single-bench ICS security training rig that simulates a residential **smart meter**
and a **firmware-update-over-RF** attack path, for use in a hands-on cyber exercise.

- An **Arduino Opta PLC** runs a smart-meter simulation and serves **Modbus TCP**. Its
  **physical four-light panel** (blue/green/yellow/red) is the blue team's operator view —
  there is no software HMI.
- A **LoRa HAT** (Waveshare SX1262) on a **Raspberry Pi 5** (Pironman 5 case) is the simulated
  update channel; a listener on the Pi turns a received RF payload into a Modbus write against
  the Opta. A payload delivered over that channel is the exploited path in the scenario.
- The scenario outcome: the "malicious firmware update" flips the meter to a fault state —
  panel goes **red**, voltage/usage drop to **zero**.
- A **central/facilitator node** (Kit 00, Pi `.100` / Opta `.200`) aggregates every kit's
  status over RF and serves a fleet dashboard (see `central/`).

This is an isolated training lab on owned hardware. The "attack" is a Modbus register
write against a simulated meter — there is no real infrastructure and no weaponized code.

## Architecture (data flow)

```
[drone / 2nd LoRa node]  ----RF payload---->  [Pi: update listener]
                                                        | writes FW_MODE (Modbus)
                                                        v
[Opta PLC: smart-meter sim + Modbus TCP server]  ----> physical 4-light panel (operator view)
        drives POWER_STATUS / VOLTAGE / POWER_W
        field kits also beacon status over RF ----> [Kit 00 central node: collector + dashboard]
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
- `listener/` — field-kit Pi service: LoRa (serial) -> Modbus write; also **beacons kit status**
- `central/` — facilitator **fleet console**: `collector.py` (aggregates status beacons + local Kit 00 meter) + `fleet.html` live dashboard + `smartmeter-collector.service`
- `drone/`    — RF injection experiments (`beacon/` dead end, `rxsweep/` diagnostic — see `drone/README.md`)
- `provision/`— per-kit build: `provision.sh` (build one kit), `hat_config.py`, `opta_flash.sh`, `patch_ip.py`, `authorized_keys`
- `scripts/`  — test/helper scripts (Modbus poll, trip inject, reset)
- `docs/`     — `register-map.md` (contract), `architecture.md`

Kit replication (1 -> 45): **isolated islands, per-kit addressing, built one at a time** — see
`PROVISION.md`. Kit N -> Pi `192.168.1.(100+N)`, Opta `192.168.1.(200+N)`. **No golden image:**
on each kit, git clone the repo and run `sudo provision/provision.sh <N>` — it sets the Pi IP,
installs SSH keys, configures the HAT, installs the listener service pointed at **this kit's**
Opta, and flashes the Opta with its IP stamped into the firmware (one prebuilt `.bin` serves all
kits via a patchable `KITCFGv1` marker). RF is the cross-kit attack path; unique IPs mean the OT
switches *may* be bridged for management if wanted.

## Tech stack

- Opta: **Arduino sketch** (`arduino:mbed_opta` core + ArduinoModbus), Modbus TCP server,
  static IP, flashed over USB via `arduino-cli`. (The PLC IDE / IEC 61131-3 path was
  abandoned — its online link would not connect on this bench; see `opta/README.md`.)
- Pi 5: Raspberry Pi OS (64-bit / ARM64); no external services (no Docker).
- Listener / collector: Python 3 (pyserial + the dependency-free `scripts/mb.py` Modbus client).

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
- **Two meshes, split by channel.** The exercise fleet is on **channel 65 / 915.125 MHz**
  (GOLDEN, the `hat_config.py` default). The **DV walk-through demo** (Kits 43–45, a separate
  self-contained rig shown to visitors while the exercise runs) is on **channel 58 / 908.125 MHz**
  — a different centre frequency, so it's fully **PHY-isolated**: demo payloads can't reach the
  blue-team kits. The channel is the HAT's REG5 byte; `hat_config.py --channel N` (or
  `HAT_CHANNEL=` to `provision.sh`) sets it, default stays 65. Demo build + isolation-verify +
  run-book: **`DEMO.md`**; demo central/console setup: `provision/demo_central.sh`; re-channel/read
  a built node over SSH: `provision/demo_channel_update.sh`.
- **Planted weaknesses (deliberate — don't "fix" them):** the RF update channel is
  **unauthenticated** (anyone can forge a valid-looking `SMFW` frame — the exercise's core
  lesson), and SSH + a shared management key are baked into provisioning for the isolated lab.
  Don't ship either outside the lab.
- **Opta Modbus server wedges on an eth0 link bounce.** The sketch's ArduinoModbus TCP server is
  blocking single-client with no TCP keepalive, so if a Pi's eth0 IP changes / cable replugs / NM
  reactivates, the abandoned (no-FIN) connection keeps `client.connected()` true and the Opta stays
  stuck on the dead client — every new client then gets `RST` ("Connection reset by peer"). It does
  **not** self-heal; **reboot the Opta** (reflash over USB, or reset button) to clear it. A
  non-blocking server / keepalive is a firmware follow-up. (Bit us moving the central Pi `.11`→`.100`.)

## Status

- [x] Phase 1 — Opta smart-meter program + Modbus TCP server (Arduino **sketch**, not PLC IDE — see `opta/README.md`)
- [x] Phase 2 — Verify Modbus (read + trip + reset confirmed via `mbpoll` and `scripts/mb_*.py`; run from the Pi to reconfirm)
- [—] Phase 3–4 — **DESCOPED.** SCADA-LTS software operator view was built and working, then
  removed from scope: the blue team uses the Opta's **physical four-light panel** as the operator
  view. No software HMI, no Docker on the kits. (`scada/` deleted.)
- [x] Phase 5 — RF update listener + LoRa flood mesh: **built + validated over the air** (`listener/`).
  Real 2-kit trip proven (drone HAT → kit's listener → `FW_MODE` write → meter faults). Two attack
  modes (TEST / EXERCISE LOCK). **The 2nd node MUST be another EBYTE/Waveshare UART HAT** — a
  raw-SX1262 ESP32 (Heltec) drone is a **dead end** (see `drone/README.md`).
- [x] Phase 6 — End-to-end trip + reset over real RF (2-kit mesh test passed).
- [x] Central node — Kit 00 collector + fleet dashboard + RSSI range-map built (`central/`); drone
  data-mule for out-of-range kits done (`scripts/datamule.py` → "via mule" on the dashboard).
- [x] Drone / injection node — dedicated attacker build (`provision/drone.sh`: no Opta, no listener
  service). Bench drone = Pi 5 `.140`; OTA validated (trip + reset vs live kits over RF). Pi Zero backup
  builds the same way. Drone tooling: `--send --loop` execution mode, `scripts/rf_sniff.py` monitor,
  `scripts/datamule.py` store-and-forward mule, and `provision/drone_service.sh` (boot-armed
  autonomous payload via `smartmeter-drone.service` + `/etc/default/smartmeter-drone`).
- [ ] Replication — build out kits 1–45 per `PROVISION.md` (per-kit `provision.sh <N>`).
- [ ] DV demo — separate 3-kit rig (Kits 43–45) on an isolated mesh (**ch 58 / 908.125 MHz**) so
  it can't touch the live exercise (ch 65); Kit 43 = central + dashboard + RF console. Built out
  in `DEMO.md` (`HAT_CHANNEL=58 provision.sh`, `provision/demo_central.sh`,
  `provision/demo_channel_update.sh`); tooling landed, hardware build pending.

Update this checklist as work lands.
