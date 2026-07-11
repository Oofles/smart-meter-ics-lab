#!/usr/bin/env python3
"""Stamp the Opta firmware's per-kit IP host octet into a copy of the .bin.

The sketch embeds a `KITCFGv1` marker followed by the 4 IP octets (192.168.1.210).
This finds the marker and rewrites the 4th octet, so one prebuilt firmware serves every
kit (kit N -> 192.168.1.(200+N)). No recompile.

  python3 patch_ip.py <in.bin> <last-octet> <out.bin>
"""
import sys

MAGIC = b"KITCFGv1"      # 8 bytes, then IP(4): octet index = magic + 8 + 3

def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    src, octet, dst = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    if not 1 <= octet <= 254:
        sys.exit("last octet must be 1..254")
    data = bytearray(open(src, "rb").read())
    if data.count(MAGIC) != 1:
        sys.exit("KITCFGv1 marker not found exactly once (%d) — wrong/old firmware?" % data.count(MAGIC))
    i = data.find(MAGIC)
    data[i + 11] = octet
    open(dst, "wb").write(data)
    print("patched Opta IP -> 192.168.1.%d" % octet)

if __name__ == "__main__":
    main()
