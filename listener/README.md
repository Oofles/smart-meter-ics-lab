# listener/ — RF update listener (Phase 5)

Pi-side service that turns a malicious "firmware update" received over the RF
channel into a `FW_MODE=1` Modbus write on the Opta — the exercise's attack path.
The Modbus write is identical to `scripts/mb_trip.py`; this just adds the radio.

## Hardware (validated)

Waveshare **SX1262 868M LoRa HAT** — a **UART** module (EBYTE-style), not SPI.

- Serial: `/dev/serial0` (= `/dev/ttyAMA0` on Pi 5) @ **9600 8N1**.
- Mode pins: **M0 = BCM22, M1 = BCM27** on **gpiochip0** (RP1), driven via `lgpio`.
- Board jumpers: **UART-select = B**, **M0/M1 caps removed**.
- Pi serial prep: `enable_uart=1`, serial login console **off** (getty masked).
- Deps (already on the Pi, no internet needed): `pyserial`, `lgpio`. Modbus is our
  dependency-free `scripts/mb.py`.

## Protocol (`protocol.py`)

8-byte firmware-shaped frame: `b"SMFW" | version | type | crc16`. `type` is
`0x00` benign (version heartbeat) or `0x01` malicious. The listener "validates"
the CRC — but the channel is unauthenticated, which is the lesson.

## Run it

```
./listener.py                       # listen on LoRa, act on received frames
./listener.py --simulate malicious  # NO radio: canned frame -> FW_MODE=1 (proves the chain)
./listener.py --simulate benign
./listener.py --send malicious      # transmit a frame (from a 2nd node)
```

`--simulate` needs no radio and can run from any host on the LAN — it exercises
parse → Modbus write end to end (watch it trip via `scripts/mb_read.py` / SCADA).

## Testing order (solo)

1. `--simulate malicious` → confirm the meter trips (Opta red, SCADA red), then
   `scripts/mb_reset.py` to clear.
2. Real over-the-air: run `listener.py` on this Pi, and `listener.py --send malicious`
   from a **second** SX1262 node → the frame arrives over LoRa and trips the meter.

## TODO

- Real over-the-air: a 2nd SX1262 node to transmit the frame (solo-testing limit).
- Optional benign heartbeat transmitter so normal-state RF is benign-but-present.
