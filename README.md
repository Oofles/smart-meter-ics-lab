# smart-meter-ics-lab

A single-bench ICS security training rig: an Arduino Opta PLC simulates a residential
**smart meter**, serves Modbus TCP, and shows meter state on a **physical four-light panel**
(the blue team's operator view); a LoRa update channel on a Raspberry Pi 5 is the simulated,
exploited **firmware-update-over-RF** path. The scenario outcome: a "malicious firmware update"
trips the meter to a fault state — panel red, voltage/usage to zero.

Built for a hands-on cyber exercise. Isolated lab, owned hardware; the "attack" is a
Modbus register write against a simulated meter — no real infrastructure, no weaponized
code.

## Components

- **Opta PLC** — smart-meter simulation, Modbus TCP server, four-light HMI panel
- **Raspberry Pi 5** (Pironman 5) — hosts the RF update listener; the central node (Kit 00)
  also runs the fleet collector + dashboard
- **Waveshare SX1262 868M LoRa HAT** (UART) — the RF update channel

## Layout

| Path         | Contents                                                          |
|--------------|------------------------------------------------------------------|
| `opta/`      | Opta smart-meter Arduino sketch + factory-firmware backup        |
| `listener/`  | Pi-side LoRa update listener -> Modbus write; beacons kit status |
| `central/`   | Kit 00 fleet collector + live dashboard + service unit           |
| `provision/` | Per-kit build (`provision.sh <N>`) + HAT/Opta flash helpers      |
| `scripts/`   | Modbus poll / trip / reset helpers                               |
| `docs/`      | `register-map.md` (the contract), `architecture.md`              |
| `CLAUDE.md`  | Claude Code project memory                                       |
| `PLAN.md`    | Phased implementation plan                                       |
| `BOM.md`     | Bill of materials — what to buy to build your own                |

## Start here

0. Building your own? `BOM.md` lists the hardware (and what's substitutable).
1. Read `docs/register-map.md` — the Modbus contract everything builds against.
2. Follow `PLAN.md` phase by phase (Opta first; nothing validates until it serves Modbus).
3. `CLAUDE.md` carries the context and gotchas into each Claude Code session.

## Data flow

```
[drone / 2nd LoRa node]
    |
    |  RF payload (LoRa)
    v
[Pi: update listener] --writes FW_MODE (Modbus)--> [Opta: smart-meter sim + Modbus TCP]
    |                                                  |
    |  beacons kit status (RF)                         |  drives POWER_STATUS / VOLTAGE / POWER_W
    v                                                  v
[Kit 00: collector + fleet dashboard]              [physical 4-light panel (operator view)]
```
