# PROVISION.md — standing up kits (1 → 45)

Replication model: **isolated identical islands**. Every kit is a byte-identical clone —
same static IPs (Pi `192.168.1.94`, Opta `192.168.1.210`), same HAT config, same firmware.
Kits never share an Ethernet segment; the only thing that crosses between them is **LoRa RF**
(the attack channel). Identical addressing is safe *because* the islands are electrically
separate, and it's what makes cloning trivial.

## Per-kit hardware

- Raspberry Pi 5 (baseline Raspberry Pi OS, 64-bit / Bookworm).
- Waveshare SX1262 868M LoRa HAT on the GPIO header (jumpers: UART-select **B**, M0/M1 caps
  removed), antenna attached.
- Arduino Opta **connected to the Pi by USB** (this is what lets the Pi flash it).
- 12–24 V trainer supply for the Opta (relays only switch on that supply; Modbus logic runs
  without it).
- 5-port switch: Pi + Opta both on it (that's the kit's OT LAN). **No uplink to other kits.**

## Two-stage replication

**Stage 1 — build ONE golden kit** (do this once, on the reference Pi):

```bash
git clone <repo> ~/smart-meter-ics-lab && cd ~/smart-meter-ics-lab
sudo provision/provision.sh          # deps, UART, static IP, SCADA, listener svc, HAT, Opta
sudo reboot                          # UART change needs it; re-run 'provision.sh verify' after
```

`provision.sh` is **phased** — run one at a time while validating a fresh kit:
`sudo provision/provision.sh system serial net`, then `scada`, `service`, `hw`, `verify`.

When it verifies clean, power down and image the SD card (on another machine):

```bash
sudo dd if=/dev/sdX of=golden-kit.img bs=4M status=progress   # then shrink with pishrink
```

**Stage 2 — clone the other 44:** write `golden-kit.img` to each SD, boot the kit, then:

```bash
cd ~/smart-meter-ics-lab && sudo provision/kit_init.sh
```

`kit_init.sh` does only the two things that live in the *physical* hardware and therefore
can't be baked into the image: **configure this kit's HAT NVM** and **flash this kit's Opta**,
then verify. ~1–2 min per kit. Everything else (SCADA + config, listener service, IP, UART)
rode along in the image.

## The building blocks (all in `provision/`)

| Script | Does | Notes |
|--------|------|-------|
| `hat_config.py` | Writes the HAT to the golden config (ch 18 / 868.125 MHz, air-rate 2.4k, transparent) + verifies | `--read` to inspect only. Validated on the reference kit. |
| `opta_flash.sh` | Flashes `opta/firmware/smart_meter.ino.bin` from the Pi via `dfu-util` (1200-baud touch → DFU → write 0x08040000) | No Arduino toolchain on the Pi; Opta must be on Pi USB. |
| `kit_init.sh` | HAT + Opta + verify (per clone) | |
| `provision.sh` | Full golden-kit build (phased) | Run once; validate on kit 2. |

The Opta firmware artifact `opta/firmware/smart_meter.ino.bin` is rebuilt from
`opta/smart_meter/` with `arduino-cli` (see `opta/README.md`) whenever the sketch changes —
regenerate + re-image after any Opta change.

## Verify a kit

```bash
python3 provision/hat_config.py --read     # HAT: 00 00 00 62 00 12 03 00 00
python3 scripts/mb_read.py                 # Opta: healthy, dial voltage, panel state
# SCADA: http://192.168.1.94:8080/Scada-LTS  (admin/admin — intentional planted cred)
```

## RF at scale (single shared channel — "one shot trips everyone")

All kits on channel 18 in one venue = one broadcast domain: a single drone injection reaches
every in-range kit directly. Inject with **`--ttl 1`** so nodes trip on direct reception and
do **not** rebroadcast (45 relayers would storm the channel). The mesh relay only matters if
the venue is large enough that some kits are out of the drone's range.
