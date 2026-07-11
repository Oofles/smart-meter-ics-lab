#!/usr/bin/env python3
"""Inject the 'malicious firmware update' by writing FW_MODE directly (RF stand-in).

Usage: ./mb_trip.py [host] [--lock]   (default host 192.168.1.210)
  (default)  FW_MODE := 1  TEST trip    — operator RESET (mb_reset.py / I3) clears it
  --lock     FW_MODE := 2  EXERCISE LOCK — operator RESET disabled;
                                           clear only with mb_unlock.py (direct FW_MODE:=0)
"""
import sys
import mb

lock = ("--lock" in sys.argv) or ("--exercise" in sys.argv)
hosts = [a for a in sys.argv[1:] if not a.startswith("-")]
host = hosts[0] if hosts else mb.DEFAULT_HOST

if lock:
    mb.write_register(9, 2, host=host)  # FW_MODE (holding reg 9) := 2
    print("FW_MODE := 2  — EXERCISE LOCK (red persists; RESET disabled; clear with mb_unlock.py)")
else:
    mb.write_register(9, 1, host=host)  # FW_MODE (holding reg 9) := 1
    print("FW_MODE := 1  — TEST trip (red, voltage/usage -> 0; clear with mb_reset.py)")
