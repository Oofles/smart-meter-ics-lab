# scada/ — SCADA-LTS deployment (Phases 3–4)

SCADA-LTS on the Pi 5 via Docker Compose, polling the Opta over Modbus TCP.

## ARM64 note (updated)

The old worry — "stock compose pins `mysql-server:5.7`, no clean arm64" — is **no longer
true**. `scadalts/scadalts` and `mysql/mysql-server:8.0.32` both publish **native arm64**
images, so there's **no emulation and no DB workaround**. `docker-compose.yml` pins
`scadalts/scadalts:release-2.8.1` + `mysql/mysql-server:8.0.32`.

> The app's DB connection is baked into its `context.xml` (host `database`, user/pass
> `root`/`root`, schema `scadalts`). Keep the `database` service name and those creds, or
> mount your own `context.xml`.

## Deploy

On the Pi (in this folder):

```
docker compose up -d
docker compose logs -f scadalts        # watch first boot
```

First boot **builds the schema (~5 min)** — be patient. It's ready when the log settles and
the app answers at:

```
http://<pi-ip>:8080/Scada-LTS          # note the /Scada-LTS path, not bare :8080
```

Default login **admin / admin** — for this exercise it is **intentionally left as-is** (a
planted default-credential weakness for the defenders to discover). Change it (top-right user
→ Users → edit `admin`) only if this rig ever leaves the isolated lab.

## Modbus data source + points (Phase 3)

Data Sources → add **Modbus IP**: transport **TCP**, host `192.168.1.210`, port `502`,
update period `1 s`. Slave/unit id: any (the Opta answers all; use `1`).

SCADA-LTS **offsets are 0-based** — same as our PDU addresses in `docs/register-map.md`, so
no conversion:

| Point | Register range | Offset | Point type | Notes |
|-------|----------------|--------|------------|-------|
| POWER_STATUS | Coil status | 0 | Binary | healthy/fault bit |
| RESET | Coil status | 15 | Binary (settable) | write 1 to re-arm |
| VOLTAGE_X10 | Holding register | 0 | 2-byte unsigned | **multiplier 0.1** → shows 120.0 V |
| POWER_W | Holding register | 1 | 2-byte unsigned | |
| FW_MODE | Holding register | 9 | 2-byte unsigned | 0 normal / 1 malicious |

**Panel mirror (Phase 4b)** — add these six as **Input status** (discrete input, function 02)
Binary points so SCADA can render the same four-light panel + switch positions:

| Point | Register range | Offset | Point type | Notes |
|-------|----------------|--------|------------|-------|
| LAMP_BLUE | Input status | 0 | Binary | O1 blue lamp |
| LAMP_GREEN | Input status | 1 | Binary | O2 green lamp |
| LAMP_YELLOW | Input status | 2 | Binary | O3 yellow lamp (dial past 6) |
| LAMP_RED | Input status | 3 | Binary | O4 red lamp (faulted/attack) |
| SW_BLUE | Input status | 4 | Binary | I1 switch position |
| SW_GREEN | Input status | 5 | Binary | I2 switch position |

Validate each point against the bench: `python3 scripts/mb_read.py` from the repo should
match SCADA's live values.

## Graphical view — operator page (Phase 4)

Assets in `scada/assets/`: `operator-bg.png` (panel background, 900×480), and optional
custom lamps `power-green.png` / `power-red.png`.

In SCADA-LTS → **Graphical Views → add a view**:
1. **Name** it `Smart Meter Operator View`; **upload the background** `scada/assets/operator-bg.png`.
2. **POWER indicator** — add a **Binary graphic** → point **POWER_STATUS** → image set
   **Leds32** (or `LightBulb`): map **1 → green**, **0 → red**. Drop it in the POWER panel.
3. **VOLTAGE gauge** — add an **Analog graphic** → point **VOLTAGE_X10** → image set **Dial**
   / **SmallDial**, range **0–250**. Place in the VOLTAGE panel; add a **Simple point**
   (numeric) beneath it for the `120.0` readout.
4. **USAGE** — add a **Simple point** → point **POWER_W** in the USAGE panel.
5. **Four-light panel** — add four **Binary graphic** components, one per lamp point
   **LAMP_BLUE / LAMP_GREEN / LAMP_YELLOW / LAMP_RED**, image set **Leds32** (or `LightBulb`)
   with each mapped **1 → its color, 0 → off/grey**. Lay them out as a stack light to match
   the Opta panel. Optionally add two small **Binary graphic**s for **SW_BLUE / SW_GREEN**
   (image set **Switch3d**/**Contacts**) so the operator's switch positions show too — during
   an attack the switch reads **on** while its lamp is forced **off**, which is the teachable
   moment.
6. **Save**, then open the view (Views menu) — it renders live.

Verify: `python3 scripts/mb_trip.py` → **red** lamp lights, blue/green/yellow go **off**,
POWER_STATUS flips, voltage & usage drop to **0**; `scripts/mb_reset.py` (or the I3 button /
RESET coil) restores normal and the lamps resume following the I1/I2 switches + dial. Day-1
blue-team check: flip **I1**→blue lamp, **I2**→green lamp, dial **past 6**→yellow lamp, all
reflected live in SCADA.

## Versioning the config

The data source + all 11 points (5 core + the 6 panel-mirror discrete inputs) are versioned
in **`scada/emport-config.json`**, serialized via **Emport**. The six panel points were
provisioned headlessly with **`scada/emport.py`** (drives SCADA-LTS's DWR-backed Emport over
HTTP) and verified live against the Opta — trip → red on / others off with the switches still
reading on.

```
python3 scada/emport.py export scada/emport-config.json   # re-serialize after UI changes
python3 scada/emport.py import scada/emport-config.json    # (re)create points on a fresh box
```

Import is **additive/upsert by xid** (matches + creates/updates points; does not delete
points missing from the JSON), so it's safe to re-run against the live rig. Env overrides:
`SCADA_URL`, `SCADA_USER`, `SCADA_PASS` (default the Pi + `admin/admin`). A **full project**
import (the UI's project-file import) still deletes existing config first — use the JSON
data-source/points Emport above for incremental changes. Graphical **views** aren't included
here; place them in the UI per the steps above.

## Persistence / ops

- Named volumes `db_data` (MySQL) and `tomcat_log` persist across restarts.
- Heap is `-Xmx1G` (Pi-sized); raise to 2G only on an 8 GB Pi.
- `TZ` is set on both containers — change from `America/New_York` to match the Pi.
