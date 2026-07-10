#!/usr/bin/env python3
"""RF update listener: LoRa -> FW_MODE write on the Opta.

On a recognized MALICIOUS firmware-update frame received over LoRa, writes
FW_MODE=1 on the Opta (Modbus TCP) — tripping the meter. Benign frames (version
heartbeats) are logged and ignored. This is the RF half of the exercise's attack
path; the Modbus write is exactly what scripts/mb_trip.py does.

  ./listener.py                       # listen on LoRa, act on frames
  ./listener.py --simulate malicious  # feed a canned frame (NO RF) -> should trip
  ./listener.py --simulate benign
  ./listener.py --send malicious      # TRANSMIT a frame over LoRa (2nd node / OTA)
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import mb           # pure-stdlib Modbus TCP client (no deps)
import protocol

HREG_FW_MODE = 9


def handle(frame: bytes, host: str):
    valid, fw_type, version = protocol.parse(frame)
    if not valid:
        print("  ignored — bad magic/CRC:", frame.hex(" "))
        return
    if fw_type == protocol.TYPE_MALICIOUS:
        print("  !! MALICIOUS firmware update accepted (v%d) -> writing FW_MODE=1" % version)
        mb.write_register(HREG_FW_MODE, 1, host=host)
    else:
        print("  benign firmware/heartbeat v%d — no-op" % version)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=mb.DEFAULT_HOST, help="Opta Modbus host")
    ap.add_argument("--simulate", choices=["malicious", "benign"],
                    help="feed a canned frame to the handler (no radio needed)")
    ap.add_argument("--send", choices=["malicious", "benign"],
                    help="transmit a frame over LoRa (needs the HAT)")
    args = ap.parse_args()

    # --simulate needs no hardware: it exercises parse -> Modbus write end to end.
    if args.simulate:
        frame = protocol.build(protocol.TYPE_MALICIOUS if args.simulate == "malicious"
                               else protocol.TYPE_BENIGN)
        print("simulated received frame:", frame.hex(" "))
        handle(frame, args.host)
        return

    from lora import LoRaHAT
    lora = LoRaHAT()
    try:
        if args.send:
            frame = protocol.build(protocol.TYPE_MALICIOUS if args.send == "malicious"
                                   else protocol.TYPE_BENIGN)
            print("transmitting over LoRa:", frame.hex(" "))
            lora.send(frame)
            time.sleep(0.2)
            return
        print("listening on LoRa (/dev/serial0) — Ctrl-C to stop")
        buf = b""
        while True:
            chunk = lora.read_frame()
            if chunk:
                buf += chunk
                while len(buf) >= 8:
                    handle(buf[:8], args.host)
                    buf = buf[8:]
            else:
                buf = b""       # inter-frame gap -> drop any partial
    except KeyboardInterrupt:
        pass
    finally:
        lora.close()


if __name__ == "__main__":
    main()
