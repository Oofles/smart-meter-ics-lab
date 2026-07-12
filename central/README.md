# central/ — facilitator fleet console (collector + dashboard)

The **central node** is the facilitator's setup: a Pi + SX1262 HAT + its own Opta
("**Kit 00**"). It gives the red team one screen showing every kit's status.

- `collector.py` — the service. Listens on LoRa for **status beacons** from the field
  kits, applies malicious update frames to its **own** Opta (so the central node is a
  valid attack target you can demo against), polls that local Opta over Modbus for the
  full Kit 00 meter, and serves the dashboard + a JSON feed.
- `fleet.html` — the live dashboard (`/`), a 45-kit grid + Kit 00; click a kit for detail.
  Polls `/api/fleet` every 1.5 s. Same page you reviewed as the mock-up, wired to real data.

## How status gets here

Each field kit's `listener.py` **beacons** its state over LoRa — a tiny `SMST` frame
(`kit_id + FW_MODE`), sent on a ~20 s heartbeat **and immediately on any state change**,
at **`ttl=1`** (direct only — no relay storm). The collector hears whatever is in range;
kits out of range show **Unknown** until the **drone mules** their status back (planned).
RSSI is measured by the collector's radio — enable the HAT's RSSI-append bit on **this
node only** with `sudo python3 provision/hat_config.py --rssi` (field kits stay on plain
golden; it's a receive-side setting, same PHY, so they still interoperate). The module
then appends one RSSI byte per received packet; the collector reports it as dBm.

```
[field kit] --SMST beacon (kit_id, FW_MODE), ttl=1--> [central: collector] --> dashboard
```

## Run it

```bash
# one-time: enable RSSI-append on THIS node's HAT (field kits don't get this):
sudo python3 provision/hat_config.py --rssi
# run once in the foreground (own Opta = Kit 00 at --host):
sudo python3 central/collector.py --host 192.168.1.200 --port 8090
# open the dashboard:  http://<central-pi>:8090/
```

`--host` is the central node's **own** Opta IP (Kit 00 = `192.168.1.200`); `--port` defaults
to 8090.

### As a service (survives reboot)

`smartmeter-collector.service` (this dir) is the central-node counterpart to the field kits'
`smartmeter-listener.service`. It runs as `vivicat` (needs `gpio`+`dialout` for the HAT),
`PYTHONUNBUFFERED=1` so RX-beacon lines hit `journalctl` live.

```bash
sudo cp central/smartmeter-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now smartmeter-collector
journalctl -u smartmeter-collector -f          # watch beacons land
```

## Status / TODO

- [x] Status beacon (`protocol.SMST`) + field-kit beaconing (`listener.py`, auto kit-id from `--host`).
- [x] Collector: aggregate beacons + local Kit 00 meter + dashboard/JSON.
- [x] **RSSI** — `hat_config.py --rssi` enables the EBYTE RSSI-append bit on the central HAT;
  collector reads the trailing byte and reports dBm. Validated over the air (K09 ≈ −10…−32 dBm on the bench).
- [x] `smartmeter-collector.service` unit (this dir) — installed + enabled on the central
  node (`.100`); survives reboot, RX lines live in `journalctl`.
- [ ] **Drone mule** — drone logs `{kit, state, time}` per sortie and uploads to the
  collector when back in range, resolving out-of-range (Unknown) kits.
- [ ] Fold the central-node setup (HAT `--rssi`, this service) into provisioning.
