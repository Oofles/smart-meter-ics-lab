"""Waveshare SX1262 868M LoRa HAT (UART / EBYTE-style) driver for Raspberry Pi 5.

UART on the 40-pin header (GPIO14/15) @ 9600 8N1; mode pins M0=BCM22, M1=BCM27 on
gpiochip0 (RP1) via lgpio. Board jumpers: UART-select = B, M0/M1 caps REMOVED (so the
Pi GPIO — not a fixed GND jumper — drives the mode). Modes (M0,M1): 0,0 = transceive
(normal TX/RX), 0,1 = config.

Serial device = /dev/ttyAMA0 (the RP1 header UART), NOT /dev/serial0. On Raspberry Pi OS
Bookworm serial0 -> ttyAMA0 so either worked, but on Debian 13 (trixie) serial0 -> ttyAMA10
which is the *Bluetooth* SoC UART — writing there talks to nothing. ttyAMA0 is the header
UART on both, so we address it directly. (See PROVISION.md env notes.)
"""
import time
import serial
import lgpio

M0_PIN, M1_PIN, GPIOCHIP = 22, 27, 0
DEFAULT_PORT = "/dev/ttyAMA0"


class LoRaHAT:
    def __init__(self, port=DEFAULT_PORT, baud=9600, timeout=0.5):
        self.h = lgpio.gpiochip_open(GPIOCHIP)
        lgpio.gpio_claim_output(self.h, M0_PIN, 0)
        lgpio.gpio_claim_output(self.h, M1_PIN, 0)
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.transceive_mode()

    def _set_mode(self, m0, m1):
        lgpio.gpio_write(self.h, M0_PIN, m0)
        lgpio.gpio_write(self.h, M1_PIN, m1)
        time.sleep(0.05)

    def config_mode(self):
        self._set_mode(0, 1)      # M0=0, M1=1

    def transceive_mode(self):
        self._set_mode(0, 0)      # M0=0, M1=0

    def send(self, data: bytes):
        self.ser.write(data)
        self.ser.flush()

    def read_frame(self, max_len=64) -> bytes:
        """Read available bytes (blocks up to the serial timeout)."""
        return self.ser.read(max_len)

    def close(self):
        try:
            self.ser.close()
        finally:
            lgpio.gpio_free(self.h, M0_PIN)
            lgpio.gpio_free(self.h, M1_PIN)
            lgpio.gpiochip_close(self.h)
