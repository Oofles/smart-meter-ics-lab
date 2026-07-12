#!/usr/bin/env python3
"""RF update listener + LoRa flood mesh: propagate a firmware update across meters.

Replicates the AMI / smart-meter attack: a "drone" injects a malicious firmware
update near ONE node; every node that hears it (a) applies it locally
(FW_MODE=1 -> trips its own meter over Modbus) and (b) rebroadcasts it, so the
update floods hop-by-hop to every reachable meter over LoRa.

Flood layer: each frame carries a msg_id (dedup — act/relay once) and a ttl
(hop limit). Runs on the existing UART SX1262 HATs in transparent (broadcast)
mode — no Meshtastic, no new hardware.

  ./listener.py                          # be a mesh node: receive, apply, relay
  ./listener.py --send malicious         # inject a TEST update (drone) — operator RESET clears it
  ./listener.py --send malicious --exercise  # inject an EXERCISE LOCK — RESET disabled, persists
  ./listener.py --send benign
  ./listener.py --simulate malicious     # NO radio: exercise apply+relay logic
"""
import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import mb            # pure-stdlib Modbus TCP client (no deps)
import protocol

HREG_FW_MODE = 9
DEFAULT_TTL = 3
BEACON_SEC = 20      # status-beacon heartbeat (plus jitter); also beacons on state change
BEACON_JITTER = 8
_seen = set()        # msg_ids already applied / relayed by this node


def derive_kit_id(host):
    """Kit number from the Opta IP: 192.168.1.(200+N) -> N; else 0 (override with --kit)."""
    try:
        octet = int(host.rsplit(".", 1)[1])
        return octet - 200 if 1 <= octet - 200 <= 99 else 0
    except (ValueError, IndexError):
        return 0


def consume_updates(buf, host, lora):
    """Process complete SMFW update frames in buf, resyncing on the magic so status
    beacons (SMST) and any garbage are skipped without misaligning the parser."""
    while True:
        i = buf.find(protocol.MAGIC)
        if i < 0:
            return buf[-3:] if len(buf) > 3 else buf   # keep a possible partial magic
        if len(buf) - i < protocol.FRAME_LEN:
            return buf[i:]                              # wait for the rest of the frame
        on_frame(buf[i:i + protocol.FRAME_LEN], host, lora=lora)
        buf = buf[i + protocol.FRAME_LEN:]


def apply_update(info, host):
    t = info["fw_type"]
    if t == protocol.TYPE_MALICIOUS:
        fw, note = 1, "FW_MODE=1 (TEST trip — operator RESET clears it)"
    elif t == protocol.TYPE_MALICIOUS_LOCK:
        fw, note = 2, "FW_MODE=2 (EXERCISE LOCK — operator RESET disabled)"
    elif t == protocol.TYPE_RESET:
        # facilitator recovery over RF: force FW_MODE:=0, clearing TEST *and* LOCK
        print("    APPLY: RESET update v%d -> FW_MODE=0 (recover — clears TEST and LOCK)" % info["version"])
        try:
            mb.write_register(HREG_FW_MODE, 0, host=host)
        except Exception as e:
            print("    (Modbus write failed: %s)" % e)
        return
    else:
        print("    benign firmware/heartbeat v%d — no-op" % info["version"])
        return
    print("    APPLY: malicious update v%d -> %s" % (info["version"], note))
    try:
        mb.write_register(HREG_FW_MODE, fw, host=host)
    except Exception as e:
        print("    (Modbus write failed: %s)" % e)


def on_frame(frame, host, lora=None):
    info = protocol.parse(frame)
    if not info.get("valid"):
        print("  drop — bad magic/CRC:", frame.hex(" "))
        return
    mid = info["msg_id"]
    if mid in _seen:
        print("  drop — already seen msg_id=0x%04X (dedup)" % mid)
        return
    _seen.add(mid)
    print("  RX update msg_id=0x%04X ttl=%d type=%d" % (mid, info["ttl"], info["fw_type"]))
    apply_update(info, host)
    # flood: rebroadcast to neighbours if hops remain
    if info["ttl"] > 1 and lora is not None:
        time.sleep(random.uniform(0.05, 0.25))       # jitter to avoid collisions
        relay = protocol.build(info["fw_type"], mid, info["ttl"] - 1, info["version"])
        lora.send(relay)
        print("    RELAY: rebroadcast msg_id=0x%04X ttl=%d" % (mid, info["ttl"] - 1))
    elif info["ttl"] <= 1:
        print("    (ttl exhausted — not relayed)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=mb.DEFAULT_HOST, help="this node's Opta Modbus host")
    ap.add_argument("--send", choices=["malicious", "benign", "reset"], help="inject an update over LoRa (the drone); 'reset' = facilitator recovery (FW_MODE:=0 everywhere)")
    ap.add_argument("--ttl", type=int, default=DEFAULT_TTL, help="hop limit for --send")
    ap.add_argument("--exercise", action="store_true",
                    help="with malicious --send/--simulate: EXERCISE LOCK (FW_MODE=2 — operator RESET "
                         "disabled; clear only with a direct FW_MODE:=0 write). Default is TEST.")
    ap.add_argument("--simulate", choices=["malicious", "benign", "reset"], help="exercise apply+relay logic, no radio")
    ap.add_argument("--kit", type=int, default=None, help="this node's kit id for status beacons (default: from --host)")
    args = ap.parse_args()

    def fw_type(kind):
        if kind == "malicious":
            return protocol.TYPE_MALICIOUS_LOCK if args.exercise else protocol.TYPE_MALICIOUS
        if kind == "reset":
            return protocol.TYPE_RESET
        return protocol.TYPE_BENIGN

    # --simulate needs no hardware: it drives parse -> apply (-> relay is logged).
    if args.simulate:
        t = fw_type(args.simulate)
        frame = protocol.build(t, random.randint(0, 0xFFFF), args.ttl)
        print("simulated received frame:", frame.hex(" "))
        on_frame(frame, args.host, lora=None)
        return

    from lora import LoRaHAT
    lora = LoRaHAT()
    try:
        if args.send:
            t = fw_type(args.send)
            mid = random.randint(0, 0xFFFF)
            frame = protocol.build(t, mid, args.ttl)
            _seen.add(mid)                            # don't relay our own injection
            print("INJECT (drone) msg_id=0x%04X ttl=%d:" % (mid, args.ttl), frame.hex(" "))
            lora.send(frame)
            time.sleep(0.2)
            return
        kit_id = args.kit if args.kit is not None else derive_kit_id(args.host)
        print("mesh node K%02d: listening on LoRa (%s), beaconing status ttl=1 — Ctrl-C to stop"
              % (kit_id, lora.ser.port))
        buf = b""
        last_fw = None
        next_beacon = 0.0
        while True:
            now = time.monotonic()
            try:
                fw = mb.read_holding(HREG_FW_MODE, host=args.host)[0]
            except Exception:
                fw = last_fw if last_fw is not None else 0
            # beacon on a heartbeat, and immediately whenever our state changes
            if fw != last_fw or now >= next_beacon:
                lora.send(protocol.build_status(kit_id, fw))
                if last_fw is not None and fw != last_fw:
                    print("  BEACON K%02d: state change -> FW_MODE=%d" % (kit_id, fw))
                last_fw = fw
                next_beacon = now + BEACON_SEC + random.uniform(0, BEACON_JITTER)
            chunk = lora.read_frame()
            if chunk:
                buf += chunk
                buf = consume_updates(buf, args.host, lora)
            else:
                buf = b""                             # inter-frame gap -> drop partial
    except KeyboardInterrupt:
        pass
    finally:
        lora.close()


if __name__ == "__main__":
    main()
