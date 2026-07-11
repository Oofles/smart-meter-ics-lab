"""'Firmware update' frame for the smart-meter LoRa mesh update channel.

Firmware-shaped (magic + version + type + msg_id + ttl + CRC16) so the exercise
teaches integrity/authenticity — the listener 'validates' the CRC, but the RF
channel is unauthenticated, so anyone can forge a valid-looking malicious update.

The msg_id + ttl fields turn the raw LoRa broadcast into an application-layer
FLOOD MESH: an update injected at one node (the "drone" near a meter) is
rebroadcast hop-by-hop to every reachable meter (see listener.py). `msg_id` dedups
so a frame is acted on / relayed once; `ttl` bounds the hop count. Runs on the
existing UART SX1262 HATs (transparent/broadcast mode) — no Meshtastic needed.

Frame (11 bytes):
  b"SMFW" | version(1) | type(1) | msg_id(2 BE) | ttl(1) | crc16-ccitt(2 BE)
"""
import struct

MAGIC = b"SMFW"
TYPE_BENIGN = 0x00        # normal firmware / version heartbeat
TYPE_MALICIOUS = 0x01     # malicious update, TEST mode -> FW_MODE=1 (operator RESET clears it)
TYPE_MALICIOUS_LOCK = 0x02  # malicious update, EXERCISE mode -> FW_MODE=2 (locked; RESET ignored)
FRAME_LEN = 11


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build(fw_type: int, msg_id: int, ttl: int = 3, version: int = 1) -> bytes:
    body = (MAGIC + bytes([version & 0xFF, fw_type & 0xFF])
            + struct.pack(">H", msg_id & 0xFFFF) + bytes([ttl & 0xFF]))
    return body + struct.pack(">H", crc16(body))


def parse(frame: bytes) -> dict:
    """-> {valid, version, fw_type, msg_id, ttl}. valid=False on bad magic/CRC/len."""
    frame = frame.rstrip(b"\r\n")
    if len(frame) < FRAME_LEN or frame[:4] != MAGIC:
        return {"valid": False}
    body, chk = frame[:FRAME_LEN - 2], frame[FRAME_LEN - 2:FRAME_LEN]
    if struct.unpack(">H", chk)[0] != crc16(body):
        return {"valid": False}
    return {"valid": True, "version": frame[4], "fw_type": frame[5],
            "msg_id": struct.unpack(">H", frame[6:8])[0], "ttl": frame[8]}


# ---------------------------------------------------------------------------
# STATUS beacon — the reverse direction: each field kit periodically announces
# its own state so the central collector can build a fleet view. Distinct magic
# so field kits (which scan for SMFW) ignore each other's beacons; only the
# collector parses these. RSSI is NOT carried here — it's measured by the
# receiver (the collector) from the radio, not known to the sender.
#
# Frame (9 bytes):  b"SMST" | version(1) | kit_id(1) | fw_mode(1) | crc16(2 BE)
MAGIC_STATUS = b"SMST"
STATUS_LEN = 9


def build_status(kit_id: int, fw_mode: int, version: int = 1) -> bytes:
    body = MAGIC_STATUS + bytes([version & 0xFF, kit_id & 0xFF, fw_mode & 0xFF])
    return body + struct.pack(">H", crc16(body))


def parse_status(frame: bytes) -> dict:
    """-> {valid, version, kit_id, fw_mode}. valid=False on bad magic/CRC/len."""
    frame = frame[:STATUS_LEN]
    if len(frame) < STATUS_LEN or frame[:4] != MAGIC_STATUS:
        return {"valid": False}
    body, chk = frame[:STATUS_LEN - 2], frame[STATUS_LEN - 2:STATUS_LEN]
    if struct.unpack(">H", chk)[0] != crc16(body):
        return {"valid": False}
    return {"valid": True, "version": frame[4], "kit_id": frame[5], "fw_mode": frame[6]}
