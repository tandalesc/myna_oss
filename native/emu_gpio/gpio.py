"""SoC GPIO block of the DB3210 application CPU: 0xC0016000, five banks of 8 pins, 0x30 bytes per bank, VIC lines 32..36 (GPIO0..GPIO4).

Plain Python, no unicorn import. A driver accesses every register as a 16-bit halfword. Marks: [V] read in driver code, [I] inferred, [?] unknown,
[MOCK] chosen stand-in.

    +0x00 (bank 0 only) CTRL  [V] init sets bit 0; a boot loader sets bit 2. [?] meaning. Stored.
  per bank n, base n*0x30:
    +0x04 DIN   [V] pin levels, low 8 bits. [I] read-only: an output pin reads its latch. (A boot loader
                writes bit 4 here once at 5.6 ms; ignored.)
    +0x08 DOUT  [V] output latch, written whole from a RAM shadow.
    +0x0c DIR   [V] two bits per pin: 01 = output, 00 = input. [?] values 10/11.
    +0x10       [V] written once at init. [?] meaning (pin function select?). Stored.
    +0x14 ISTAT [V] interrupt status, low 8 bits; write 1 to clear.
    +0x18 IEN   [V] interrupt enable per pin.
    +0x1c       [V] written 0 at init. [?] Stored.
    +0x20 IPOL  [V] 1 = the pin interrupts on high / rising, 0 = low / falling. For
                "both edges" the driver itself re-programs the bit to the opposite of the level it just reported.
    +0x24       [V] bank 1 bit 0 set by a boot loader. [?] Stored.

Interrupt model [I]: edge type. ISTAT bit p latches when input pin p is enabled in IEN and changes to the level IPOL selects; VIC line
32+n is high while ISTAT & IEN is non-zero. ISTAT shows enabled pins only: a handler that scans the raw ISTAT of all five banks
faults on a pending pin that has no subscriber [V], so the hardware
cannot be latching pins that were never enabled. (A level-type reading fits the code equally; the driver always arms the
opposite of the current level.)
"""

NBANKS, BANK_SIZE = 5, 0x30
CTRL, DIN, DOUT, DIR, REG10, ISTAT, IEN, REG1C, IPOL = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x20
LINE0 = 32

# named input pins: name -> (bank, pin, level per state).
#   slide       port 0 mask 0x10, both edges; pin high = slide closed, low = open
#   lens_cover  port 0 mask 0x08, both edges; pin high = lens cover closed, low = open
#   memstick    port 1 mask 0x10: card detect of the memory card slot; pin low = card in
PINS = {'slide': (0, 4, {'closed': 1, 'open': 0}),
        'lens_cover': (0, 3, {'closed': 1, 'open': 0}),
        'memstick': (1, 4, {'out': 1, 'in': 0})}
# [MOCK] external levels at power-up: slide closed, lens cover closed, no card; every other input low
DEFAULT_EXT = (0x18, 0x10, 0x00, 0x00, 0x00)


class GpioBlock:
    name = 'GPIO'

    def __init__(self, set_line=None, log=None, ext=DEFAULT_EXT):
        self.set_line = set_line or (lambda n, level: None)
        self.log = log or (lambda s: None)
        self.ext = list(ext)                    # external level of each pin, per bank
        self.regs = {}                          # offset -> value, everything that is plain storage
        self.dout = [0] * NBANKS
        self.dir = [0] * NBANKS
        self.istat = [0] * NBANKS
        self.ien = [0] * NBANKS
        self.ipol = [0] * NBANKS
        self.levels = [False] * NBANKS          # VIC line levels
        self.irq_rises = [0] * NBANKS
        self.din_reads = [0] * NBANKS
        self.events = []                        # (bank, pin, level) every external change, last 32
        self.trace = None                       # optional list of ('R'|'W', offset, value)

    # ---- electrical ----
    def out_mask(self, n):
        d = self.dir[n]
        return sum(1 << p for p in range(8) if (d >> (2 * p)) & 3 == 1)

    def din(self, n):
        m = self.out_mask(n)
        return (self.dout[n] & m) | (self.ext[n] & ~m & 0xFF)

    def _update(self, n):
        level = bool(self.istat[n] & self.ien[n])
        if level != self.levels[n]:
            self.levels[n] = level
            if level:
                self.irq_rises[n] += 1
            self.set_line(LINE0 + n, level)

    # ---- outside world ----
    def set_pin(self, bank, pin, level):
        """Drive the external level of one pin (0/1). Latches ISTAT when the pin is an enabled input and the change matches IPOL."""
        bit = 1 << pin
        old = self.din(bank) & bit
        self.ext[bank] = (self.ext[bank] & ~bit) | (bit if level else 0)
        new = self.din(bank) & bit
        if new != old:
            self.events.append((bank, pin, 1 if new else 0)); del self.events[:-32]
            if self.ien[bank] & bit and bool(new) == bool(self.ipol[bank] & bit):
                self.istat[bank] |= bit
                self._update(bank)
        return bool(new)

    def get_pin(self, bank, pin):
        return (self.din(bank) >> pin) & 1

    def set_switch(self, name, state):
        bank, pin, levels = getattr(self, 'pins', PINS)[name]      # a device with a different wiring sets `pins` on its block
        self.set_pin(bank, pin, levels[state])
        return 'GPIO port %d pin %d = %d' % (bank, pin, levels[state])

    # ---- bus ----
    def read(self, off, size):
        n, r = divmod(off, BANK_SIZE)
        if n >= NBANKS:
            v = self.regs.get(off, 0)
        elif r == DIN:
            self.din_reads[n] += 1
            v = self.din(n)
        elif r == DOUT: v = self.dout[n]
        elif r == DIR: v = self.dir[n]
        elif r == ISTAT: v = self.istat[n]
        elif r == IEN: v = self.ien[n]
        elif r == IPOL: v = self.ipol[n]
        else: v = self.regs.get(off, 0)
        if self.trace is not None: self.trace.append(('R', off, v))
        return v

    def write(self, off, size, value):
        if self.trace is not None: self.trace.append(('W', off, value))
        n, r = divmod(off, BANK_SIZE)
        value &= 0xFFFF
        if n >= NBANKS:
            self.regs[off] = value
        elif r == DIN:
            pass                                # read-only [I]
        elif r == DOUT: self.dout[n] = value & 0xFF
        elif r == DIR: self.dir[n] = value
        elif r == ISTAT:
            self.istat[n] &= ~value
            self._update(n)
        elif r == IEN:
            self.ien[n] = value & 0xFF
            self._update(n)
        elif r == IPOL: self.ipol[n] = value & 0xFF
        else: self.regs[off] = value

    def summary(self):
        b = '; '.join('P%d din %02x dir %04x out %02x ien %02x ipol %02x istat %02x irq %d reads %d' % (
            n, self.din(n), self.dir[n], self.dout[n], self.ien[n], self.ipol[n], self.istat[n], self.irq_rises[n], self.din_reads[n]) for n in range(NBANKS))
        return '[gpio] ' + b + '; pin changes %s' % (' '.join('P%d.%d=%d' % e for e in self.events) or '-')
