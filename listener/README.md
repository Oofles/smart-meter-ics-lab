# listener/ — LoRa flood-mesh update listener (Phase 5)

Pi-side service that replicates the **smart-meter (AMI) mesh attack**: a "drone"
injects a malicious firmware update near one node; every node that hears it
**applies it locally** (`FW_MODE=1` → trips its own meter via Modbus) **and
rebroadcasts it**, so the update floods hop-by-hop to every reachable meter over
LoRa. Built entirely on the existing UART SX1262 HATs — **no Meshtastic, no new
hardware**.

## How the mesh works

The EBYTE modules broadcast in transparent mode (every HAT on the same frequency
hears every transmission). The flood layer lives in `protocol.py` + `listener.py`:

- Each frame carries a **`msg_id`** (dedup) and a **`ttl`** (hop limit).
- On receive: if `msg_id` is new → **apply** locally, then **relay** (`ttl-1`,
  after a small random jitter) if hops remain. A seen-`msg_id` set means each node
  acts/relays a frame **once** (no broadcast storm); `ttl` bounds the reach.
- Spread-out site → true multi-hop; single bench (all in range) → one-hop flood.
  Same code; `--ttl` controls it.

## Hardware (validated)

Waveshare **SX1262 868M LoRa HAT** — UART (EBYTE-style), not SPI.

- Serial `/dev/serial0` (=`/dev/ttyAMA0` on Pi 5) @ **9600 8N1**; mode pins
  **M0=BCM22, M1=BCM27** on **gpiochip0** via `lgpio`. Jumpers: **UART-select = B**,
  **M0/M1 caps removed**. Deps already on the Pi: `pyserial`, `lgpio` (Modbus is the
  dependency-free `scripts/mb.py`).

## Protocol (`protocol.py`)

11-byte frame: `b"SMFW" | version | type | msg_id(2) | ttl(1) | crc16(2)`. `type`:
`0x00` benign (heartbeat) / `0x01` malicious. The listener "validates" the CRC — but
the channel is unauthenticated (the lesson).

## Run it

```
./listener.py                      # be a mesh node: receive → apply → relay
./listener.py --send malicious     # the "drone": inject an update over LoRa
./listener.py --send malicious --ttl 4
./listener.py --simulate malicious # NO radio: exercise apply+relay (any host on the LAN)
```

`--host` sets this node's Opta (default `192.168.1.210`); on a real fleet each kit's
listener points at its own Opta.

## Demo (the drone → mesh propagation)

1. Run `./listener.py` on **every meter's Pi** (each with its own `--host`).
2. From the **drone/injection** node run `./listener.py --send malicious`.
3. Every node in range applies it (its meter trips) and relays it; nodes out of the
   drone's range trip via a neighbour's relay. Watch each meter's panel go red (red lamp,
   voltage/usage to zero); `scripts/mb_reset.py` (or the I3 button) re-arms.

Solo (one radio): `--simulate malicious` proves the apply chain without a partner;
full mesh propagation needs ≥2 SX1262 nodes.
