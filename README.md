# smart-meter-ics-lab

A single-bench ICS security training rig: an Arduino Opta PLC simulates a residential
**smart meter** and serves Modbus TCP; a Raspberry Pi 5 hosts a **SCADA-LTS** operator
view (green/red power indicator + live voltage/usage meter); a LoRa update channel on
the Pi is the simulated, exploited **firmware-update-over-RF** path. The
scenario outcome: a "malicious firmware update" trips the meter to a fault state —
indicator red, voltage/usage to zero.

Built for a hands-on cyber exercise. Isolated lab, owned hardware; the "attack" is a
Modbus register write against a simulated meter — no real infrastructure, no weaponized
code.

## Components

- **Opta PLC** — smart-meter simulation, Modbus TCP server, HMI board (+ optional buzzer)
- **Raspberry Pi 5** (Pironman 5) — hosts SCADA-LTS + the RF update listener
- **Waveshare SX1262 868M LoRa HAT** (UART) — the RF update channel

## Layout

| Path         | Contents                                                          |
|--------------|------------------------------------------------------------------|
| `opta/`      | Opta smart-meter Arduino sketch + factory-firmware backup        |
| `scada/`     | SCADA-LTS docker-compose (ARM64) + exported view/datasource      |
| `listener/`  | Pi-side LoRa update listener -> Modbus write                     |
| `scripts/`   | Modbus poll / trip / reset helpers                               |
| `docs/`      | `register-map.md` (the contract), `architecture.md`              |
| `CLAUDE.md`  | Claude Code project memory                                       |
| `PLAN.md`    | Phased implementation plan                                       |

## Start here

1. Read `docs/register-map.md` — the Modbus contract everything builds against.
2. Follow `PLAN.md` phase by phase (Opta first; nothing validates until it serves Modbus).
3. `CLAUDE.md` carries the context and gotchas into each Claude Code session.

## Data flow

```
[2nd LoRa node] --------RF payload--------> [Pi: update listener]
                                                     | writes FW_MODE (Modbus)
                                                     v
[Opta: smart-meter sim + Modbus TCP] <-- polls -- [Pi: SCADA-LTS view]
      drives POWER_STATUS/VOLTAGE/POWER_W           green light + meter
```
