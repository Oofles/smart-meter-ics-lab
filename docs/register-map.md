# Modbus Register Map (contract)

**This file is the single source of truth for the Opta <-> everything interface.**
Any change to an address, type, or scaling must update this file and every consumer
(Opta sketch, SCADA-LTS data points, listener) in the same commit.

## Server

- Device: Arduino Opta PLC (AFX00003, Opta WiFi), running an **Arduino sketch**
  (`opta/smart_meter/`, `arduino:mbed_opta` core) that serves **Modbus TCP**.
  > Implementation note: the Arduino PLC IDE (IEC 61131-3) was abandoned — its online
  > link would not connect on this bench across three IDE versions. The sketch is flashed
  > over USB with `arduino-cli` and is functionally identical for the exercise.
- IP: `192.168.1.210` on the reference build; **per kit it's `192.168.1.(200+kit#)`** — the host
  octet is stamped into the firmware at flash time via the `KITCFGv1` marker (see `PROVISION.md`),
  so one prebuilt `.bin` serves every kit. Static, set in the sketch via `Ethernet.begin`.
- Port: `502`
- Unit / slave ID: the server answers **any** unit ID (ArduinoModbus TCP default). Clients
  may use `1`.

## Points

Addresses below are **0-based Modbus PDU addresses** (what the sketch and most client
libraries use). Conventional entity numbers are shown for reference; note `mbpoll` uses
**1-based** references, so `mbpoll -r <PDU+1>`.

| Type        | PDU addr | Entity | Name         | Type/Scale        | R/W by SCADA | Written by | Meaning                                   |
|-------------|----------|--------|--------------|-------------------|--------------|------------|-------------------------------------------|
| Coil        | 0        | 000001 | POWER_STATUS | bit               | read         | Opta       | 1 = powered/healthy, 0 = faulted (attack) |
| Coil        | 15       | 000016 | RESET        | bit               | write        | ops        | operator reset: 1 clears a TEST trip (FW_MODE 1→0); **ignored when FW_MODE=2 (locked)** |
| Holding Reg | 0        | 400001 | VOLTAGE_X10  | uint16, volts x10 | read         | Opta       | live voltage (dial-driven); 0 in fault    |
| Holding Reg | 1        | 400002 | POWER_W      | uint16, watts     | read         | Opta       | instantaneous usage; 0 in fault           |
| Holding Reg | 9        | 400010 | FW_MODE      | uint16            | (read)       | listener   | 0=normal, 1=malicious TEST trip, 2=malicious EXERCISE LOCK (see below) |

### Panel mirror — discrete inputs (read-only bits the Opta drives, for the SCADA HMI)

Function 02 (Read Discrete Inputs). These let SCADA render the **same four-light panel**
the operator sees on the Opta, plus the physical switch positions. All are written by the
Opta, read-only to clients.

| Type           | PDU addr | Name        | Meaning                                             |
|----------------|----------|-------------|-----------------------------------------------------|
| Discrete Input | 0        | LAMP_BLUE   | O1 blue lamp state (1 = lit)                        |
| Discrete Input | 1        | LAMP_GREEN  | O2 green lamp state                                 |
| Discrete Input | 2        | LAMP_YELLOW | O3 yellow lamp state (dial past 6)                  |
| Discrete Input | 3        | LAMP_RED    | O4 red lamp state (1 = faulted/attack)              |
| Discrete Input | 4        | SW_BLUE     | I1 switch position (operator's blue-light request)  |
| Discrete Input | 5        | SW_GREEN    | I2 switch position (operator's green-light request) |

> Why mirror both switch **and** lamp: in normal state `LAMP_BLUE == SW_BLUE`, but during a
> fault the lamp is forced off while the switch may still read on — SCADA then shows the
> attack overriding operator intent.

### Diagnostics (raw ADC counts, 12-bit 0..4095) — for bring-up/SCADA debug

| Type        | PDU addr | Name       | Meaning                                    |
|-------------|----------|------------|--------------------------------------------|
| Holding Reg | 20       | RAW_BLUE   | analogRead(I1) — blue-light switch input   |
| Holding Reg | 21       | RAW_RESET  | analogRead(I3) — local reset button input  |
| Holding Reg | 22       | RAW_DIAL   | analogRead(I5) — the voltage dial          |
| Holding Reg | 23       | RAW_GREEN  | analogRead(I2) — green-light switch input  |

External `FC06`/`FC16` writes to `FW_MODE` and `FC05` writes to `RESET` are reflected back
into the sketch and drive the trip/reset — verified with `mbpoll` from the Pi.

## Sketch behavior logic

The panel is an **operator HMI**: in normal state the blue team drives the lights; a
delivered malicious update faults the meter and forces the red lamp.

```
every ~500 ms:
  read analog inputs (I1 blue switch, I2 green switch, I3 reset, I5 dial)
  publish raw counts to diag regs; publish SW_BLUE/SW_GREEN discrete inputs
  if RESET coil == 1  OR  I3 button > threshold:
      RESET coil := 0                                # always ack the coil
      if FW_MODE != 2: FW_MODE := 0                  # operator reset clears TEST (1), NOT LOCK (2)
  # NOTE: no local trip. The fault fires ONLY from FW_MODE (RF payload / listener /
  # direct Modbus write) — so a direct-Modbus attacker can also trigger it.

  # NOTE: FW_MODE is RAM only — a power-cycle clears even a LOCK. Flash-persisting the lock
  # across reboots is a planned follow-up (FlashIAP reserved sector).

  if FW_MODE == 0:            # normal — operator drives the panel
      POWER_STATUS := 1
      VOLTAGE_X10  := dial (0..10 V -> 0..240.0 V x10) + small jitter
      POWER_W      := random-walk in [300, 1500] W
      lamps: BLUE := I1 switch, GREEN := I2 switch, YELLOW := (dial >= 6 of 0..10), RED := off
  else:                       # FW_MODE 1 or 2 — "malicious firmware", meter faults (identical)
      POWER_STATUS := 0 ; VOLTAGE_X10 := 0 ; POWER_W := 0
      lamps: BLUE/GREEN/YELLOW := off, RED := on
  mirror the four lamp states to discrete inputs 0..3
```

### Attack modes (FW_MODE 1 vs 2)

Both fault the meter identically (red, zero); they differ only in **recovery**:

| FW_MODE | Mode | Injected by | Cleared by |
|---------|------|-------------|------------|
| 1 | **TEST** | `mb_trip.py` / `listener.py --send malicious` | operator RESET — coil 15 or the I3 button (`mb_reset.py`) |
| 2 | **EXERCISE LOCK** | `mb_trip.py --lock` / `listener.py --send malicious --exercise` | **only** a direct `FW_MODE := 0` write (`mb_unlock.py`) — the operator RESET (coil 15 / I3) is ignored |

The LOCK models "the malicious firmware can't be reset away" — the blue team's normal recovery
(RESET button / SCADA reset) does nothing; recovery needs the facilitator's out-of-band re-flash
(the direct `FW_MODE := 0`).

> **Persistence — RAM only for now.** The lock is not yet stored in non-volatile memory, so an
> Opta **power-cycle also clears it**. Flash-persisting it across reboots (so only the unlock
> recovers) is a planned follow-up — `Arduino_KVStore` hard-faults on this H7, so the intended
> mechanism is a reserved internal-flash sector via `FlashIAP`, validated on the bench first.

## Physical layer (Opta trainer I/O, driven by the sketch)

- **Relay outputs:** O1=`D0` blue, O2=`D1` green, O3=`D2` yellow, O4=`D3` red.
  (Relays only switch when the Opta is on its **12–24 V supply**, not USB power; the onboard
  STATUS LED 1 (`LED_D0`) mirrors POWER_STATUS and works on USB.)
- **Inputs (read as analog, threshold ~2000/4095 ≈ 5.3 V):** I1=`A0` blue-light switch,
  I2=`A1` green-light switch, I3=`A2` reset button, I5=`A4` voltage dial. `digitalRead` on
  these 0–10 V pins is unreliable — always read analog + threshold.
- **Yellow threshold:** the dial reads ~0..10.9 V; YELLOW lights at **≥ 6.0 V** (past 6 on
  the 0–10 dial).

## Consumers

- **SCADA-LTS**: Modbus IP data source ->
  - POWER_STATUS (coil 0), VOLTAGE_X10 (hreg 0, /10), POWER_W (hreg 1).
  - Panel mirror: LAMP_BLUE/GREEN/YELLOW/RED (discrete inputs 0..3), SW_BLUE/SW_GREEN
    (discrete inputs 4..5). Poll ~1 s.
- **Listener**: on a recognized malicious payload, write `FW_MODE` (FC06, hreg 9) — `1` for a
  TEST update, `2` for an EXERCISE-LOCK update (frame type byte selects which; see `protocol.py`).
- **Reset**: operator RESET — write `RESET := 1` (FC05, coil 15) or press I3 — clears a TEST trip
  only. **Unlock** (facilitator): write `FW_MODE := 0` (FC06, hreg 9) to clear either, LOCK included.
