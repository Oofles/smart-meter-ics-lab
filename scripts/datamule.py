#!/usr/bin/env python3
"""datamule.py — drone store-and-forward for out-of-range kit status.

The roaming drone hears field kits' SMST status beacons over LoRa. Kits far from the
central Kit 00 collector can't reach it directly, so their state never shows on the
fleet dashboard. This mule BUFFERS each kit's latest first-hand beacon and periodically
RE-EMITS it (marked relayed — version=2) so that whenever the drone passes within range
of Kit 00, the collector picks up those otherwise-invisible kits.

  drone hears  K33 -> FW_MODE=1   (K33 is out of Kit 00's range)
  drone roams back toward Kit 00
  drone re-emits K33's beacon (v2)  ->  collector shows K33 (via mule)

Design / scope:
  - STATUS only. Attacks (SMFW) are not muled — this is the reporting direction; inject
    attacks with listener.py --send.
  - Half-duplex, single HAT: it mostly listens and briefly transmits the buffered
    beacons on a cadence (--forward-interval), with small gaps + jitter.
  - Only FIRST-HAND beacons (version=1) are buffered, so two mules can't ping-pong each
    other's relays. Re-emitted beacons are version=2.
  - Entries not re-heard within --expire seconds are dropped (a kit's state goes stale
    rather than being forwarded forever from an old sighting).
  - The collector prefers a directly-heard beacon over a muled copy, so muling a kit
    that Kit 00 can also hear itself does no harm (see central/collector.py).

Caveat: store-and-forward has latency — a muled beacon reflects the kit's state WHEN THE
DRONE LAST HEARD IT, not now. The dashboard marks these "via mule" and shows no RSSI (the
measured signal would be the mule->central hop, not the kit's).

  sudo python3 scripts/datamule.py                          # listen + forward every 15s
  sudo python3 scripts/datamule.py --forward-interval 10 --expire 300
  sudo python3 scripts/datamule.py --once 20                # one 20s listen, forward, exit (test)

Runs on the same UART SX1262 HAT as the listener (/dev/ttyAMA0). Deps: pyserial, lgpio.
"""
import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "listener"))
import protocol
# LoRaHAT is imported lazily in main() so the pure buffer/forward logic (and its tests)
# import without the lgpio/pyserial hardware deps.

N_KITS = 45
FW = {0: "OK/healthy", 1: "FW_MODE=1 TEST", 2: "FW_MODE=2 LOCK"}


def _ingest(buf, seen):
    """Pull complete SMST/SMFW frames out of buf; buffer first-hand kit beacons into
    `seen` (kit_id -> {fw, heard}). Returns leftover bytes. SMFW and relayed (v2) SMST
    are decoded but not buffered."""
    while buf:
        iu = buf.find(protocol.MAGIC)          # SMFW (attack) — not muled
        it = buf.find(protocol.MAGIC_STATUS)   # SMST (status)
        cands = [x for x in (iu, it) if x >= 0]
        if not cands:
            return buf[-3:]                    # keep a possible partial magic
        i = min(cands)
        if i > 0:
            buf = buf[i:]
            continue
        if buf[:4] == protocol.MAGIC:
            if len(buf) < protocol.FRAME_LEN:
                return buf
            buf = buf[protocol.FRAME_LEN:]
        else:
            if len(buf) < protocol.STATUS_LEN:
                return buf
            info = protocol.parse_status(buf[:protocol.STATUS_LEN])
            buf = buf[protocol.STATUS_LEN:]
            if info.get("valid") and info["version"] < protocol.STATUS_VER_RELAYED:
                kid = info["kit_id"]
                if 1 <= kid <= N_KITS:
                    prev = seen.get(kid)
                    seen[kid] = {"fw": info["fw_mode"], "heard": time.monotonic()}
                    if prev is None or prev["fw"] != info["fw_mode"]:
                        print("  HEAR  K%02d -> %s" % (kid, FW.get(info["fw_mode"], "?")))
    return buf


def _forward(lora, seen, expire):
    """Drop expired sightings, then re-emit each remaining kit's last beacon (relayed)."""
    now = time.monotonic()
    for kid in [k for k, v in seen.items() if now - v["heard"] > expire]:
        del seen[kid]
        print("  DROP  K%02d (not heard in %ds)" % (kid, expire))
    if not seen:
        return
    kits = sorted(seen)
    print("  FWD   %d kit(s): %s" % (len(kits), ", ".join("K%02d" % k for k in kits)))
    for kid in kits:
        frame = protocol.build_status(kid, seen[kid]["fw"], version=protocol.STATUS_VER_RELAYED)
        lora.send(frame)
        time.sleep(0.10 + random.uniform(0, 0.05))   # inter-frame gap + jitter vs collisions


def main():
    ap = argparse.ArgumentParser(description="drone data-mule: carry out-of-range kit status to Kit 00")
    ap.add_argument("--forward-interval", type=float, default=15.0,
                    help="seconds between re-emit bursts (default 15)")
    ap.add_argument("--expire", type=float, default=300.0,
                    help="drop a kit if not re-heard within this many seconds (default 300)")
    ap.add_argument("--once", type=float, default=None, metavar="SECONDS",
                    help="listen this long, forward once, then exit (for testing)")
    args = ap.parse_args()

    from lora import LoRaHAT
    lora = LoRaHAT()
    seen = {}
    buf = b""
    t0 = time.monotonic()
    next_fwd = t0 + (args.once if args.once else args.forward_interval)
    mode = ("one-shot %.0fs" % args.once) if args.once else ("forward every %.0fs" % args.forward_interval)
    print("datamule: listening on %s (%s), expire %.0fs — Ctrl-C to stop"
          % (lora.ser.port, mode, args.expire))
    try:
        while True:
            chunk = lora.read_frame()            # blocks up to the serial timeout
            if chunk:
                buf += chunk
                buf = _ingest(buf, seen)
            else:
                buf = b""                        # inter-frame gap -> drop partial
            if time.monotonic() >= next_fwd:
                _forward(lora, seen, args.expire)
                if args.once:
                    break
                next_fwd = time.monotonic() + args.forward_interval
    except KeyboardInterrupt:
        pass
    finally:
        lora.close()
    print("--- mule buffer: %s" % (", ".join("K%02d=%s" % (k, FW.get(v["fw"], v["fw"]))
                                              for k, v in sorted(seen.items())) or "empty"))


if __name__ == "__main__":
    main()
