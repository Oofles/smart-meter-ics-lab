# drone/ — RF injection experiments (Phase 5)

The exercise's RF attack path: a "drone" node transmits a malicious firmware-update
frame over LoRa; a meter's Pi hears it, writes `FW_MODE=1` over Modbus, and the meter
trips. The **receive + apply + flood-relay** side is done and lives in `listener/`
(`protocol.py`, `listener.py`), which runs on the Pi's **Waveshare SX1262 868M LoRa HAT**.

This directory holds the **transmit / drone-side** experiments.

## ⛔ Key finding: the drone must be another EBYTE/Waveshare HAT, not a raw SX1262

We tried to use a **Heltec WiFi LoRa 32 V4** (ESP32-S3 + **raw SX1262**, RadioLib) as the
drone, transmitting standard LoRa tuned to match the HAT. **It cannot work, and this is a
hardware-architecture limit, not a tuning problem.**

The Waveshare "SX1262 868M LoRa HAT" is an **EBYTE E22-900T (UART) module**: an SX1262 radio
sitting behind an **onboard microcontroller** running EBYTE's firmware. You never reach the
raw radio — you hand bytes to that MCU over UART, and it wraps them in **proprietary,
non-standard LoRa framing** that only interoperates with **other EBYTE modules**. A standard
RadioLib SX1262 speaks textbook LoRa, which the EBYTE firmware does not accept.

### What we measured (both directions, same bench, ~same antenna distance)

| Direction | PHY coverage | Result |
|-----------|--------------|--------|
| Heltec raw TX → HAT RX (`listener.py`) | full SF7–12 × BW{125,250,500} grid @ sync 0x12 | **0 bytes** |
| HAT TX → Heltec RX sweep (`rxsweep/`)  | SF7–12 × BW{125,250,500} × sync{0x12,0x34}, 133 TX frames | **0 locks** |

Zero *reception* (not garbled packets) in both directions = the receiver never even detected
a valid preamble+sync, i.e. the signals aren't mutually decodable at the PHY level.

Frequency was verified correct and is **not** the issue: Waveshare's channel formula is
`850.125 + CH×1MHz`; at the time of this test the HAT's channel register read `0x12` (18) →
**868.125 MHz**, which the Heltec matched exactly. (The lab has since moved to channel 65 /
915.125 MHz for US 902–928 ISM compliance; the dead-end conclusion is unaffected.)

This reproduces documented experience — see
[RadioLib Discussion #1612](https://github.com/jgromes/RadioLib/discussions/1612) (a raw SX1262
board vs an EBYTE E22-900T: swept the whole config, never worked; fix = use a matching EBYTE
device) and [RadioLib #467](https://github.com/jgromes/RadioLib/issues/467).

### The fix

Use a **second EBYTE/Waveshare SX1262 UART HAT** as the drone (any UART host: a 2nd Pi, or an
ESP32/Arduino wired to an EBYTE E22-**T** module — *not* a bare SX1262). EBYTE↔EBYTE transparent
mode is exactly what `listener/protocol.py` targets. Inject with `listener.py --send malicious`
from that node.

**Building the drone Pi:** run `sudo provision/drone.sh` on it (no Opta, no listener service —
see PROVISION.md "The drone / injection node"). The current bench drone is a Pi 5 at
`192.168.1.140`; a Pi Zero built the same way is the backup.

## Contents

- **`beacon/beacon.ino`** — the raw-SX1262 injector we *tried* (Heltec V4, RadioLib). Builds a
  benign/malicious SMFW frame and sweeps the PHY grid looking for a combo the HAT would hear.
  **Kept for the record; it does not and cannot deliver to the EBYTE HAT.** Do not spend more
  time on it.
- **`rxsweep/`** — the reverse-link diagnostic that produced the conclusion:
  - `rxsweep.ino` — Heltec RX-sweeps SF/BW×sync and reports any lock (OLED + USB serial).
  - `tx_beacon.py` — Pi-side helper: drives the HAT to transmit benign SMFW frames on a
    cadence so the sweep has a known signal to lock onto.

## Toolchain notes (Heltec V4)

Same Windows `arduino-cli` used for the Opta (WSL interop). Core `esp32:esp32` 3.3.x, libs
RadioLib + U8g2. FQBN `esp32:esp32:heltec_wifi_lora_32_V4`. Board enumerates on **COM7**.
The default build routes `Serial` to UART0 (invisible on USB) — build with
`:CDCOnBoot=cdc` to read status over USB. Stage the sketch to a Windows path before
`compile`/`upload` (the `.exe` can't read `\\wsl$` paths). Uploads occasionally throw a
transient RAM-checksum error — just retry.
