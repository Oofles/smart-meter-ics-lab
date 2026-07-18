# DEMO.md — the DV walk-through demo (Kits 43–45, isolated mesh)

A **self-contained, 3-kit demo** of the smart-meter RF attack, for showing DVs in real time
while the **live exercise fleet is online**. It runs on its **own LoRa mesh channel**, fully
isolated from the exercise, so demo payloads **cannot** reach the blue-team kits.

## Why it's safe: separate channel = separate mesh

The only thing that crosses between kits is LoRa RF. Every radio only demodulates its **own
channel** (centre frequency) — a receiver tuned elsewhere hears *nothing*, so two channels are
a hard **PHY-layer** separation, not a software filter.

| Mesh | Kits | Channel | Frequency |
|------|------|---------|-----------|
| **Exercise** (blue team) | 1–45 + Kit 00 central + drone | 65 (`0x41`) | 915.125 MHz |
| **DV demo** (this doc)   | 43, 44, 45 | **58 (`0x3a`)** | **908.125 MHz** |

908.125 vs 915.125 = **7 MHz** apart, both inside the US 902–928 ISM band, and far wider than
the ~125 kHz the 2.4k air-rate occupies → **zero spectral overlap**. The payload frames are
byte-for-byte identical to the real attack (so the demo is faithful); they simply can't be
heard on channel 65. Nothing at the app layer changes — only the HAT channel byte (REG5).

> The channel lives in `provision/hat_config.py`. Default is **GOLDEN ch 65** (the exercise);
> `--channel 58` (or `HAT_CHANNEL=58` to `provision.sh`) selects the demo mesh. The exercise
> build path is completely unchanged.

## Topology (all three kits in one room)

```
   Kit 43  Pi .143  ── demo CENTRAL: collector + dashboard (:8090) + RF console (injects payload)
   (own Opta .243)      RSSI-append HAT, channel 58
        │  LoRa ch 58 (908.125 MHz) — isolated demo mesh
        ├──────────────► Kit 44  Pi .144 / Opta .244  — victim meter (listener + 4-light panel)
        └──────────────► Kit 45  Pi .145 / Opta .245  — victim meter (listener + 4-light panel)
```

- **Kit 43** is the facilitator's console: it aggregates status onto the dashboard **and**
  injects the "malicious firmware update" from the dashboard's **RF Console** (no separate
  drone Pi needed — the collector transmits over the same HAT it listens on). Its own Opta is
  a valid target too, so on attack **all three meters** in the room go red.
- **Kits 44 & 45** are ordinary field/victim kits: their physical **blue/green/yellow/red
  panels** are the live visual, and they beacon status back to Kit 43's dashboard.

## Build (do this once, before the tours)

Per-kit hardware and jumpers are exactly as `PROVISION.md` (Waveshare HAT: UART-select **B**,
M0/M1 caps removed, antenna on; Opta on the Pi's USB). The **only** difference from a normal
kit build is `HAT_CHANNEL=58`, which puts the HAT straight onto the demo mesh so these kits
**never momentarily join channel 65**.

### Kits 44 and 45 — victim meters

On each kit (git clone the repo first), two-step because the UART change needs a reboot:

```bash
# --- Kit 44 (repeat with 45 on the other kit) ---
sudo provision/provision.sh 44 system serial      # packages + enable header UART
sudo reboot
# after reboot:
sudo HAT_CHANNEL=58 provision/provision.sh 44 net ssh service hw verify
```

`HAT_CHANNEL=58` makes `hat_config.py` write channel 58. Everything else is a standard kit:
static IP `.144`, listener service pointed at Opta `.244`, Opta flashed to `.244`.

### Kit 43 — demo central / console

Build it as a field kit **on the demo channel**, then convert it to the central node:

```bash
sudo provision/provision.sh 43 system serial
sudo reboot
# after reboot — base build on the demo channel:
sudo HAT_CHANNEL=58 provision/provision.sh 43
# convert it into the collector + dashboard + RF console (channel 58):
sudo provision/demo_central.sh 43 58
```

`demo_central.sh` disables the mesh listener, re-writes the HAT to **`--rssi --channel 58`**
(central needs RSSI-append for the range map), and installs/enables
`smartmeter-collector.service` pointed at Kit 43's own Opta `.243`, serving the dashboard on
`:8090`.

## Verify the isolation (do this BEFORE any tour — this is the safety check)

Read back every demo kit's channel and confirm it's **58 (`3a`)**, not 65 (`41`). From the
facilitator laptop on each kit's switch:

```bash
provision/demo_channel_update.sh 43 read
provision/demo_channel_update.sh 44 read
provision/demo_channel_update.sh 45 read
```

In each readback, the config is 9 bytes `ADDH ADDL NETID REG3 REG4 CH REG6 REG7 REG8`; the
**6th byte is the channel**:

- **`... 00 3a ...`** → channel 58 = demo mesh ✅ (this is what all three demo kits must show)
- `... 00 41 ...` → channel 65 = **exercise mesh** ❌ (if a demo kit shows this, fix it before demoing:
  `provision/demo_channel_update.sh <kit>` writes it back to 58)

Belt-and-suspenders — confirm an **exercise** kit still reads `41` (unchanged by any of this):

```bash
provision/kit_915_update.sh 9 read     # an exercise kit -> expect '... 00 41 ...'
```

Because the meshes are on different frequencies, a demo payload sent on 58 is physically
unreceivable on 65 even if a kit were mis-set — but the readback is your positive proof.

## Run the demo

1. Power the three kits. Open the dashboard for the DVs: **`http://192.168.1.143:8090/`**
   (Kit 43). Kits 44 and 45 appear as their status beacons arrive; all should read **normal**
   (green). Their physical panels show the healthy state (blue/green, yellow if the dial ≥ 6).
2. **Deliver the payload** — the "drone" moment. Use the dashboard's **RF Console**, or from Kit 43:
   ```bash
   # TEST trip (operator RESET can clear it) — direct to all in-room kits:
   curl -s -XPOST localhost:8090/api/send -d '{"type":"malicious","ttl":1}'
   ```
   Within a second, **all three meters go red** — panels flip to O4 red, voltage/watts drop to
   zero — and the dashboard cells turn critical. Use `ttl` > 1 to narrate the **flood mesh**
   (44/45 rebroadcast hop-by-hop).
3. **EXERCISE LOCK variant** (operator RESET is disabled — shows the "you can't just reset it"
   lesson): `{"type":"malicious_lock","ttl":1}`.
4. **Recover** for the next tour group:
   ```bash
   curl -s -XPOST localhost:8090/api/send -d '{"type":"reset","ttl":1}'   # clears TEST *and* LOCK
   ```
   (A power-cycle also clears it — LOCK is RAM-only.) Meters return to green.

Watch it land in real time on Kit 43: `journalctl -u smartmeter-collector -f`.

> Cosmetic note: `fleet.html` is shared with the exercise dashboard, so its header subtitle
> still reads "915 MHz / ch 65". The demo genuinely runs on 908.125 / ch 58 (proven by the
> readback above); the subtitle is just the static page title, not a live readout.

## Teardown / relationship to Thursday

Nothing to undo on the exercise fleet — this demo never touched it. The three demo kits simply
**stay on channel 58**; they are a permanent, separate island. If you ever fold 43–45 back into
the exercise, re-channel them to 65 first and re-verify:

```bash
DEMO_CHANNEL=65 provision/demo_channel_update.sh 44     # -> exercise mesh (readback '... 00 41 ...')
```

(For the central, `demo_central.sh` left a collector service; disable it and re-run
`provision/provision.sh 43` if you want it back as a plain field kit.)
