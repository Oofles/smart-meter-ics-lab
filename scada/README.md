# scada/ — SCADA-LTS deployment (Phases 3–4)

SCADA-LTS on the Pi via Docker Compose (services: database + scadalts).

ARM64 note: the stock compose pins `mysql-server:5.7` (no clean arm64 build). Swap for
an arm64 MariaDB / MySQL 8 or emulate, and pin an arm64 `scadalts` tag. Persist volumes.
Change the default admin/admin login.

Build order:
1. `docker-compose.yml` up, reach the UI, change admin creds.
2. Add a Modbus IP data source -> Opta; data points POWER_STATUS, VOLTAGE_X10, POWER_W.
3. Graphical view: green/red image on POWER_STATUS, meter on VOLTAGE_X10 (render /10).
4. Export the data source + view config back into this folder.
