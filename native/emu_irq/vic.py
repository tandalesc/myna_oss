"""ARM PL190-style vectored interrupt controller pair of the DB3210 (plain Python, no unicorn import).

Two controllers: VIC0 at 0xA0001000 (lines 0-31) and VIC1 at 0xA0002000 (lines 32-63). An interrupt handler
 reads IRQStatus of both and the VectAddr of VIC0 only, so VIC1 is modelled as
daisy-chained behind VIC0: when VIC0 has no active vectored interrupt, a read of VIC0.VectAddr returns the
vector address of VIC1's highest-priority active vectored interrupt, else DefVectAddr of VIC0.

    pair = VicPair(on_irq=cb, on_fiq=cb)     # cb(level: bool), called when the output changes
    pair.set_line(n, level)                  # device input, n = 0..63, level-sensitive
    pair.vic0 / pair.vic1                    # bus devices (read(offset,size) / write(offset,size,value))
"""

REG_IRQSTATUS, REG_FIQSTATUS, REG_RAWINTR, REG_INTSELECT = 0x00, 0x04, 0x08, 0x0C
REG_INTENABLE, REG_INTENCLEAR, REG_SOFTINT, REG_SOFTINTCLEAR = 0x10, 0x14, 0x18, 0x1C
REG_PROTECTION, REG_VECTADDR, REG_DEFVECTADDR = 0x20, 0x30, 0x34
VECTADDR0, VECTCNTL0 = 0x100, 0x200
PERIPH_ID = (0x90, 0x11, 0x04, 0x00)           # PL190 PeriphID0-3 (datasheet values; the firmware never reads them)
PCELL_ID = (0x0D, 0xF0, 0x05, 0xB1)
M32 = 0xFFFFFFFF


class Vic:
    """One PL190. `chain` (optional) is the Vic whose vector output feeds this one's default vector."""

    def __init__(self, name, notify=None):
        self.name = name
        self.notify = notify or (lambda: None)
        self.lines = 0            # level inputs from devices
        self.soft = 0
        self.enable = 0
        self.select = 0           # 1 = FIQ
        self.protection = 0
        self.defvect = 0
        self.vectaddr = [0] * 16
        self.vectcntl = [0] * 16
        self.chain = None
        self.cur_prio = []        # stack of slot numbers whose vector was read and not yet acknowledged
        self.reads_vect = 0
        self.writes_vect = 0

    # ---- derived state ----
    @property
    def raw(self):
        return (self.lines | self.soft) & M32

    @property
    def irq_status(self):
        return self.raw & self.enable & ~self.select & M32

    @property
    def fiq_status(self):
        return self.raw & self.enable & self.select & M32

    def _active_slot(self):
        """Lowest enabled vector slot whose source is active as IRQ and not blocked by the priority stack."""
        st = self.irq_status
        limit = self.cur_prio[-1] if self.cur_prio else 16
        for i in range(min(limit, 16)):
            c = self.vectcntl[i]
            if c & 0x20 and st >> (c & 0x1F) & 1:
                return i
        return None

    def irq_asserted(self):
        if self.irq_status == 0:
            return False
        # priority hardware: an active vectored interrupt of lower priority than the one in service is held off,
        # a non-vectored one is held off while any vectored one is in service
        if not self.cur_prio:
            return True
        if self._active_slot() is not None:
            return True
        return False

    def fiq_asserted(self):
        return self.fiq_status != 0

    def vector_out(self):
        """What a VectAddr read yields (None = no vectored interrupt active), without side effects."""
        i = self._active_slot()
        return None if i is None else (i, self.vectaddr[i])

    # ---- bus ----
    def read(self, off, size):
        if off == REG_IRQSTATUS:
            return self.irq_status
        if off == REG_FIQSTATUS:
            return self.fiq_status
        if off == REG_RAWINTR:
            return self.raw
        if off == REG_INTSELECT:
            return self.select
        if off == REG_INTENABLE:
            return self.enable
        if off == REG_SOFTINT:
            return self.soft
        if off == REG_PROTECTION:
            return self.protection
        if off == REG_VECTADDR:
            self.reads_vect += 1
            v = self.vector_out()
            if v is not None:
                self.cur_prio.append(v[0])
                self.notify()                 # lower-priority interrupts are now held off
                return v[1]
            if self.chain is not None:
                return self.chain.read(REG_VECTADDR, size) if self.chain.vector_out() is not None else self.defvect
            return self.defvect
        if off == REG_DEFVECTADDR:
            return self.defvect
        if VECTADDR0 <= off < VECTADDR0 + 64:
            return self.vectaddr[(off - VECTADDR0) >> 2]
        if VECTCNTL0 <= off < VECTCNTL0 + 64:
            return self.vectcntl[(off - VECTCNTL0) >> 2]
        if 0xFE0 <= off < 0x1000:
            n = (off - 0xFE0) >> 2
            return PERIPH_ID[n] if n < 4 else PCELL_ID[n - 4]
        return 0

    def write(self, off, size, value):
        value &= M32
        if off == REG_INTSELECT:
            self.select = value
        elif off == REG_INTENABLE:
            self.enable |= value
        elif off == REG_INTENCLEAR:
            self.enable &= ~value & M32
        elif off == REG_SOFTINT:
            self.soft |= value
        elif off == REG_SOFTINTCLEAR:
            self.soft &= ~value & M32
        elif off == REG_PROTECTION:
            self.protection = value & 1
        elif off == REG_VECTADDR:
            self.writes_vect += 1
            if self.cur_prio:
                self.cur_prio.pop()
            elif self.chain is not None and self.chain.cur_prio:
                self.chain.cur_prio.pop()
        elif off == REG_DEFVECTADDR:
            self.defvect = value
        elif VECTADDR0 <= off < VECTADDR0 + 64:
            self.vectaddr[(off - VECTADDR0) >> 2] = value
        elif VECTCNTL0 <= off < VECTCNTL0 + 64:
            self.vectcntl[(off - VECTCNTL0) >> 2] = value & 0x3F
        self.notify()


class VicPair:
    def __init__(self, on_irq=None, on_fiq=None):
        self.on_irq = on_irq or (lambda level: None)
        self.on_fiq = on_fiq or (lambda level: None)
        self.irq_out = False
        self.fiq_out = False
        self.vic0 = Vic('VIC0', self.update)
        self.vic1 = Vic('VIC1', self.update)
        self.vic0.chain = self.vic1
        self.irq_edges = 0

    def set_line(self, n, level):
        v = self.vic0 if n < 32 else self.vic1
        bit = 1 << (n & 31)
        v.lines = (v.lines | bit) if level else (v.lines & ~bit)
        self.update()

    def get_line(self, n):
        v = self.vic0 if n < 32 else self.vic1
        return bool(v.lines >> (n & 31) & 1)

    def update(self):
        irq = self.vic0.irq_asserted() or self.vic1.irq_asserted()
        fiq = self.vic0.fiq_asserted() or self.vic1.fiq_asserted()
        if irq != self.irq_out:
            self.irq_out = irq
            self.irq_edges += irq
            self.on_irq(irq)
        if fiq != self.fiq_out:
            self.fiq_out = fiq
            self.on_fiq(fiq)
