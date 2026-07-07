# opta/ — Opta PLC program (Phase 1)

Smart-meter simulation + Modbus TCP server for the Arduino Opta.

- Author in the **Arduino PLC IDE** (Windows), IEC 61131-3.
- Implement the behavior logic in `../docs/register-map.md`.
- Enable the Modbus TCP server; set a static IP (default `192.168.1.10`), unit ID `1`.
- Wire the HMI board to mirror POWER_STATUS (green/red); optional buzzer on fault.

Document here once built: exact IP/unit ID, register-to-variable mapping (confirm the
0- vs 1-based convention), and flashing steps.
