#!/usr/bin/env python3
"""Configure the kit's Waveshare/EBYTE SX1262 868M LoRa HAT to a lab mesh config.

Every node on the SAME mesh must share this config, or they can't hear each other. Two
meshes exist on this bench, separated by CHANNEL (= RF centre frequency — a receiver only
demodulates its own channel, so different channels are fully PHY-isolated):

  * EXERCISE / GOLDEN  — channel 65 = 915.125 MHz  (the default here; the blue-team fleet)
  * DV DEMO            — channel 58 = 908.125 MHz  (`--channel 58`; Kits 43-45, see DEMO.md)

Base config (read off the reference kit): address 0/0, NETID 0, UART 9600 8N1, air-rate 2.4k,
transparent mode; only the channel byte (REG5) and, on the central node, the RSSI-append bit
(REG6 bit7) vary. This writes the target to the HAT's NVM (C0) and verifies by reading back (C1).

Pins: M0=BCM22, M1=BCM27 on gpiochip0; UART /dev/ttyAMA0 @ 9600 (the RP1 header UART — NOT
/dev/serial0, which is the Bluetooth UART on trixie; see listener/lora.py). Board jumpers:
UART-select=B, M0/M1 caps removed (same as listener/lora.py). Deps: pyserial, lgpio.

  python3 hat_config.py                 # write GOLDEN (ch 65 / 915.125 MHz) + verify
  python3 hat_config.py --channel 58    # write the DV-demo channel (58 / 908.125 MHz)
  python3 hat_config.py --rssi          # GOLDEN + RSSI-append ON  (a CENTRAL node's collector HAT)
  python3 hat_config.py --rssi --channel 58   # DV-demo central (Kit 43) HAT
  python3 hat_config.py --read          # just show current config, change nothing

--rssi sets REG6 bit7 so the module appends a per-packet RSSI byte after each received
frame (dBm ~= -(256-byte)); the collector reads it for the fleet range map. It's a
receive-side UART behaviour only — same PHY (channel/air-rate/sync) as the rest of that
mesh, so an RSSI-append HAT still interoperates fully with the field kits on its channel.
Field kits stay plain; only the central collector needs --rssi.
"""
import sys
import time

M0, M1, CHIP = 22, 27, 0
PORT = "/dev/ttyAMA0"
RSSI_BIT = 0x80          # REG6 bit7: append RSSI byte after each received packet
DEFAULT_CH = 0x41        # channel 65 = 915.125 MHz (US 902-928 ISM) — the EXERCISE/GOLDEN mesh
# 9 config registers @ addr 0: ADDH ADDL NETID REG3 REG4 CH(REG5) REG6 REG7 REG8
BASE = bytes([0x00, 0x00, 0x00, 0x62, 0x00, DEFAULT_CH, 0x03, 0x00, 0x00])
FREQ_BASE_MHZ = 850.125  # module: centre freq (MHz) = 850.125 + channel
US_ISM_CH = (52, 77)     # channels whose 908/915-style centre sits inside US 902-928 MHz ISM


def cfg_for(channel, rssi=False):
    """9-byte EBYTE NVM config for `channel` (0..80), optionally with RSSI-append."""
    reg6 = BASE[6] | (RSSI_BIT if rssi else 0)
    return BASE[:5] + bytes([channel & 0xFF, reg6]) + BASE[7:]


def freq_mhz(channel):
    return FREQ_BASE_MHZ + channel


def channel_from_argv(argv):
    """`--channel N` (accepts decimal or 0x.. ) -> int; default = GOLDEN (65)."""
    if "--channel" in argv:
        try:
            return int(argv[argv.index("--channel") + 1], 0)
        except (IndexError, ValueError):
            print("error: --channel needs a number (e.g. --channel 58)", file=sys.stderr)
            sys.exit(2)
    return DEFAULT_CH


def _read_cfg(ser):
    ser.reset_input_buffer()
    ser.write(bytes([0xC1, 0x00, 0x09])); ser.flush()
    time.sleep(0.3)
    r = ser.read(32)
    return r[3:12] if len(r) >= 12 and r[0] in (0xC1, 0xC0) else b""


def main():
    read_only = "--read" in sys.argv
    rssi = "--rssi" in sys.argv
    channel = channel_from_argv(sys.argv)
    if not 0 <= channel <= 80:
        print("error: channel %d out of range (0..80)" % channel, file=sys.stderr)
        return 2
    target = cfg_for(channel, rssi)
    tag = "channel %d / %.3f MHz, air-rate 2.4k, transparent" % (channel, freq_mhz(channel))
    if rssi:
        tag += " + RSSI-append"
    if not US_ISM_CH[0] <= channel <= US_ISM_CH[1]:
        print("WARNING: channel %d (%.3f MHz) is outside US 902-928 ISM (ch %d-%d)"
              % (channel, freq_mhz(channel), *US_ISM_CH), file=sys.stderr)

    import serial
    import lgpio
    h = lgpio.gpiochip_open(CHIP)
    lgpio.gpio_claim_output(h, M0, 0)
    lgpio.gpio_claim_output(h, M1, 0)
    ser = serial.Serial(PORT, 9600, timeout=1)
    try:
        lgpio.gpio_write(h, M0, 0); lgpio.gpio_write(h, M1, 1); time.sleep(0.1)  # config mode
        cur = _read_cfg(ser)
        print("current :", cur.hex(" ") or "(no response — check jumpers/wiring)")
        if read_only:
            return 0
        if cur == target:
            print("already set — " + tag)
            return 0
        ser.reset_input_buffer()
        ser.write(bytes([0xC0, 0x00, 0x09]) + target); ser.flush()  # C0 = write NVM
        time.sleep(0.4)
        ser.read(32)
        chk = _read_cfg(ser)
        print("readback:", chk.hex(" "))
        if chk == target:
            print("HAT config OK — " + tag)
            return 0
        print("MISMATCH — expected", target.hex(" "))
        return 1
    finally:
        lgpio.gpio_write(h, M0, 0); lgpio.gpio_write(h, M1, 0)  # back to transceive
        ser.close()
        lgpio.gpio_free(h, M0); lgpio.gpio_free(h, M1); lgpio.gpiochip_close(h)


if __name__ == "__main__":
    sys.exit(main())
