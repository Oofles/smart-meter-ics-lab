# PROVISION.md — standing up kits (1 → 45)

Replication model: **isolated islands, per-kit-addressed Pis, built one at a time.** Kits never
share an Ethernet segment during the exercise; the only thing that crosses between them is
**LoRa RF** (the attack channel). There is **no golden image** — every kit is built individually
by cloning the repo and running one script with its kit number, so each kit's IP, listener
service, and Opta firmware are stamped correctly per-kit.

## Addressing

Set entirely by the **kit number** — kit N → Pi `.10N`, Opta `.20N`:

| Device | IP | Notes |
|--------|-----|-------|
| Pi (wired/switch) | `192.168.1.(100 + kit)` | kit 9 → `.109` |
| Opta | `192.168.1.(200 + kit)` | kit 9 → `.209`. Stamped into the firmware at flash time (`patch_ip.py` rewrites a `KITCFGv1` marker) — **one prebuilt `.bin` serves every kit**, no recompile. |
| Pi (WiFi) | DHCP | Internet for setup only (git clone + apt); unused during the exercise. |

Every device is uniquely addressed, so nothing collides — you **may** bridge the OT switches
into one management LAN (all Pis `.10x`, all Optas `.20x`) if you want central reach. It's
optional: the exercise runs on isolated islands and RF is the cross-kit attack path.

**Kit 00 = the central/facilitator node** (not one of the 45 blue-team kits): Pi `.100`,
Opta `.200`. It additionally runs the fleet **collector + dashboard** and has RSSI-append
enabled on its HAT — see `central/README.md`.

## Per-kit hardware

- Raspberry Pi 5 (Raspberry Pi OS, 64-bit; Bookworm or Debian 13/trixie both work).
- Waveshare SX1262 868M LoRa HAT on the GPIO header (jumpers: UART-select **B**, M0/M1 caps
  removed), antenna attached.
- Arduino Opta **connected to the Pi by USB** (this is what lets the Pi flash it).
- 12–24 V trainer supply for the Opta (relays only switch on that supply; Modbus logic runs
  without it).
- 5-port switch: Pi + Opta both on it (the kit's OT LAN). **No uplink to other kits.**

The blue team's operator view is the Opta's **physical four-light panel** (O1 blue / O2 green /
O3 yellow / O4 red) — there is no software HMI on the kits.

## Build a kit (repeat per kit)

On each kit, with internet over WiFi, **git clone the repo and run the build with that kit's
number.** The UART change needs a reboot, so it's a natural two-step:

```bash
git clone https://github.com/Oofles/smart-meter-ics-lab.git ~/smart-meter-ics-lab
cd ~/smart-meter-ics-lab
sudo provision/provision.sh <N> system serial     # packages + enable the header UART
sudo reboot                                        # UART change takes effect
cd ~/smart-meter-ics-lab
sudo provision/provision.sh <N> net ssh service hw verify   # the rest of the build
```

Or run it all in one go (`sudo provision/provision.sh <N>`) and just re-run the HAT step after
the reboot (`sudo provision/provision.sh <N> hw verify`) — HAT config can't succeed until the
UART is live, but the Opta flash (USB) and everything else will.

`provision.sh <kit> [phase ...]` is **phased** (default order:
`system serial net ssh service hw verify`) so you can validate a kit a step at a time.
What each phase does:

| Phase | Does |
|-------|------|
| `system` | apt packages (`dfu-util`, `python3-serial`, `python3-lgpio`, `git`, `curl`, `openssh-server`) |
| `serial` | enable the GPIO header UART, disable the serial login console (needs a reboot) |
| `net` | static wired IP `192.168.1.(100+kit)/24`, **no gateway + `never-default`** so eth0 doesn't steal the default route from WiFi |
| `ssh` | enable the SSH server, install `provision/authorized_keys` |
| `service` | install + enable `smartmeter-listener.service`, pointed at **this kit's** Opta `.20N` |
| `hw` | flash this Opta (IP `.20N` stamped in) + write this HAT's golden NVM config |
| `verify` | read back the HAT config + read the Opta over Modbus |

## SSH / management

`provision.sh` enables `ssh` and installs the public keys in **`provision/authorized_keys`**
(version-controlled) for every kit — so any kit is reachable from a management laptop with a
listed key. This is deliberate for the isolated lab (same spirit as the intentionally
unauthenticated RF update channel the exercise teaches); don't ship it outside the lab. Add
facilitator keys to that file before building. If you build a kit with a keyboard/monitor
attached you can skip the `ssh` phase.

## The building blocks (all in `provision/`)

| Script | Does | Notes |
|--------|------|-------|
| `provision.sh <kit> [phase]` | Full/partial per-kit build, phased | The whole replication method — run once per kit. |
| `drone.sh [octet] [phase]` | Builds a Pi as the RF **drone**/injection node (no Opta, no listener service) | The attacker node — see "The drone" below. Also converts an old field kit into a drone. |
| `hat_config.py` | Writes the HAT to the golden config (ch 65 / 915.125 MHz, air-rate 2.4k, transparent) + verifies | `--read` to inspect only; `--rssi` (central node only) enables the RSSI-append byte. |
| `opta_flash.sh <octet>` | Stamps this kit's IP into the firmware (`patch_ip.py`), then flashes from the Pi via `dfu-util` (1200-baud touch → DFU → 0x08040000) | No Arduino toolchain on the Pi; Opta must be on Pi USB. |
| `patch_ip.py` | Rewrites the `KITCFGv1` IP-marker octet in a copy of the `.bin` | so one firmware serves every kit |
| `authorized_keys` | Management SSH public keys installed on every kit | add facilitator keys here |

The Opta firmware artifact `opta/firmware/smart_meter.ino.bin` is rebuilt from
`opta/smart_meter/` with `arduino-cli` (see `opta/README.md`) whenever the sketch changes —
regenerate + commit after any Opta change, then each kit's build flashes the current binary.

## Verify a kit

```bash
python3 provision/hat_config.py --read     # HAT: 00 00 00 62 00 12 03 00 00
python3 scripts/mb_read.py 192.168.1.20N   # Opta: healthy, dial voltage, panel state
```

## The drone / injection node

The **drone** is the attacker: it transmits malicious firmware-update frames over LoRa; every
field kit in range hears them, trips its own meter (`FW_MODE` over Modbus), and flood-relays.
Build it with **`drone.sh`**, not `provision.sh` — the drone has **no Opta** (nothing to flash),
runs **no listener service** (it injects on demand, so it neither beacons nor holds the radio),
and its wired IP is optional (it serves nothing; the IP is only for facilitator SSH).

```bash
# on the drone Pi, repo cloned:
sudo provision/drone.sh            # full build, leaves wired IP as-is
sudo provision/drone.sh 50         # ... and set the wired IP to 192.168.1.50
sudo provision/drone.sh hat        # re-run just the HAT config after fixing jumpers
```

Phases: `system serial net ssh undo-kit hat verify` (`undo-kit` disables a leftover
`smartmeter-listener` if this Pi had been built as a field kit; `net` is a no-op without an
octet). `verify` reads the HAT and fires a **benign** frame to prove the TX path (no trip).

Inject the actual attack from the drone:

```bash
cd listener && python3 listener.py --send malicious            # TEST trip (operator RESET clears it)
                python3 listener.py --send malicious --exercise # EXERCISE LOCK (RESET disabled)
                python3 listener.py --send malicious --loop      # execution mode: re-inject every --interval s
                python3 listener.py --send reset                # facilitator recovery: FW_MODE:=0 everywhere
```

`--loop` is the roaming "keep delivering" mode (fresh `msg_id` each pass so newly-in-range kits
trip). The link is blind broadcast — no ACK, the drone stores no per-kit state — so to see what
an injection hit, run **`python3 scripts/rf_sniff.py`** on the drone (passive; decodes the target
kits' `SMST` beacons flipping to `FW_MODE=1`). Central-side, the same beacons drive the Kit 00
dashboard.

**Data-mule** (`scripts/datamule.py`): a roaming drone hears kits that are out of the central
collector's range, buffers their `SMST` beacons, and re-emits them (marked relayed) so Kit 00
resolves those kits as **"via mule"** on the dashboard when the drone passes back in range:

```bash
sudo python3 scripts/datamule.py                      # listen + forward buffered beacons every 15s
sudo python3 scripts/datamule.py --forward-interval 10 --expire 300
```

Store-and-forward only (STATUS, not attacks); a beacon Kit 00 hears directly always wins over a
muled copy, so running the mule near in-range kits is harmless.

### Launching the drone (autonomous, boot-armed)

The deployed drone is headless and off the network, so it self-starts from a **systemd boot
service** — no SSH at launch. Install it once with **`sudo provision/drone_service.sh`**; the
payload/timing live in **`/etc/default/smartmeter-drone`** (a one-line change swaps TEST → LOCK).

**Installed DISABLED on purpose** — a normal boot does nothing, so bench setup never fires an
attack. Enabling it is the deliberate "arm for the field" step:

```bash
sudo provision/drone_service.sh                 # install unit + config (disabled)
sudo systemctl start smartmeter-drone           # test now: honors the countdown, then loops
journalctl -u smartmeter-drone -f               # watch: ARM countdown -> INJECT #1, #2, ...
sudo systemctl enable smartmeter-drone          # ARM: run on every boot (do this for the field)
sudo systemctl disable smartmeter-drone         # DISARM: back to inert boots
```

Field use: arm it (`enable`), then **just power the Pi on at the launch point** — it waits
`DRONE_DELAY` seconds (default 60, the window to get it airborne) and starts the injection loop.
Recover the kits afterward with `listener.py --send reset` (drone or Kit 00 console).

Config knobs (`/etc/default/smartmeter-drone`):

| Var | Default | Meaning |
|-----|---------|---------|
| `DRONE_SEND` | `malicious` | `malicious` = attack; `benign` = harmless heartbeat (safe dry run) |
| `DRONE_MODE` | *(empty)* | empty = **TEST** trip (RESET clears); `--exercise` = **EXERCISE LOCK** — *set this before exercise day* |
| `DRONE_TTL` | `3` | floods out-of-range kits via relays (one flyby propagates the mesh); set `1` for direct-range only |
| `DRONE_INTERVAL` | `5` | seconds between re-injections while flying |
| `DRONE_DELAY` | `60` | launch countdown before the first injection |

Hardware: the drone **must** be a 2nd EBYTE/Waveshare SX1262 **UART** HAT on the GOLDEN config —
a raw-SX1262 board (Heltec/RadioLib) does **not** interoperate (see `drone/README.md`). The
backup drone (Pi Zero) is built with the exact same `drone.sh`.

## RF at scale (single shared channel — "one shot trips everyone")

All kits on channel 65 in one venue = one broadcast domain: a single drone injection reaches
every in-range kit directly. Inject with **`--ttl 1`** so nodes trip on direct reception and
do **not** rebroadcast (45 relayers would storm the channel). The mesh relay only matters if
the venue is large enough that some kits are out of the drone's range.
