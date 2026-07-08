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

Default login **admin / admin** — **change it immediately** (top-right user → Users → edit
`admin` → new password).

## Modbus data source + points (Phase 3)

Data Sources → add **Modbus IP**: transport **TCP**, host `192.168.1.210`, port `502`,
update period `1 s`. Slave/unit id: any (the Opta answers all; use `1`).

SCADA-LTS **offsets are 0-based** — same as our PDU addresses in `docs/register-map.md`, so
no conversion:

| Point | Register range | Offset | Point type | Notes |
|-------|----------------|--------|------------|-------|
| POWER_STATUS | Coil status | 0 | Binary | green/red bit |
| RESET | Coil status | 15 | Binary (settable) | write 1 to re-arm |
| VOLTAGE_X10 | Holding register | 0 | 2-byte unsigned | **multiplier 0.1** → shows 120.0 V |
| POWER_W | Holding register | 1 | 2-byte unsigned | |
| FW_MODE | Holding register | 9 | 2-byte unsigned | 0 normal / 1 malicious |

Validate each point against the bench: `python3 scripts/mb_read.py` from the repo should
match SCADA's live values.

## Versioning the config

Use **Import/Export (Emport)** in the UI to serialize data sources + points (+ views) to
**JSON**; commit that JSON here (e.g. `scada/emport-datasource.json`). Caveat: a full
project *import* deletes existing config first — safe for a repo-driven rebuild, not against
a live instance.

## Persistence / ops

- Named volumes `db_data` (MySQL) and `tomcat_log` persist across restarts.
- Heap is `-Xmx1G` (Pi-sized); raise to 2G only on an 8 GB Pi.
- `TZ` is set on both containers — change from `America/New_York` to match the Pi.
