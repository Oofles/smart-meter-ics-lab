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
- IP: `192.168.1.210` (static, set in the sketch via `Ethernet.begin`)
- Port: `502`
- Unit / slave ID: the server answers **any** unit ID (ArduinoModbus TCP default). Clients
  may use `1`.

## Points

Addresses below are **0-based Modbus PDU addresses** (what the sketch and most client
libraries use). Conventional entity numbers are shown for reference; note `mbpoll` uses
**1-based** references, so `mbpoll -r <PDU+1>`.

| Type        | PDU addr | Entity | Name         | Type/Scale        | R/W by SCADA | Written by | Meaning                                   |
|-------------|----------|--------|--------------|-------------------|--------------|------------|-------------------------------------------|
| Coil        | 0        | 000001 | POWER_STATUS | bit               | read         | Opta       | 1 = powered (green), 0 = fault (red)      |
| Coil        | 15       | 000016 | RESET        | bit               | write        | ops        | write 1 to clear fault (sets FW_MODE=0)   |
| Holding Reg | 0        | 400001 | VOLTAGE_X10  | uint16, volts x10 | read         | Opta       | live voltage (dial-driven); 0 in fault    |
| Holding Reg | 1        | 400002 | POWER_W      | uint16, watts     | read         | Opta       | instantaneous usage; 0 in fault           |
| Holding Reg | 9        | 400010 | FW_MODE      | uint16            | (read)       | listener   | 0 = normal, !=0 = malicious ("updated")   |

### Diagnostics (raw ADC counts, 12-bit 0..4095) — for bring-up/SCADA debug

| Type        | PDU addr | Name       | Meaning                                  |
|-------------|----------|------------|------------------------------------------|
| Holding Reg | 20       | RAW_TRIP   | analogRead(I1) — local trip switch input |
| Holding Reg | 21       | RAW_RESET  | analogRead(I3) — local reset button input|
| Holding Reg | 22       | RAW_DIAL   | analogRead(I5) — the voltage dial        |

External `FC06`/`FC16` writes to `FW_MODE` and `FC05` writes to `RESET` are reflected back
into the sketch and drive the trip/reset — verified with `mbpoll` from the Pi.

## Sketch behavior logic

```
every ~500 ms:
  read analog inputs (I1 trip, I3 reset, I5 dial); publish raw counts to diag regs
  if RESET coil == 1  OR  I3 button > threshold:
      FW_MODE := 0 ; RESET coil := 0            # self-clear, re-arm
  if I1 switch > threshold:                     # local "malicious update"
      FW_MODE := 1

  if FW_MODE == 0:            # normal firmware
      POWER_STATUS := 1
      VOLTAGE_X10  := dial (0..10 V -> 0..240.0 V x10) + small jitter
      POWER_W      := random-walk in [300, 1500] W
      lamps: green on, red off, blue "alive"
  else:                       # FW_MODE != 0, "malicious firmware"
      POWER_STATUS := 0 ; VOLTAGE_X10 := 0 ; POWER_W := 0
      lamps: green off, red on
```

## Physical layer (Opta trainer I/O, driven by the sketch)

- **Relay outputs:** O1=`D0` blue, **O2=`D1` green**, O3=`D2` yellow, **O4=`D3` red**.
  (Relays only switch when the Opta is on its **12–24 V supply**, not USB power; the onboard
  STATUS LED 1 (`LED_D0`) mirrors POWER_STATUS and works on USB.)
- **Inputs (read as analog, threshold ~2000/4095 ≈ 5.3 V):** I1=`A0` trip switch (local
  fault), I3=`A2` reset button, I5=`A4` voltage dial. `digitalRead` on these 0–10 V pins is
  unreliable — always read analog + threshold.

## Consumers

- **SCADA-LTS**: Modbus IP data source -> POWER_STATUS (coil 0), VOLTAGE_X10 (hreg 0, /10),
  POWER_W (hreg 1). Poll ~1 s.
- **Listener**: on a recognized malicious payload, write `FW_MODE := 1` (FC06, hreg 9).
- **Reset**: write `RESET := 1` (FC05, coil 15), or press the I3 button, to re-arm.
