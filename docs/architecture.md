# Architecture & Scenario

## Subsystems

1. **Opta PLC (the meter).** Runs a smart-meter simulation and a Modbus TCP server.
   Owns the physical-state registers (POWER_STATUS, VOLTAGE_X10, POWER_W) and reads
   FW_MODE to decide normal vs. fault behavior. Drives a **four-light operator HMI panel**
   (O1 blue, O2 green, O3 yellow, O4 red) the blue team configures via switches I1/I2 and
   the voltage dial; the lamp + switch states are mirrored to Modbus discrete inputs.

2. **RF update channel (the attack surface).** A LoRa HAT (serial) feeds a Pi-side
   listener. The listener treats inbound payloads as "firmware updates" and writes
   FW_MODE accordingly. The operator view is the Opta's **physical four-light panel**
   (subsystem 1) — there is no software HMI. POWER_STATUS/VOLTAGE/POWER_W are read over
   Modbus only for the central fleet dashboard.

3. **Central node (Kit 00, facilitator).** Aggregates every field kit's status beacons
   over RF and serves a live fleet dashboard for the red team (see `central/`).

## Kill chain (normal -> attack -> reset)

0. **Day-1 setup (blue team).** Operator switches I1/I2 on (blue + green lamps) and turns the
   voltage dial past 6 (yellow lamp) — verifying their meter's I/O works on the panel.
1. **Normal.** Opta: FW_MODE=0 -> POWER_STATUS=1, voltage ~120 V with jitter, usage
   walking. Panel: blue/green (operator) + yellow (dial) lit; red off.
2. **Delivery.** Attacker transmits a malicious "firmware update" over LoRa. The same
   channel also carries benign version heartbeats — the point is that the channel
   is unauthenticated, not that traffic is inherently bad.
3. **Apply.** Listener decodes the payload, "applies the update," writes FW_MODE=1.
4. **Effect.** Opta latches fault: POWER_STATUS=0, voltage/usage=0, **all operator lamps off,
   red on** — even though the I1/I2 switches are still on (the attack overrides operator intent).
5. **Observe.** Panel: blue/green/yellow drop, red lights; voltage/usage drop to zero.
6. **Reset.** Ops writes RESET=1 -> FW_MODE=0 -> normal state; demo re-armed.

## Design decisions

- **"Modified firmware" = a mode register, not a reflash.** The Opta has no OTA path
  over LoRa and the radio lives on the Pi. Modeling the update as FW_MODE keeps
  the demo reliable and re-runnable while staying faithful to the lesson: an update
  channel with write access to OT can change physical process state.
- **Trip logic lives on the Opta.** The listener only sets FW_MODE; the Opta decides
  behavior. This means a direct-Modbus attacker (not just the RF path) can also trip the
  meter — a useful secondary attack path for the exercise.
- **Optional firmware-shaped payload.** Giving the payload magic bytes + a version header
  + a checksum the listener "validates" sharpens the integrity/supply-chain teaching
  point without adding real risk.

## Teaching points

- Unauthenticated / unvalidated update channels into OT.
- Update integrity (no signing/verification) as a supply-chain vector.
- Physical consequence of a logic/mode change in a controller.
- Blue-team detection: distinguishing benign heartbeats from the malicious update on the
  RF channel and on the Modbus write to FW_MODE.
