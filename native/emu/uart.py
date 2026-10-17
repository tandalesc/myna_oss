"""UART model at 0xC0013000. TX data at +0, status at +0x18 (bit5 busy = 0, bit7 done = 1)."""
import sys


class Uart:
    name = 'UART0'

    def __init__(self, logfile=None, echo=True):
        self.out = bytearray()
        self.echo = echo
        self.logf = open(logfile, 'wb') if logfile else None

    def read(self, off, size):
        if off == 0x18:
            return 0x80
        return 0

    def write(self, off, size, value):
        if off == 0:
            self.putc(value & 0xff)

    def putc(self, c):
        self.out.append(c)
        if self.logf:
            self.logf.write(bytes([c])); self.logf.flush()
        if self.echo:
            sys.stdout.write(chr(c) if 32 <= c < 127 or c in (9, 10, 13) else f'<{c:02x}>')
            sys.stdout.flush()
