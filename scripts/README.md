# scripts/ — Modbus helpers (Phase 2+)

Bench utilities to validate the Opta over Modbus (read / trip / reset / unlock):

- `mb_read.py`  — read POWER_STATUS / VOLTAGE_X10 / POWER_W
- `mb_trip.py`  — write FW_MODE=1 (simulate applied malicious update)
- `mb_reset.py` — write RESET=1 (clear fault, re-arm)

Keep these dependency-light (pymodbus) so they run anywhere on the bench.
