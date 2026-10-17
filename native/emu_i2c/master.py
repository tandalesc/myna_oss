"""I2C master controller of the DB3210 (blocks 0xC0004000 = I2C0, line 42 and 0xC0005000 = I2C1, line 43).

Plain Python, no unicorn import. Register layout and bit meanings are bit-for-bit the ST "I2C" cell of the ST7 / STR71x
microcontrollers (STR71x reference manual RM0002, chapter I2C). Marks: [V] verified in driver code or seen in a run, [I] inferred.

    +0x00 CR    PE 0x20, ENGC 0x10, START 0x08, ACK 0x04, STOP 0x02, ITE 0x01
    +0x04 SR1   EVF 0x80, ADD10 0x40, TRA 0x20, BUSY 0x10, BTF 0x08, ADSL 0x04, M/SL 0x02, SB 0x01     (read only)
    +0x08 SR2   ENDAD 0x20, AF 0x10, STOPF 0x08, ARLO 0x04, BERR 0x02, GCAL 0x01                      (read only)
    +0x0c CCR   clock divider (bit 7 fast mode)         +0x10 OAR1 own address      +0x14 OAR2 (bits 7:6 frequency range)
    +0x18 DR    data                                     +0x1c ECCR extended clock divider

Master sequence the firmware uses (events are instantaneous in this model; SCL timing is not modelled):
    CR.START            -> SB, M/SL, BUSY                         (interrupt if ITE)
    DR = address byte   -> SB cleared; slave ACK -> ENDAD (TRA if write); no ACK -> AF
    read SR2, write CR  -> ENDAD cleared; transmitter: BTF (DR empty); receiver: first byte in DR, BTF
    transmitter DR = b  -> BTF again, AF if the slave did not acknowledge
    receiver read DR    -> next byte clocked in, BTF again (not after STOP)
    CR.STOP             -> M/SL, BUSY, TRA cleared; a received byte stays readable in DR
    interrupt line      =  PE and ITE and EVF, EVF = SB | ENDAD | BTF | AF (| slave-mode flags, never set here)
"""

CR, SR1, SR2, CCR, OAR1, OAR2, DR, ECCR = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C
PE, ENGC, START, ACK, STOP, ITE = 0x20, 0x10, 0x08, 0x04, 0x02, 0x01
EVF, ADD10, TRA, BUSY, BTF, ADSL, MSL, SB = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01
ENDAD, AF, STOPF, ARLO, BERR, GCAL = 0x20, 0x10, 0x08, 0x04, 0x02, 0x01


class I2cMaster:
    """One controller. `bus` is an I2cBus (emu_i2c.bus); `set_irq(level)` drives the interrupt line (level sensitive)."""

    def __init__(self, name, bus, set_irq=None, log=None):
        self.name = name
        self.bus = bus
        self.set_irq = set_irq or (lambda level: None)
        self.log = log or (lambda s: None)
        self.trace = None               # optional list: every access as (kind, offset, value)
        self.reset()

    def reset(self):
        self.cr = 0
        self.sr1 = 0                    # stored bits: TRA, BUSY, BTF, M/SL, SB (EVF is derived)
        self.sr2 = 0                    # ENDAD, AF
        self.ccr = self.oar1 = self.oar2 = self.eccr = 0
        self.dr = 0
        self._sr2_read = False          # ENDAD is cleared by "read SR2, then write CR"
        self._addressed = False         # a slave acknowledged the address of the running transfer
        self.irq_level = False
        self.starts = self.stops = self.naks = self.bytes_tx = self.bytes_rx = 0

    # ---- derived ----
    @property
    def evf(self):
        return bool(self.sr1 & (SB | BTF) or self.sr2 & (ENDAD | AF))

    def _update(self):
        level = bool(self.cr & PE and self.cr & ITE and self.evf)
        if level != self.irq_level:
            self.irq_level = level
            self.set_irq(level)

    # ---- bus access ----
    def read(self, off, size):
        v = self._read(off)
        if self.trace is not None:
            self.trace.append(('R', off, v))
        return v

    def _read(self, off):
        if off == CR:
            return self.cr
        if off == SR1:
            return self.sr1 | (EVF if self.evf else 0)
        if off == SR2:
            v = self.sr2
            if v & ENDAD:
                self._sr2_read = True
            if v & AF:                      # AF is cleared by reading SR2
                self.sr2 &= ~AF
                self._update()
            return v
        if off == DR:
            v = self.dr
            if self.sr1 & BTF and not self.sr1 & TRA:
                self.sr1 &= ~BTF
                if self.sr1 & MSL:          # still master receiver: the next byte is clocked in at once
                    self._receive()
                self._update()
            return v
        return {CCR: self.ccr, OAR1: self.oar1, OAR2: self.oar2, ECCR: self.eccr}.get(off, 0)

    def write(self, off, size, v):
        v &= 0xFF
        if self.trace is not None:
            self.trace.append(('W', off, v))
        if off == CR:
            self._write_cr(v)
        elif off == DR:
            self._write_dr(v)
        elif off == CCR:
            self.ccr = v
        elif off == OAR1:
            self.oar1 = v
        elif off == OAR2:
            self.oar2 = v
        elif off == ECCR:
            self.eccr = v
        self._update()

    def _write_cr(self, v):
        if not v & PE:                      # disabled: every flag and the transfer are dropped
            if self.sr1 & MSL:
                self.bus.stop()
            self.cr = v & (ENGC | ACK | ITE)
            self.sr1 = self.sr2 = 0
            self._sr2_read = self._addressed = False
            return
        self.cr = v & (PE | ENGC | ACK | ITE)
        if self._sr2_read and self.sr2 & ENDAD:     # ENDAD clear sequence completed: the data phase begins
            self.sr2 &= ~ENDAD
            self._sr2_read = False
            if self.sr1 & TRA:
                self.sr1 |= BTF                     # transmitter: data register empty
            else:
                self._receive()
        if v & START:                       # (repeated) start; the bit clears itself
            self.starts += 1
            self.sr1 = (self.sr1 & ~(BTF | TRA)) | SB | MSL | BUSY
            self.sr2 &= ~ENDAD
            self._addressed = False
        if v & STOP and self.sr1 & (MSL | BUSY):    # stop; the bit clears itself
            self.stops += 1
            self.bus.stop()
            if self.sr1 & TRA:
                self.sr1 &= ~BTF
            self.sr1 &= ~(MSL | BUSY | TRA | SB)
            self.sr2 &= ~ENDAD
            self._addressed = False

    def _write_dr(self, v):
        self.dr = v
        if self.sr1 & SB:                   # address byte
            self.sr1 &= ~SB
            if self.bus.start(v >> 1, bool(v & 1)):
                self._addressed = True
                self.sr2 |= ENDAD
                self._sr2_read = False
                if not v & 1:
                    self.sr1 |= TRA
            else:
                self.naks += 1
                self.sr2 |= AF
        elif self.sr1 & MSL and self.sr1 & TRA and self._addressed:
            self.bytes_tx += 1
            self.sr1 |= BTF                 # byte shifted out; BTF is set whatever the acknowledge was
            if not self.bus.write(v):
                self.naks += 1
                self.sr2 |= AF

    def _receive(self):
        self.dr = self.bus.read(bool(self.cr & ACK)) & 0xFF
        self.bytes_rx += 1
        self.sr1 |= BTF

    def summary(self):
        return (f'[{self.name}] starts {self.starts}, stops {self.stops}, bytes tx {self.bytes_tx} rx {self.bytes_rx}, '
                f'not acknowledged {self.naks}')
