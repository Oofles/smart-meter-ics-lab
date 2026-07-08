"""Tiny dependency-free Modbus TCP client for the smart-meter Opta.

Pure standard-library (sockets) so it runs on the Pi/Kali without pymodbus.
0-based PDU addressing. See docs/register-map.md.
"""
import socket
import struct

DEFAULT_HOST = "192.168.1.210"
DEFAULT_PORT = 502
DEFAULT_UNIT = 1


def _txn(pdu, host, port, unit):
    mbap = struct.pack(">HHHB", 1, 0, len(pdu) + 1, unit)
    with socket.create_connection((host, port), timeout=3) as s:
        s.sendall(mbap + pdu)
        head = _recvn(s, 7)                      # MBAP: tid, pid, len, unit
        _, _, length, _ = struct.unpack(">HHHB", head)
        resp = _recvn(s, length - 1)             # PDU: fc + data
    fc, data = resp[0], resp[1:]
    if fc & 0x80:
        raise IOError("Modbus exception code %d" % data[0])
    return data


def _recvn(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise IOError("connection closed by peer")
        buf += chunk
    return buf


def read_holding(addr, count=1, host=DEFAULT_HOST, port=DEFAULT_PORT, unit=DEFAULT_UNIT):
    data = _txn(struct.pack(">BHH", 3, addr, count), host, port, unit)
    bc = data[0]
    return list(struct.unpack(">%dH" % (bc // 2), data[1:1 + bc]))


def read_coils(addr, count=1, host=DEFAULT_HOST, port=DEFAULT_PORT, unit=DEFAULT_UNIT):
    data = _txn(struct.pack(">BHH", 1, addr, count), host, port, unit)
    return [(data[1 + i // 8] >> (i % 8)) & 1 for i in range(count)]


def write_register(addr, value, host=DEFAULT_HOST, port=DEFAULT_PORT, unit=DEFAULT_UNIT):
    _txn(struct.pack(">BHH", 6, addr, value & 0xFFFF), host, port, unit)


def write_coil(addr, on, host=DEFAULT_HOST, port=DEFAULT_PORT, unit=DEFAULT_UNIT):
    _txn(struct.pack(">BHH", 5, addr, 0xFF00 if on else 0x0000), host, port, unit)
