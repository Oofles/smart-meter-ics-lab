# Modbus Register Map (contract)

**This file is the single source of truth for the Opta <-> everything interface.**
Any change to an address, type, or scaling must update this file and every consumer
(Opta program, SCADA-LTS data points, listener) in the same commit.

## Server

- Device: Arduino Opta PLC, acting as **Modbus TCP server**.
- IP: `192.168.1.10` (static) — adjust to your bench subnet, keep it static.
- Port: `502`
- Unit / slave ID: `1`

## Points

| Type          | Address | Name         | Type/Scale        | R/W by SCADA | Written by | Meaning                                             |
|---------------|---------|--------------|-------------------|--------------|------------|-----------------------------------------------------|
| Coil          | 00001   | POWER_STATUS | bit               | read         | Opta       | 1 = powered (green indicator), 0 = fault (red)      |
| Holding Reg   | 40001   | VOLTAGE_X10  | uint16, volts x10 | read         | Opta       | 1200 = 120.0 V. 0 in fault state.                   |
| Holding Reg   | 40002   | POWER_W      | uint16, watts     | read         | Opta       | Instantaneous usage. 0 in fault state.              |
| Holding Reg   | 40010   | FW_MODE      | uint16            | (read)       | listener   | 0 = normal firmware, 1 = malicious ("updated")      |
| Coil          | 00016   | RESET        | bit               | write        | ops        | Write 1 to clear fault: sets FW_MODE back to 0      |

> Addressing note: names use conventional 1-based Modbus references (4xxxx = holding
> registers, 0xxxx = coils). In zero-based client libraries (e.g. pymodbus) subtract 1:
> VOLTAGE_X10 = holding register index 0, POWER_W = index 1, FW_MODE = index 9;
> POWER_STATUS = coil index 0, RESET = coil index 15. Confirm against your Opta mapping
> and pin the convention in `opta/` once verified.

## Opta behavior logic

```
each scan:
  if RESET coil == 1:
      FW_MODE := 0
      RESET   := 0            # self-clear

  if FW_MODE == 0:            # normal firmware
      POWER_STATUS := 1
      VOLTAGE_X10  := 1200 +/- small jitter   # ~119.x–120.x V
      POWER_W      := random-walk around a baseline (e.g. 300–1500 W)
  else:                       # FW_MODE == 1, "malicious firmware"
      POWER_STATUS := 0
      VOLTAGE_X10  := 0
      POWER_W      := 0
      # optional physical effect: HMI red / buzzer
```

## Consumers

- **SCADA-LTS**: Modbus IP data source -> data points for POWER_STATUS, VOLTAGE_X10
  (render /10), POWER_W. Poll ~1 s so the meter visibly moves and visibly collapses.
- **Listener**: on a recognized "malicious update" payload, write `FW_MODE = 1`.
  On a benign update/heartbeat, write `FW_MODE = 0` (or no-op).
- **Reset**: bind RESET to a button/script to re-arm the demo between runs.
