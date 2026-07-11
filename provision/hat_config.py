#!/usr/bin/env python3
"""Configure the kit's Waveshare/EBYTE SX1262 868M LoRa HAT to the lab GOLDEN config.

Every kit's HAT must match, or they can't hear each other. Golden config (read off the
reference kit): address 0/0, NETID 0, UART 9600 8N1, air-rate 2.4k, channel 18
(= 850.125 + 18 = 868.125 MHz), transparent mode. This writes it to the HAT's NVM (C0)
and verifies by reading back (C1).

Pins: M0=BCM22, M1=BCM27 on gpiochip0; UART /dev/serial0 @ 9600. Board jumpers: UART-select=B,
M0/M1 caps removed (same as listener/lora.py). Deps: pyserial, lgpio.

  python3 hat_config.py          # write golden + verify   (use sudo if GPIO needs it)
  python3 hat_config.py --read   # just show current config, change nothing
"""
import sys, time, serial, lgpio

M0, M1, CHIP = 22, 27, 0
PORT = "/dev/serial0"
# 9 config registers @ addr 0: ADDH ADDL NETID REG3 REG4 CH(REG5) REG6 REG7 REG8
GOLDEN = bytes([0x00, 0x00, 0x00, 0x62, 0x00, 0x12, 0x03, 0x00, 0x00])


def _read_cfg(ser):
    ser.reset_input_buffer()
    ser.write(bytes([0xC1, 0x00, 0x09])); ser.flush()
    time.sleep(0.3)
    r = ser.read(32)
    return r[3:12] if len(r) >= 12 and r[0] in (0xC1, 0xC0) else b""


def main():
    read_only = "--read" in sys.argv
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
        if cur == GOLDEN:
            print("already golden — channel 18 / 868.125 MHz, air-rate 2.4k, transparent")
            return 0
        ser.reset_input_buffer()
        ser.write(bytes([0xC0, 0x00, 0x09]) + GOLDEN); ser.flush()  # C0 = write NVM
        time.sleep(0.4)
        ser.read(32)
        chk = _read_cfg(ser)
        print("readback:", chk.hex(" "))
        if chk == GOLDEN:
            print("HAT config OK — channel 18 / 868.125 MHz, air-rate 2.4k, transparent")
            return 0
        print("MISMATCH — expected", GOLDEN.hex(" "))
        return 1
    finally:
        lgpio.gpio_write(h, M0, 0); lgpio.gpio_write(h, M1, 0)  # back to transceive
        ser.close()
        lgpio.gpio_free(h, M0); lgpio.gpio_free(h, M1); lgpio.gpiochip_close(h)


if __name__ == "__main__":
    sys.exit(main())
