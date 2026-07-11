# PROVISION.md — standing up kits (1 → 45)

Replication model: **isolated islands, per-kit-addressed Pis.** Kits never share an
Ethernet segment during the exercise; the only thing that crosses between them is **LoRa RF**
(the attack channel). Each kit is provisioned by a single **kit-number** argument.

## Addressing

Set entirely by the **kit number** — kit N → Pi `.10N`, Opta `.20N`:

| Device | IP | Notes |
|--------|-----|-------|
| Pi (wired/switch) | `192.168.1.(100 + kit)` | kit 9 → `.109` |
| Opta | `192.168.1.(200 + kit)` | kit 9 → `.209`. Stamped into the firmware at flash time (`patch_ip.py` rewrites a `KITCFGv1` marker) — **one prebuilt `.bin` serves every kit**, no recompile. |
| Pi (WiFi) | DHCP | Internet for setup only; unused during the exercise. |

Every device is uniquely addressed, so nothing collides — you **may** bridge the OT switches
into one management LAN (all Pis `.10x`, all Optas `.20x`) if you want central reach. It's
optional: the exercise runs on isolated islands and RF is the cross-kit attack path.

**Personal test kit** (not one of the 45): Pi `.11`, Opta `.12` — a low-band pair kept clear of
the `.1xx`/`.2xx` production ranges. Set the Pi with `nmcli`; flash its Opta with
`sudo provision/opta_flash.sh 12`.

## Per-kit hardware

- Raspberry Pi 5 (baseline Raspberry Pi OS, 64-bit / Bookworm).
- Waveshare SX1262 868M LoRa HAT on the GPIO header (jumpers: UART-select **B**, M0/M1 caps
  removed), antenna attached.
- Arduino Opta **connected to the Pi by USB** (this is what lets the Pi flash it).
- 12–24 V trainer supply for the Opta (relays only switch on that supply; Modbus logic runs
  without it).
- 5-port switch: Pi + Opta both on it (the kit's OT LAN). **No uplink to other kits.**

## Two-stage replication

**Stage 1 — build ONE golden kit** (once, on a reference Pi with internet over WiFi):

```bash
git clone <repo> ~/smart-meter-ics-lab && cd ~/smart-meter-ics-lab
sudo provision/provision.sh <kit-number>     # e.g. 2  -> Pi .102; all phases
sudo reboot                                  # UART change needs it; then 'provision.sh <n> verify'
```

`provision.sh <kit> [phase ...]` is **phased** — validate a fresh kit a step at a time:
`sudo provision/provision.sh 2 system serial net ssh`, then `scada`, `service`, `hw`, `verify`.
Phases: `system serial net ssh scada service hw verify`.

When it verifies clean, power down and image the SD (on another machine):

```bash
sudo dd if=/dev/sdX of=golden-kit.img bs=4M status=progress   # then shrink with pishrink
```

**Stage 2 — clone the other 44:** write `golden-kit.img` to each SD, boot the kit, then run
`kit_init.sh` **with that kit's number**:

```bash
cd ~/smart-meter-ics-lab && sudo provision/kit_init.sh 9      # kit 9 -> Pi .109
```

`kit_init.sh <kit>` applies only the per-kit bits (`net ssh hw verify`): this kit's IP + SSH
keys, this HAT's NVM config, and this Opta's firmware, then verifies. ~1–2 min per kit.
Everything slow (SCADA + config, listener service, UART, packages) rode along in the image.

## SSH / management

`provision.sh` enables `ssh` and installs the public keys in **`provision/authorized_keys`**
(version-controlled) for every kit — so any kit is reachable from a management laptop with a
listed key. This is deliberate for the isolated lab (same spirit as the planted `admin/admin`
SCADA cred); don't ship it outside the lab. Add facilitator keys to that file before imaging.

> Bootstrapping the *first* kit: enable SSH once by hand (`sudo raspi-config nonint do_ssh 0`
> + drop your key in `~/.ssh/authorized_keys`) so you can get in to run `provision.sh`; from
> then on the golden image carries SSH + keys forward automatically.

## The building blocks (all in `provision/`)

| Script | Does | Notes |
|--------|------|-------|
| `hat_config.py` | Writes the HAT to the golden config (ch 18 / 868.125 MHz, air-rate 2.4k, transparent) + verifies | `--read` to inspect only. Validated on the reference kit. |
| `opta_flash.sh <octet>` | Stamps this kit's IP into the firmware (`patch_ip.py`), then flashes from the Pi via `dfu-util` (1200-baud touch → DFU → 0x08040000) | No Arduino toolchain on the Pi; Opta must be on Pi USB. |
| `patch_ip.py` | Rewrites the `KITCFGv1` IP-marker octet in a copy of the `.bin` | so one firmware serves every kit |
| `kit_init.sh <kit>` | Per-clone: net + ssh + HAT + Opta + verify | thin wrapper over `provision.sh` phases |
| `provision.sh <kit> [phase]` | Full/partial kit build, phased | Run once for the golden kit; validate on kit 2. |
| `authorized_keys` | Management SSH public keys installed on every kit | add facilitator keys here |

The Opta firmware artifact `opta/firmware/smart_meter.ino.bin` is rebuilt from
`opta/smart_meter/` with `arduino-cli` (see `opta/README.md`) whenever the sketch changes —
regenerate + re-image after any Opta change.

## Verify a kit

```bash
python3 provision/hat_config.py --read     # HAT: 00 00 00 62 00 12 03 00 00
python3 scripts/mb_read.py                 # Opta: healthy, dial voltage, panel state
# SCADA: http://192.168.1.<100+kit>:8080/Scada-LTS  (admin/admin — intentional planted cred)
```

## RF at scale (single shared channel — "one shot trips everyone")

All kits on channel 18 in one venue = one broadcast domain: a single drone injection reaches
every in-range kit directly. Inject with **`--ttl 1`** so nodes trip on direct reception and
do **not** rebroadcast (45 relayers would storm the channel). The mesh relay only matters if
the venue is large enough that some kits are out of the drone's range.
