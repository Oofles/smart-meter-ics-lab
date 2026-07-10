"""Waveshare SX1262 868M LoRa HAT (UART / EBYTE-style) driver for Raspberry Pi 5.

UART on /dev/serial0 (=/dev/ttyAMA0 on Pi 5) @ 9600 8N1; mode pins M0=BCM22,
M1=BCM27 on gpiochip0 (RP1) via lgpio. Board jumpers: UART-select = B,
M0/M1 caps REMOVED. Modes (M0,M1): 0,0 = transceive (normal TX/RX), 0,1 = config.
"""
import time
import serial
import lgpio

M0_PIN, M1_PIN, GPIOCHIP = 22, 27, 0


class LoRaHAT:
    def __init__(self, port="/dev/serial0", baud=9600, timeout=0.5):
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
