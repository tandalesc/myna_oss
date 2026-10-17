"""APP 0xC0040000..0xC0047fff: the "AVE" block, a DSP interface with its own RAM. No unicorn import.

What a driver does with it at start-up [V code + register trace]:
  1. clears 0x3000 bytes at +0x0000 (word writes of 0): the block's RAM
  2. +0x307c = 0x40, then 0          3. +0x306c = 0          4. +0x3028 = 0x2044          5. +0x3020 = 0x140c1001
  6. polls +0x307c until bits 12, 13 and 15 are all set (no time-out, interrupts enabled)
  7. +0x307c = 0x40, then 0          8. reads +0x3078 once (the version)
Nothing else touched the block in 20 s of an idle boot.

Model:
  [V need] +0x3020 written with bit0 set = start: from then on +0x307c reads with 0xb000 set ("running"); bit0 clear takes it away
  [I] the write of 0x40 to +0x307c is an acknowledge pulse: stored, it does not clear the ready bits (the driver writes it both
      before the start and right after seeing them, then 0)
  [?] +0x3078 version reads AVE_VERSION (0: the real value is unknown; the firmware only prints it)
  [MOCK] everything else is plain storage. No interrupt is raised, no job is executed: an access outside the list above is logged
      (first LOG_LIMIT) so that the first real use of the block (video / codec job) shows up as '[ave] UNMODELLED ...'.
"""
RAM_END = 0x3000
CTRL, CFG, R6C, VERSION, STATUS = 0x3020, 0x3028, 0x306c, 0x3078, 0x307c
READY = 0xb000
AVE_VERSION = 0
LOG_LIMIT = 40


class Ave:
    name = 'AVE'

    def __init__(self, log=None):
        self.r = {}
        self.log = log or (lambda s: None)
        self.running = False
        self.starts = 0
        self.unmodelled = 0
        self.nread = self.nwrite = 0

    def _note(self, kind, off, v):
        self.unmodelled += 1
        if self.unmodelled <= LOG_LIMIT:
            self.log('[ave] UNMODELLED %s +%#06x %s%#x (storage only)' % (kind, off, '= ' if kind == 'read' else '<= ', v))

    def read(self, off, size):
        self.nread += 1
        a = off & ~3
        v = self.r.get(a, 0)
        if a == STATUS:
            v = (v & ~READY) | (READY if self.running else 0)
        elif a == VERSION:
            v = AVE_VERSION
        elif a >= RAM_END and a not in (CTRL, CFG, R6C):
            self._note('read', off, v)
        return (v >> (8 * (off & 3))) & ((1 << (8 * size)) - 1)

    def write(self, off, size, v):
        self.nwrite += 1
        a = off & ~3
        if size != 4:                                   # byte / halfword lanes into the stored word
            sh = 8 * (off & 3); mask = ((1 << (8 * size)) - 1) << sh
            v = (self.r.get(a, 0) & ~mask) | ((v << sh) & mask)
        self.r[a] = v & 0xFFFFFFFF
        if a == CTRL:
            run = bool(v & 1)
            if run and not self.running:
                self.starts += 1
                self.log('[ave] started (+0x3020 <= %#x, +0x3028 = %#x)' % (v, self.r.get(CFG, 0)))
            self.running = run
        elif a >= RAM_END and a not in (CFG, R6C, STATUS):
            self._note('write', off, v)

    def summary(self):
        return 'AVE: %d reads, %d writes, started %d time(s), running %s, accesses outside the modelled start-up: %d' % (
            self.nread, self.nwrite, self.starts, self.running, self.unmodelled)


def attach(m, irq):
    """db3210 --attach emu_dsp:attach"""
    dev = Ave(log=lambda s: print(s, flush=True))
    m.attach(0xC0040000, 0x8000, dev, 'AVE')
    return dev
