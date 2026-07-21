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
a kit out of range shows **Unknown** until the **drone data-mule** (`scripts/datamule.py`)
carries its last-known beacon back within reach — those show **"via mule"** with no RSSI (the
state is second-hand; a beacon the collector hears directly always wins over a muled copy).
RSSI is measured by the collector's radio — enable the HAT's RSSI-append bit on **this
node only** with `sudo python3 provision/hat_config.py --rssi` (field kits stay on plain
golden; it's a receive-side setting, same PHY, so they still interoperate). The module
then appends one RSSI byte per received packet; the collector reports it as dBm.

```
[field kit] --SMST beacon (kit_id, FW_MODE), ttl=1--> [central: collector] --> dashboard
```

## Facilitator TX — the RF console

Kit 00 is also the **drone/injection** node: the collector transmits over the same HAT it
listens on (they share it via a lock), so you can broadcast to every in-range kit **without
stopping the service**. The dashboard's **RF Console** has the buttons; under the hood they
POST to the collector:

```bash
# trip all in-range kits (TEST — operator RESET clears), direct-only:
curl -s -XPOST localhost:8090/api/send -d '{"type":"malicious","ttl":1}'
# EXERCISE LOCK (RESET disabled):        {"type":"malicious_lock","ttl":1}
# facilitator recovery — clears TEST *and* LOCK everywhere:
curl -s -XPOST localhost:8090/api/send -d '{"type":"reset","ttl":1}'
```

`ttl>1` floods via relays to kits out of direct range. Each send also applies to Kit 00's own
Opta (it's a node too). The **`reset`** frame (`protocol.TYPE_RESET`) is the RF version of the
facilitator's `mb_unlock.py` — a field kit's `listener.py` writes `FW_MODE:=0` on receipt.
(Kits still on older firmware ignore an unknown frame type as a no-op, so it's safe to mix.)

Standalone (collector stopped), the same frames go out via `listener.py --send reset` /
`--send malicious [--exercise]`.

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

## USB macropad -> RF trigger (optional)

`keypad.py` turns a plugged-in 4-key USB macropad into a physical shortcut for the
dashboard's send button. It reads the pad with `evdev` and, on each keypress, POSTs to the
**local** collector's `/api/send` — so it reuses the collector's radio (no `/dev/ttyAMA0`
contention) and does exactly what clicking send in `fleet.html` does: broadcast over LoRa +
trip Kit 00's own Opta.

```
[pad key] --evdev--> keypad.py --POST /api/send--> collector --LoRa--> mesh
```

One-time bind (auto-discovers device + keycode — just press the key for each action):

```bash
sudo provision/keypad_service.sh          # python3-evdev + `input` group + install unit
sudo python3 central/keypad.py --learn    # press a key for: TEST / LOCK / reset / heartbeat
sudo systemctl enable --now smartmeter-keypad
journalctl -u smartmeter-keypad -f        # watch keypresses fire
```

The mapping saves to `/etc/smartmeter-keypad.json` (stable `by-id` device path). Runtime
**grabs** the pad exclusively so keystrokes don't leak to a console, and a per-action
cooldown (`--cooldown`, default 1.5 s) stops a bounce double-firing the payload. Rebind any
time with `--learn`, then `systemctl restart smartmeter-keypad`. `keypad.py --list` shows
input devices. Needs the collector running (it's the POST target).

## Status / TODO

- [x] Status beacon (`protocol.SMST`) + field-kit beaconing (`listener.py`, auto kit-id from `--host`).
- [x] Collector: aggregate beacons + local Kit 00 meter + dashboard/JSON.
- [x] **RF console** — `POST /api/send` + dashboard buttons broadcast TEST / LOCK / reset from
  Kit 00 to all in-range kits (shares the HAT with the RX loop; no service stop). New `reset` frame.
- [x] **RSSI** — `hat_config.py --rssi` enables the EBYTE RSSI-append bit on the central HAT;
  collector reads the trailing byte and reports dBm. Validated over the air (K09 ≈ −10…−32 dBm on the bench).
- [x] `smartmeter-collector.service` unit (this dir) — installed + enabled on the central
  node (`.100`); survives reboot, RX lines live in `journalctl`.
- [x] **Drone mule** — `scripts/datamule.py`: the drone buffers out-of-range kits' `SMST`
  beacons and re-emits them (version=2) so the collector resolves them as **"via mule"**.
- [x] **USB macropad -> RF trigger** — `keypad.py` (`--learn` binds keys) + `smartmeter-keypad.service`
  + `provision/keypad_service.sh`. Each key POSTs to `/api/send`. Code written; needs a pad to bench-test.
- [ ] Fold the central-node setup (HAT `--rssi`, this service, keypad) into provisioning.
