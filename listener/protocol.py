"""'Firmware update' frame for the smart-meter RF update channel.

Deliberately firmware-shaped (magic + version + type + CRC16) so the exercise
teaches integrity/authenticity: the listener 'validates' the CRC, but the RF
channel is unauthenticated — anyone can forge a valid-looking malicious update.
See docs/register-map.md (FW_MODE) and CLAUDE.md.

Frame (8 bytes):  b"SMFW" | version(1) | type(1) | crc16-ccitt(2, big-endian)
"""
import struct

MAGIC = b"SMFW"
TYPE_BENIGN = 0x00      # normal firmware / version heartbeat
TYPE_MALICIOUS = 0x01   # the "malicious firmware update"


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build(fw_type: int, version: int = 1) -> bytes:
    body = MAGIC + bytes([version & 0xFF, fw_type & 0xFF])
    return body + struct.pack(">H", crc16(body))


def parse(frame: bytes):
    """-> (valid, fw_type, version). valid=False on bad magic or failed CRC."""
    frame = frame.rstrip(b"\r\n")
    if len(frame) < 8 or frame[:4] != MAGIC:
        return (False, None, None)
    body, chk = frame[:6], frame[6:8]
    if struct.unpack(">H", chk)[0] != crc16(body):
        return (False, None, None)
    return (True, frame[5], frame[4])
