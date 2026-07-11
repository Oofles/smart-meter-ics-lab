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
RSSI is measured by the collector's radio (needs the HAT's RSSI-append bit — see below).

```
[field kit] --SMST beacon (kit_id, FW_MODE), ttl=1--> [central: collector] --> dashboard
```

## Run it

```bash
# on the central node (its own Opta = Kit 00 at --host):
sudo python3 central/collector.py --host 192.168.1.200 --port 8090
# open the dashboard:  http://<central-pi>:8090/
```

`--host` is the central node's **own** Opta IP; `--port` defaults to 8090 (kept off SCADA's 8080).

## Status / TODO

- [x] Status beacon (`protocol.SMST`) + field-kit beaconing (`listener.py`, auto kit-id from `--host`).
- [x] Collector: aggregate beacons + local Kit 00 meter + dashboard/JSON.
- [ ] **RSSI** — enable the EBYTE RSSI-append bit in the golden HAT config; the collector
  already reads a trailing RSSI byte when present (`rssi=null` until enabled).
- [ ] **Drone mule** — drone logs `{kit, state, time}` per sortie and uploads to the
  collector when back in range, resolving out-of-range (Unknown) kits.
- [ ] A `smartmeter-collector.service` unit + a spot in provisioning for the central node.
