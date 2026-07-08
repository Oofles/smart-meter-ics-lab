#!/usr/bin/env python3
"""Clear the fault and re-arm the meter: RESET coil (15) := 1.

Usage: ./mb_reset.py [host]   (default host 192.168.1.210)
"""
import sys
import mb

host = sys.argv[1] if len(sys.argv) > 1 else mb.DEFAULT_HOST
mb.write_coil(15, True, host=host)      # RESET (coil 15) := 1
print("RESET := 1  — meter re-armed to normal (green, live voltage/usage)")
