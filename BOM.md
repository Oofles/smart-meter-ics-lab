# BOM.md — Bill of Materials

What to buy to build your own copy of this lab. One **field kit** is the unit of
replication (build steps: `PROVISION.md`); a minimal working lab is **two kits' worth of
radio** — one victim kit plus a **drone** (attacker node) — since the whole point is a
payload crossing the air gap. Add a **central node** (Kit 00) if you want the fleet
dashboard, and more field kits to taste.

Prices are rough 2026-USD ballparks — check current listings. Nothing here is exotic;
the only part you must NOT substitute is the radio (see
[Alternatives](#alternatives--substitutions)).

## One field kit (victim meter)

| Qty | Item | Purpose | Notes / approx. price |
|-----|------|---------|------------------------|
| 1 | **Arduino Opta PLC** — easiest as the [PLC Cables Inc. Opta PLC Trainer Kit](https://www.plccable.com/arduino-ide-opta/) | The simulated smart meter: runs the sketch, serves Modbus TCP, drives the four-light panel | The trainer kit bundles the Opta with the I/O panel this repo is wired for — 4 lamps, 2 toggle switches, reset button, 0–10 V dial — plus 24 V supply and USB cable. The Ethernet-only kit ([AFX00003 base](https://www.plccable.com/arduino-ide-opta-kit-plc-trainer-pro-industrial-iot-ethernet-afx00003/)) is enough; the [WiFi/RS485 variant](https://www.plccable.com/arduino-ide-opta-plc-trainer-pro-industrial-iot-ethernet-wifi-485-starter-kit-afx00002-t/) works but nothing here uses WiFi or RS485. See price on their site (bare Opta alone runs ~$115–170) |
| 1 | **Raspberry Pi 5** | Hosts the RF update listener (LoRa → Modbus bridge) + status beacon | Any RAM size — the workload is two small Python services; 2–4 GB is plenty. ~$50–80 |
| 1 | **Waveshare SX1262 LoRa HAT** (UART, EBYTE E22-900T-based) | The RF "firmware update" channel | ~$25–35. The **868M** and **915M** variants both tune 850.125–930.125 MHz via the channel byte; this lab runs 915.125 MHz (US ISM). Antenna included. Jumpers: UART-select **B**, M0/M1 caps removed (`PROVISION.md`) |
| 1 | microSD card, 16 GB+ | Pi boot disk (Raspberry Pi OS 64-bit) | ~$10 |
| 1 | USB-C power supply, 27 W | Pi 5 power | ~$12; the official PSU avoids undervoltage nags |
| 1 | 5-port unmanaged Ethernet switch | The kit's isolated OT LAN (Pi + Opta + a spot for the operator/facilitator laptop) | ~$15. Any unmanaged switch; kits are isolated islands, no uplink |
| 2 | Cat5e/6 patch cables | Pi → switch, Opta → switch | ~$5 |
| 1 | USB-A → USB-C cable | Pi → Opta: flashing (`opta_flash.sh` via dfu-util) and powers the Opta's logic | Included with the trainer kit |
| 1 | 12–24 V DC supply for the Opta relays | The four panel lamps switch on this supply (logic runs fine on USB alone) | Included with the trainer kit |
| — | *(optional)* Pironman 5 case | Enclosure/cooling for the Pi | ~$70–80, cosmetic — any case that leaves the GPIO header reachable for the HAT works |

## Central / facilitator node (Kit 00)

Identical hardware to a field kit (its own Opta included — Kit 00 doubles as a live meter),
plus:

| Qty | Item | Purpose | Notes |
|-----|------|---------|-------|
| 1 | *(optional)* 4-key USB macropad | Physical trigger keys for the RF console (TEST / LOCK / reset / heartbeat) | Any generic USB-HID macropad; `central/keypad.py --learn` binds whatever keycodes it emits (~$15–25) |

The only config difference is the HAT's RSSI-append bit (`hat_config.py --rssi`) — same part.

## Drone (attacker / injection node)

| Qty | Item | Purpose | Notes |
|-----|------|---------|-------|
| 1 | Raspberry Pi — any model with the 40-pin header | Runs the injection tooling (`drone.sh` build: no Opta, no listener) | Bench drone is a Pi 5; an original **Pi Zero W** is the proven backup (flash 32-bit ARMv6 OS). ~$15–80 |
| 1 | **2nd Waveshare SX1262 LoRa HAT** — same model as the kits | Transmits the forged `SMFW` payload | **Must be the same EBYTE-family UART HAT.** See the warning below |
| 1 | *(optional)* USB power bank | Untethered walking-around range tests / data-mule runs | Any 5 V bank |

> **⚠ The one part you can't substitute:** the Waveshare HAT is an EBYTE E22-900T module —
> an SX1262 behind an onboard MCU speaking **proprietary framing** that only interoperates
> with other EBYTE modules. A raw-SX1262 board (Heltec WiFi LoRa 32, generic RadioLib
> node, ...) receives **nothing** in either direction regardless of SF/BW/sync settings —
> tested exhaustively, see `drone/README.md`. Every radio in the mesh must be this HAT
> family.

## Site / bench extras

- Management laptop with an Ethernet port (static `192.168.1.50/24` — see
  `docs/kit-fieldcheck-card.md`) for provisioning and field checks.
- A spare microSD and a spare HAT antenna per ~10 kits saves a bad day.

## Alternatives & substitutions

- **Pi → any mini PC / SBC.** Nothing depends on Pi silicon — the listener and collector
  are plain Python 3 + pyserial. The HAT even works without GPIO: set its UART-select
  jumper to **A** and it enumerates over its own USB port (onboard CP2102), so any small
  x86 box (NUC, thin client, N100 mini PC) can drive it. You lose the `provision/`
  automation (`provision.sh` and `hat_config.py` assume Raspberry Pi OS and
  `/dev/ttyAMA0`), so plan on hand-configuring: point `listener/lora.py` at your serial
  device and install the systemd units manually.
- **Pi 5 → older Pi.** A Pi 4, 3B+, or Zero 2 W handles the listener easily; the Zero W
  (ARMv6) is proven as a drone. The Pi 5 choice was inventory, not requirement.
- **Opta variant.** Any Opta (Lite / WiFi / RS485) — the lab uses only Ethernet and the
  base I/O, present on all three.
- **Trainer kit → DIY panel.** The PLC Cables trainer is a convenience, not a dependency.
  Equivalent: bare Opta + 4× 12–24 V panel indicator lamps on relay outputs O1–O4,
  2 toggle switches (I1/I2), 1 momentary button (I3), and a potentiometer wired as a
  0–10 V dial (I5), per the pin table in `opta/README.md`.
- **Opta → other Modbus TCP PLC.** Possible but real work: `opta/smart_meter/` is an
  Arduino sketch, so a different PLC means reimplementing the meter logic against the
  register map in `docs/register-map.md`. Everything Pi-side only speaks Modbus TCP and
  would carry over unchanged.
- **Ethernet switch.** Anything unmanaged. Per-kit unique IPs (`PROVISION.md`) mean you
  *may* bridge kits into one management LAN, so a bigger shared switch also works.
- **Radio.** No. See the warning above — EBYTE-family UART HAT on every node, full stop.
- **Frequency / region.** US builds: either HAT variant, keep the default channel 65
  (915.125 MHz, US ISM). EU builds: use channels that land in 863–870 MHz (channel byte =
  MHz − 850.125) and mind duty-cycle rules. It's a transmitter — know your local
  regulations.

## Ballpark totals

- **Minimal lab** (1 field kit + Pi Zero drone): trainer kit + ~$150–200 of everything else.
- **Field kit** (each additional): trainer kit + ~$120–160.
- **Central node**: same as a field kit (+ macropad if wanted).
