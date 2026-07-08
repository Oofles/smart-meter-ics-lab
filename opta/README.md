# opta/ — Opta smart-meter program

The Arduino Opta (AFX00003, Opta WiFi) runs the smart-meter simulation and serves
**Modbus TCP** at `192.168.1.210:502`. See `docs/register-map.md` for the contract.

- `smart_meter/smart_meter.ino` — the program (see "Why a sketch" below).
- `backup/` — DFU image of the factory/preloaded firmware + restore runbook.

## Why a sketch (not the PLC IDE / IEC 61131-3)

The plan originally targeted the Arduino PLC IDE. On this bench the PLC IDE's **online
link would not connect** — it crashed on Connect across **1.0.8, 1.1.0, and the plccable-
bundled 1.0.6**, as Administrator, on the correct (higher) Modbus COM port, and even with
a known-good plccable sample project. Since the PLC IDE can only deploy PLC code over that
online link, it was a hard blocker. We pivoted to a plain **Arduino sketch flashed over
USB** with `arduino-cli` — the USB path was 100% reliable all along (it's how the factory
backup was pulled). The rig is functionally identical: same Modbus contract, same
`FW_MODE` trip scenario.

## Behavior

`arduino:mbed_opta` core + `ArduinoModbus` (`ModbusTCPServer`) + `ArduinoRS485`.
Every ~500 ms the sketch reads the inputs and drives state per `docs/register-map.md`:
normal → `POWER_STATUS=1`, dial-driven `VOLTAGE_X10`, random-walk `POWER_W`, green lamp;
`FW_MODE!=0` (via Modbus write or the local I1 switch) → fault: everything 0, red lamp;
`RESET` coil or the I3 button clears it.

## Physical I/O (plccable trainer)

| Signal | Opta pin | Notes |
|--------|----------|-------|
| O1 blue / **O2 green** / O3 yellow / **O4 red** | `D0`/`D1`/`D2`/`D3` | relays; need 12–24 V supply to switch |
| I1 trip switch | `A0` | analog read, threshold ~2000/4095 |
| I3 reset button | `A2` | analog read |
| I5 voltage dial | `A4` | analog read → `VOLTAGE_X10` |
| STATUS LED 1 | `LED_D0` | mirrors POWER_STATUS; works on USB power |

> Read inputs as **analog + threshold**, not `digitalRead` — `digitalRead` on these 0–10 V
> pins reads HIGH even at 0 V.

## Flash it

One-time libs:

```
arduino-cli core install arduino:mbed_opta
arduino-cli lib install ArduinoModbus ArduinoRS485
```

Build + upload (Opta on USB; port is the lower/sketch COM port, e.g. COM4):

```
arduino-cli compile --fqbn arduino:mbed_opta:opta opta/smart_meter
arduino-cli upload  --fqbn arduino:mbed_opta:opta -p COM4 opta/smart_meter
```

Uploading replaces whatever is on the board (including any PLC IDE runtime). To restore the
factory demo, see `opta/backup/README.md`.

## Verify (from the Pi / any host on the LAN)

```
python3 scripts/mb_read.py     # live state
python3 scripts/mb_trip.py     # inject FW_MODE=1  -> fault
python3 scripts/mb_reset.py    # clear -> normal
```

## Tuning

- **Voltage scale:** `VOLTAGE_X10 = dial_volts * 240` (dial 0–10 V → 0–240.0 V; mid-dial ≈
  120 V). Change the `* 240.0f` factor in `applyNormal()` for a different range.
- **Input threshold / power band / jitter:** constants near the top of the sketch.
- Diagnostic holding regs 20–22 expose raw I1/I3/dial ADC counts.
