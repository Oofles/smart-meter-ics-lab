#!/usr/bin/env python3
"""rf_sniff.py — passive LoRa channel monitor for the drone / facilitator.

Decodes both frame types the fleet uses and logs each one with a timestamp:
  - SMFW firmware-update frames (the attack payload + its flood relays), and
  - SMST status beacons from field kits (kit_id + FW_MODE).
Read-only: it puts the HAT in transceive mode and reads — it TRANSMITS NOTHING, so
it's safe to run on the drone (or any kit) without disturbing the exercise.

Because the RF channel is a blind broadcast (no ACKs), this is the only way for the
DRONE to see what its injection actually did: run `listener.py --send malicious` and
watch the target kits' SMST beacons flip to FW_MODE=1 here. It's also the seed of the
"data-mule" idea — a drone that hears out-of-range kits' beacons and carries them back.

  sudo python3 scripts/rf_sniff.py            # listen until Ctrl-C
  sudo python3 scripts/rf_sniff.py 30         # listen 30 seconds, then print a summary
  sudo python3 scripts/rf_sniff.py --rssi     # also parse the appended RSSI byte
                                              #   (only if THIS HAT was set with hat_config.py --rssi;
                                              #    the plain-golden drone HAT does NOT append it)

Runs on the same UART SX1262 HAT as the listener (/dev/ttyAMA0). Deps: pyserial, lgpio.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "listener"))
import protocol
from lora import LoRaHAT

FW = {0: "OK/healthy", 1: "FW_MODE=1 TEST-trip", 2: "FW_MODE=2 EXERCISE-LOCK", 3: "reset"}
TYPE = {protocol.TYPE_BENIGN: "benign", protocol.TYPE_MALICIOUS: "malicious TEST",
        protocol.TYPE_MALICIOUS_LOCK: "malicious LOCK", protocol.TYPE_RESET: "reset"}


def rssi_dbm(b):
    """EBYTE appended-RSSI byte -> approx dBm."""
    return -(256 - b)


def main():
    ap = argparse.ArgumentParser(description="passive LoRa monitor (decode SMFW + SMST)")
    ap.add_argument("seconds", nargs="?", type=float, default=None,
                    help="listen this many seconds then summarize (default: until Ctrl-C)")
    ap.add_argument("--rssi", action="store_true",
                    help="parse the per-packet RSSI byte the HAT appends (only if configured with "
                         "hat_config.py --rssi; the plain drone HAT does not append it)")
    args = ap.parse_args()

    rssi_len = 1 if args.rssi else 0
    need_fw = protocol.FRAME_LEN + rssi_len
    need_st = protocol.STATUS_LEN + rssi_len

    lora = LoRaHAT()
    buf = b""
    kits = {}                      # kit_id -> (fw_mode, rssi)
    n_fw = 0
    t0 = time.monotonic()
    deadline = t0 + args.seconds if args.seconds else None
    span = ("%.0fs" % args.seconds) if args.seconds else "until Ctrl-C"
    print("rf_sniff: passive listen (%s) on %s%s — TX nothing"
          % (span, lora.ser.port, " [+RSSI]" if args.rssi else ""))
    try:
        while deadline is None or time.monotonic() < deadline:
            chunk = lora.read_frame()
            if not chunk:
                continue
            buf += chunk
            while buf:
                iu = buf.find(protocol.MAGIC)          # SMFW
                it = buf.find(protocol.MAGIC_STATUS)   # SMST
                cands = [x for x in (iu, it) if x >= 0]
                if not cands:
                    buf = buf[-3:]                     # keep a possible partial magic
                    break
                i = min(cands)
                if i > 0:                              # drop garbage before the magic
                    buf = buf[i:]
                    continue
                ts = time.monotonic() - t0
                if buf[:4] == protocol.MAGIC:          # ---- SMFW update ----
                    if len(buf) < need_fw:
                        break
                    info = protocol.parse(buf[:protocol.FRAME_LEN])
                    rssi = buf[protocol.FRAME_LEN] if args.rssi else None
                    buf = buf[need_fw:]
                    if info.get("valid"):
                        n_fw += 1
                        print("  %6.1fs  SMFW  %-14s msg_id=0x%04X ttl=%d%s"
                              % (ts, TYPE.get(info["fw_type"], "type%d" % info["fw_type"]),
                                 info["msg_id"], info["ttl"],
                                 "" if rssi is None else "  %d dBm" % rssi_dbm(rssi)))
                else:                                  # ---- SMST status beacon ----
                    if len(buf) < need_st:
                        break
                    info = protocol.parse_status(buf[:protocol.STATUS_LEN])
                    rssi = buf[protocol.STATUS_LEN] if args.rssi else None
                    buf = buf[need_st:]
                    if info.get("valid"):
                        k, fw = info["kit_id"], info["fw_mode"]
                        kits[k] = (fw, None if rssi is None else rssi_dbm(rssi))
                        print("  %6.1fs  SMST  K%02d -> %-22s%s"
                              % (ts, k, FW.get(fw, "?%d" % fw),
                                 "" if rssi is None else "  %d dBm" % rssi_dbm(rssi)))
    except KeyboardInterrupt:
        pass
    finally:
        lora.close()
    print("--- heard %d update frame(s); kits: %s" %
          (n_fw, ", ".join("K%02d=%s%s" % (k, FW.get(v[0], v[0]),
                                           "" if v[1] is None else "(%ddBm)" % v[1])
                           for k, v in sorted(kits.items())) or "NONE"))


if __name__ == "__main__":
    main()
