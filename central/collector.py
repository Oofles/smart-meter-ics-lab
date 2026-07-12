#!/usr/bin/env python3
"""Central-node collector: the facilitator's fleet view.

Runs on the central node (Pi + SX1262 HAT + its own Opta = "Kit 00"). It:
  - listens on LoRa for STATUS beacons from the field kits (kit_id + FW_MODE), plus
    the RSSI the radio measured, and keeps a fleet table;
  - applies malicious update frames to its OWN local Opta (Kit 00) — so the central
    node is itself a valid attack target you can demo against in the room;
  - polls its local Opta over Modbus for the full Kit 00 meter (lamps/volts/watts);
  - serves the live dashboard (central/fleet.html) + a JSON feed at /api/fleet;
  - **transmits** payloads from Kit 00 to all in-range kits over LoRa via POST /api/send
    {"type": "malicious"|"malicious_lock"|"reset"|"benign", "ttl": 1} — the drone/console
    role, without stopping the collector (it shares the HAT with the RX loop).

  sudo python3 central/collector.py --host 192.168.1.200 --port 8090
    --host  this central node's own Opta (Kit 00) Modbus IP
    --port  dashboard/JSON port (default 8090)

Field kits run listener.py (which now beacons). Per-packet RSSI comes from the
central HAT's RSSI-append bit — configure this node's HAT with
`provision/hat_config.py --rssi` (field kits stay on plain golden).
"""
import argparse
import json
import os
import random
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "listener"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import mb
import protocol
import listener as fieldnode      # reuse on_frame (apply + dedup) for the central's own Opta

HREG_FW_MODE = 9
STALE_SEC = 45                    # no beacon within this -> "unknown" on the dashboard
N_KITS = 45
HERE = os.path.dirname(os.path.abspath(__file__))

_lock = threading.Lock()
_fleet = {}                       # kit_id -> {"fw":int, "rssi":int|None, "last":monotonic}
_central_meter = {"present": False}
_args = None
_lora = None                      # the HAT, shared by the RX loop and the /api/send TX
_lora_lock = threading.Lock()     # serialize HAT access (RX read vs. facilitator TX)

# facilitator TX from Kit 00 — payloads the console can broadcast to all in-range kits
SEND_TYPES = {
    "malicious": protocol.TYPE_MALICIOUS,        # TEST trip  (operator RESET clears)
    "malicious_lock": protocol.TYPE_MALICIOUS_LOCK,  # EXERCISE LOCK (RESET disabled)
    "reset": protocol.TYPE_RESET,                # facilitator recovery (FW_MODE:=0)
    "benign": protocol.TYPE_BENIGN,              # version heartbeat (no-op)
}


def fw_state(fw):
    return {0: "normal", 1: "test", 2: "locked"}.get(fw, "unknown")


# ---------------------------------------------------------------- RF receive
def rssi_from_byte(b):
    """EBYTE appended-RSSI byte -> dBm (approx)."""
    return -(256 - b)


def rf_loop(lora):
    buf = b""
    while True:
        with _lora_lock:          # share the HAT with facilitator TX (/api/send)
            chunk = lora.read_frame()
        if not chunk:
            buf = b""             # inter-packet gap -> drop any partial
            continue
        buf += chunk
        buf = _consume(buf, lora)


def transmit(kind, ttl=1):
    """Facilitator broadcast from Kit 00: send a payload to every in-range kit over LoRa,
    and apply it to our own Opta too (Kit 00 is a node). ttl>1 floods via relays to kits
    out of direct range. Returns a small result dict for the /api/send caller."""
    t = SEND_TYPES[kind]
    ttl = max(1, min(int(ttl), 8))
    mid = random.randint(0, 0xFFFF)
    frame = protocol.build(t, mid, ttl)
    fieldnode._seen.add(mid)                                  # ignore our own frame if it echoes
    fieldnode.apply_update(protocol.parse(frame), _args.host)  # apply to Kit 00's Opta (no relay)
    with _lora_lock:
        _lora.send(frame)
    print("  TX %s ttl=%d msg_id=0x%04X -> broadcast to all in-range kits" % (kind, ttl, mid))
    return {"ok": True, "type": kind, "ttl": ttl, "msg_id": mid}


def _consume(buf, lora):
    while buf:
        iu = buf.find(protocol.MAGIC)          # SMFW (attack)
        it = buf.find(protocol.MAGIC_STATUS)   # SMST (status beacon)
        cands = [x for x in (iu, it) if x >= 0]
        if not cands:
            return buf[-3:]                     # keep a possible partial magic
        i = min(cands)
        if i > 0:
            buf = buf[i:]
            continue
        if buf[:4] == protocol.MAGIC:
            if len(buf) < protocol.FRAME_LEN:
                return buf
            # apply attack frames to the central's own Opta (Kit 00); don't relay
            fieldnode.on_frame(buf[:protocol.FRAME_LEN], _args.host, lora=None)
            buf = buf[protocol.FRAME_LEN:]
        else:                                   # SMST status beacon
            if len(buf) < protocol.STATUS_LEN:
                return buf
            frame = buf[:protocol.STATUS_LEN]
            buf = buf[protocol.STATUS_LEN:]
            rssi = None                          # optional trailing RSSI byte (if HAT appends it)
            if len(buf) == 1 or (len(buf) >= 1 and buf[:1] != b"S"):
                rssi = rssi_from_byte(buf[0])
                buf = buf[1:]
            _record_status(frame, rssi)
    return buf


def _record_status(frame, rssi):
    info = protocol.parse_status(frame)
    if not info.get("valid"):
        return
    kid = info["kit_id"]
    if kid == 0 or kid > N_KITS:
        return
    with _lock:
        _fleet[kid] = {"fw": info["fw_mode"], "rssi": rssi, "last": time.monotonic()}
    print("  RX beacon K%02d FW_MODE=%d%s" %
          (kid, info["fw_mode"], "" if rssi is None else " %d dBm" % rssi))


# ---------------------------------------------------------------- local Opta (Kit 00)
def central_loop():
    while True:
        try:
            host = _args.host
            ps = mb.read_coils(0, 1, host=host)[0]
            v = mb.read_holding(0, 1, host=host)[0]
            w = mb.read_holding(1, 1, host=host)[0]
            fw = mb.read_holding(HREG_FW_MODE, 1, host=host)[0]
            lamps = mb.read_discrete_inputs(0, 4, host=host)
            sw = mb.read_discrete_inputs(4, 2, host=host)
            with _lock:
                _central_meter.clear()
                _central_meter.update({
                    "present": True, "fw": fw, "power": int(ps),
                    "voltage": round(v / 10.0, 1), "watts": w,
                    "lamps": {"blue": bool(lamps[0]), "green": bool(lamps[1]),
                              "yellow": bool(lamps[2]), "red": bool(lamps[3])},
                    "sw": {"blue": bool(sw[0]), "green": bool(sw[1])},
                    "last": time.monotonic(),
                })
        except Exception as e:
            with _lock:
                _central_meter["present"] = False
                _central_meter["error"] = str(e)
        time.sleep(1.5)


# ---------------------------------------------------------------- snapshot -> JSON
def node_json(kid, now):
    if kid == 0:
        with _lock:
            m = dict(_central_meter)
        if not m.get("present"):
            return {"id": 0, "central": True, "state": "unknown", "fw": None,
                    "rssi": None, "last": None, "meter": None}
        return {"id": 0, "central": True, "state": fw_state(m["fw"]), "fw": m["fw"],
                "rssi": None, "last": round(now - m["last"]), "meter": {
                    "power": m["power"], "voltage": m["voltage"], "watts": m["watts"],
                    "lamps": m["lamps"], "sw": m["sw"]}}
    with _lock:
        rec = _fleet.get(kid)
    if rec is None:
        return {"id": kid, "central": False, "state": "unknown", "fw": None,
                "rssi": None, "last": None, "meter": None}
    age = round(now - rec["last"])
    stale = age > STALE_SEC
    return {"id": kid, "central": False,
            "state": "unknown" if stale else fw_state(rec["fw"]),
            "fw": rec["fw"], "rssi": rec["rssi"], "last": age, "meter": None}


def snapshot():
    now = time.monotonic()
    return {"ts": time.time(), "stale_sec": STALE_SEC,
            "nodes": [node_json(k, now) for k in range(0, N_KITS + 1)]}


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/fleet"):
            self._send(200, "application/json", json.dumps(snapshot()).encode())
            return
        if self.path in ("/", "/index.html", "/fleet.html"):
            try:
                with open(os.path.join(HERE, "fleet.html"), "rb") as f:
                    self._send(200, "text/html; charset=utf-8", f.read())
            except OSError:
                self._send(500, "text/plain", b"fleet.html not found")
            return
        self._send(404, "text/plain", b"not found")

    def do_POST(self):
        # facilitator TX: broadcast a payload over LoRa to all in-range kits
        if self.path.rstrip("/") == "/api/send":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._send(400, "application/json", b'{"ok":false,"error":"bad json"}')
                return
            kind = body.get("type")
            if kind not in SEND_TYPES:
                self._send(400, "application/json",
                           json.dumps({"ok": False, "error": "unknown type %r" % kind}).encode())
                return
            try:
                res = transmit(kind, body.get("ttl", 1))
                self._send(200, "application/json", json.dumps(res).encode())
            except Exception as e:
                self._send(500, "application/json", json.dumps({"ok": False, "error": str(e)}).encode())
            return
        self._send(404, "text/plain", b"not found")


def main():
    global _args
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.1.200", help="this central node's own Opta (Kit 00) Modbus IP")
    ap.add_argument("--port", type=int, default=8090, help="dashboard/JSON port")
    _args = ap.parse_args()

    global _lora
    from lora import LoRaHAT
    _lora = LoRaHAT()
    threading.Thread(target=rf_loop, args=(_lora,), daemon=True).start()
    threading.Thread(target=central_loop, daemon=True).start()

    srv = ThreadingHTTPServer(("0.0.0.0", _args.port), Handler)
    print("collector: Kit 00 Opta %s | dashboard http://0.0.0.0:%d/ | listening for beacons"
          % (_args.host, _args.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _lora.close()


if __name__ == "__main__":
    main()
