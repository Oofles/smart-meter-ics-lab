# scripts/ — Modbus helpers (Phase 2+)

Bench utilities to validate the Opta over Modbus (read / trip / reset / unlock):

- `mb_read.py`   — read POWER_STATUS / VOLTAGE_X10 / POWER_W
- `mb_trip.py`   — write FW_MODE=1 (simulate applied malicious update)
- `mb_reset.py`  — write RESET=1 (clear fault, re-arm)
- `mb_unlock.py` — write FW_MODE=0 (facilitator "re-flash": clears an EXERCISE LOCK)

Keep these dependency-light (the stdlib `mb.py` client) so they run anywhere on the bench.

## RF monitor (needs the LoRa HAT)

- `rf_sniff.py` — passive channel monitor: decode SMFW updates + SMST status beacons with
  timestamps; **transmits nothing**. Run it on the **drone** to see what an injection did
  (target kits' beacons flip to `FW_MODE=1`), or anywhere to watch fleet RF. `--rssi` parses
  the appended RSSI byte if this HAT was set with `hat_config.py --rssi`. Deps: pyserial, lgpio.
