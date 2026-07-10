#!/usr/bin/env python3
"""Reverse-link helper: drive the Pi's EBYTE/Waveshare HAT to TRANSMIT a known
benign SMFW frame on a fixed cadence, so the Heltec RX-sweep (drone/rxsweep) has a
steady signal to lock onto. Pairs with rxsweep.ino.

Opens the HAT once and transmits every INTERVAL seconds until stopped. Handles
SIGINT/SIGTERM so the lgpio M0/M1 lines are always released (a hard kill leaves
them claimed -> next run dies "GPIO busy").

  python3 tx_beacon.py            # 0.4s cadence, benign frame, runs until stopped
  python3 tx_beacon.py 0.25       # custom interval
  python3 tx_beacon.py 0.4 8      # stop automatically after 8s (self-terminating)
"""
import os
import signal
import sys
import time

# Absolute repo paths so this runs from anywhere on the Pi (it's often staged to /tmp).
_REPO = "/home/vivicat/smart-meter-ics-lab"
for _d in (os.path.join(_REPO, "listener"), os.path.join(_REPO, "scripts")):
    if _d not in sys.path:
        sys.path.insert(0, _d)
from lora import LoRaHAT
import protocol

INTERVAL = float(sys.argv[1]) if len(sys.argv) > 1 else 0.4
MAX_SECS = float(sys.argv[2]) if len(sys.argv) > 2 else None

_run = True
def _stop(*_a):
    global _run
    _run = False
signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)

lora = LoRaHAT()
mid = 0
sent = 0
t0 = time.time()
print("tx_beacon: transmitting benign SMFW every %.2fs on /dev/serial0%s" %
      (INTERVAL, (" for %.0fs" % MAX_SECS) if MAX_SECS else ""), flush=True)
try:
    while _run and (MAX_SECS is None or time.time() - t0 < MAX_SECS):
        mid = (mid + 1) & 0xFFFF
        frame = protocol.build(protocol.TYPE_BENIGN, mid, 1)
        lora.send(frame)
        sent += 1
        if sent % 10 == 0:
            print("  sent %d frames (last msg_id=0x%04X)" % (sent, mid), flush=True)
        time.sleep(INTERVAL)
finally:
    lora.close()
    print("tx_beacon: stopped after %d frames; GPIO released" % sent, flush=True)
