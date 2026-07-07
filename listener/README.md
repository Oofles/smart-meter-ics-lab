# listener/ — RF update service (Phase 5)

One Pi-side service: LoRa (serial) + Zigbee (MQTT) -> Modbus write of FW_MODE.

- LoRa: SX1262 HAT on `/dev/ttyAMA0` (enable serial hardware, disable login shell).
- Zigbee: Sonoff dongle -> Zigbee2MQTT + Mosquitto -> subscribe to the topic.
- Malicious payload -> `FW_MODE=1`; benign heartbeat -> `FW_MODE=0` (or no-op).
- Optional: firmware-shaped payload (magic bytes, version header, checksum) to teach
  update-integrity failure.

Python deps: pymodbus, pyserial, paho-mqtt.
