#!/usr/bin/env python3
"""Read and print the smart-meter Opta state over Modbus TCP.

Usage: ./mb_read.py [host]   (default host 192.168.1.210)
"""
import sys
import mb

host = sys.argv[1] if len(sys.argv) > 1 else mb.DEFAULT_HOST

ps = mb.read_coils(0, 1, host=host)[0]
volt, watt = mb.read_holding(0, 2, host=host)
fw = mb.read_holding(9, 1, host=host)[0]
raw_blue, raw_reset, raw_dial, raw_green = mb.read_holding(20, 4, host=host)
lb, lg, ly, lr, sb, sg = mb.read_discrete_inputs(0, 6, host=host)

on = lambda b: "ON " if b else "off"
print(f"POWER_STATUS : {ps}  ({'healthy / normal' if ps else 'FAULTED / attack'})")
print(f"VOLTAGE_X10  : {volt}  ({volt / 10:.1f} V)")
print(f"POWER_W      : {watt} W")
print(f"FW_MODE      : {fw}  ({'normal firmware' if fw == 0 else 'MALICIOUS firmware'})")
print(f"panel lamps  : BLUE {on(lb)}  GREEN {on(lg)}  YELLOW {on(ly)}  RED {on(lr)}")
print(f"switches     : I1(blue) {on(sb)}  I2(green) {on(sg)}")
print(f"raw I1/I2/I3/dial: {raw_blue} / {raw_green} / {raw_reset} / {raw_dial}")
