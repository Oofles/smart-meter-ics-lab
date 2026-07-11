#!/usr/bin/env python3
"""Facilitator UNLOCK: clear any fault (incl. the exercise LOCK) via a direct FW_MODE := 0 write.

Models a firmware re-flash. Unlike mb_reset.py (the operator RESET coil, which an exercise
LOCK / FW_MODE=2 deliberately ignores), this ALWAYS clears the fault — TEST or LOCK.

Usage: ./mb_unlock.py [host]   (default host 192.168.1.210)
"""
import sys
import mb

host = sys.argv[1] if len(sys.argv) > 1 else mb.DEFAULT_HOST
mb.write_register(9, 0, host=host)      # FW_MODE (holding reg 9) := 0 (direct)
print("FW_MODE := 0  — facilitator unlock: fault cleared (TEST or LOCK)")
