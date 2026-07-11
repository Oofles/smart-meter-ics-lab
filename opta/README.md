# opta/ — Opta smart-meter program

The Arduino Opta (AFX00003, Opta WiFi) runs the smart-meter simulation and serves
**Modbus TCP** at `192.168.1.210:502` (reference build; per kit it's `192.168.1.(200+kit#)` —
the IP host octet is stamped into the firmware at flash time via a `KITCFGv1` marker, so one
prebuilt `.bin` serves every kit; see `PROVISION.md`). See `docs/register-map.md` for the contract.

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
Every ~500 ms the sketch reads the inputs and drives an **operator HMI** per
`docs/register-map.md`. In normal state the blue team drives the four-light panel:
**I1 switch → O1 blue, I2 switch → O2 green, dial past 6 (of 0–10) → O3 yellow**, plus
`POWER_STATUS=1`, dial-driven `VOLTAGE_X10`, random-walk `POWER_W`. A delivered malicious
update (`FW_MODE!=0`, **via Modbus write / the RF payload — there is no local trip switch**)
faults the meter: O1/O2/O3 off, **O4 red on**, `VOLTAGE_X10`/`POWER_W`→0. Two modes: **`FW_MODE=1`
TEST** — the `RESET` coil or I3 button clears it and the panel resumes; **`FW_MODE=2` EXERCISE LOCK**
— RESET is ignored and the fault persists across a power-cycle (saved to Opta flash), cleared only by
a direct `FW_MODE:=0` write (`scripts/mb_unlock.py`). The four lamp states and the I1/I2 switch
positions are mirrored to Modbus discrete inputs 0..5 for SCADA.

## Physical I/O (plccable trainer)

| Signal | Opta pin | Notes |
|--------|----------|-------|
| O1 blue / **O2 green** / O3 yellow / **O4 red** | `D0`/`D1`/`D2`/`D3` | relays; need 12–24 V supply to switch |
| I1 blue-light switch | `A0` | analog read, threshold ~2000/4095 → O1 |
| I2 green-light switch | `A1` | analog read → O2 |
| I3 reset button | `A2` | analog read |
| I5 voltage dial | `A4` | analog read → `VOLTAGE_X10`; ≥ 6 V → O3 yellow |
| STATUS LED 1 | `LED_D0` | mirrors POWER_STATUS; works on USB power |

> Read inputs as **analog + threshold**, not `digitalRead` — `digitalRead` on these 0–10 V
> pins reads HIGH even at 0 V.

## Flash it

One-time libs:

```
arduino-cli core install arduino:mbed_opta
arduino-cli lib install ArduinoModbus ArduinoRS485 Arduino_KVStore
```

> `Arduino_KVStore` persists the **exercise-lock** flag to Opta flash so a locked meter
> (`FW_MODE=2`) stays faulted across a power-cycle — see `docs/register-map.md` ("Attack modes").

Build + upload (Opta on USB; port is the lower/sketch COM port, e.g. COM4):

```
arduino-cli compile --fqbn arduino:mbed_opta:opta opta/smart_meter
arduino-cli upload  --fqbn arduino:mbed_opta:opta -p COM4 opta/smart_meter
```

Uploading replaces whatever is on the board (including any PLC IDE runtime). To restore the
factory demo, see `opta/backup/README.md`.

## Verify (from the Pi / any host on the LAN)

```
python3 scripts/mb_read.py         # live state
python3 scripts/mb_trip.py         # inject FW_MODE=1 (TEST trip) -> fault
python3 scripts/mb_reset.py        # operator reset -> normal (clears TEST only)
python3 scripts/mb_trip.py --lock  # inject FW_MODE=2 (EXERCISE LOCK) -> fault, RESET disabled
python3 scripts/mb_unlock.py       # facilitator unlock (FW_MODE:=0) -> clears TEST or LOCK
```

## Tuning

- **Voltage scale:** `VOLTAGE_X10 = dial_volts * 240` (dial 0–10 V → 0–240.0 V; mid-dial ≈
  120 V). Change the `* 240.0f` factor in `applyNormal()` for a different range.
- **Yellow threshold:** `DIAL_YELLOW_V = 6.0f` — the dial voltage at which O3 lights.
- **Input threshold / power band / jitter:** constants near the top of the sketch.
- Diagnostic holding regs 20–23 expose raw I1/I3/dial/I2 ADC counts; discrete inputs 0–5
  mirror the four lamps + the two switch positions.
