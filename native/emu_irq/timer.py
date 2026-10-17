"""Sleep/OS timer block at 0xC001A000 (plain Python, no unicorn import).

Register semantics: [V] = proven by driver code, [I] = inferred. Time base: fine counter clock of 0x3ff8 counts per 4 ms coarse step (4.094 MHz).

  +0x04  coarse counter. [V] read until two reads agree.
  +0x08  fine counter, 15 bit mask 0x7fff. [V] read-until-stable; counts DOWN from 0x3ff7 to 0 and the
         coarse counter increments on each wrap (elapsed = 0x3ff7 - fine). [I]
         So cycles = coarse * 0x3ff8 + (0x3ff7 - fine).
         [I] Until the first write to the block the pair reads as stopped: coarse 0, fine 0x3ff7. No code proves this
         (no driver code starts the counter). Reason: an early clock routine takes a time stamp from the pair and
         compares a second reading with it before its tick-length hook is registered. If the coarse counter changes
         between the two readings the code calls the hook, which is still 0. With a running counter that happens
         for about 15 % of all phases (the readings are about 0.6 ms apart, a coarse step is 4 ms); a phone does not
         fail that way. The first write is the driver's set-up (+0x0C, then +0x2C, +0x28; about 3.75 s after
         power-on). From then on the pair shows the count since power-on, so the event times do not depend on it.
         What the pair shows right after the first write on the hardware (the count since power-on or a count from
         0) is not known.
  +0x0C  mode, bits 1:0. stored only.
  +0x10  event-0 interval: low 16 bits, in coarse steps (4 ms), until event 0; 0 = periodic tick at
         every coarse step (written by sleep code with the time to the next OS timeout, only while
         +0x2C bit 0 is set). [V write, I meaning]
  +0x18  free-running 32-bit counter read by delay loops. Here: cycles + read_step per read,
         so that busy-waits finish without wall time (same trick as emu/stubs.py FreeRunTimer). It runs from power-on:
         a boot loader reads it before any write to the block.
  +0x1C  bit0 enable (event 1 side), +0x24 wake-lead configuration, +0x2C bit0/bit1 enable events 0/1: stored.
  +0x28  event status: read bit0/bit1 = event pending (the kernel reads it to detect an expiry racing its
         sleep-time computation); write 1 to a bit clears it (the ISRs). [V]
Event 0 -> VIC line 28 (TIMER_OS), event 1 -> line 29 (TIMER_MS). Event 1 never fires here: its match register is
not identified.
"""
from .clock import TIMER_HZ

FINE_TOP = 0x3FF7
CYCLES_PER_COARSE = FINE_TOP + 1
UNIT = CYCLES_PER_COARSE       # +0x10 counts coarse steps (4 ms) [I]


class SleepTimer:
    name = 'TIMER-C001A000'

    def __init__(self, clock, set_line=None, line0=28, line1=29, read_step=100):
        self.clock = clock
        self.set_line = set_line or (lambda n, level: None)
        self.line0, self.line1 = line0, line1
        self.read_step = read_step
        self.extra = 0                 # accumulated +0x18 read advance
        self.regs = {}
        self.written = False           # no write to the block yet: the coarse / fine pair reads as stopped [I]
        self.held_reads = 0            # reads of the pair answered as stopped
        self.status = 0
        self.deadline0 = None          # 32 kHz cycle at which event 0 fires
        self.fired = 0
        self.arm_log = []              # (time_ns, cycles) every event-0 arming
        self.keep_log = True

    # ---- time ----
    def advance(self):
        """Fire events whose deadline has passed. Call between slices."""
        if self.deadline0 is not None and self.clock.cycles(TIMER_HZ) >= self.deadline0:
            self.deadline0 = None
            if self.regs.get(0x2C, 0) & 1:
                self.status |= 1
                self.fired += 1
                self._rearm()
        self._lines()

    def next_event_ns(self):
        """Emulated time of the next timer event, or None."""
        if self.deadline0 is None or not self.regs.get(0x2C, 0) & 1:
            return None
        return self.clock.ns_of_cycle(self.deadline0, TIMER_HZ)

    def pending_events(self):
        t = self.next_event_ns()
        return [] if t is None else [(t, 'C001A event 0 (OS sleep wake-up, line %d)' % self.line0, self.line0)]

    def _lines(self):
        self.set_line(self.line0, bool(self.status & 1))
        self.set_line(self.line1, bool(self.status & 2))

    # ---- bus ----
    def read(self, off, size):
        cyc = self.clock.cycles(TIMER_HZ)
        if not self.written and off in (0x04, 0x08):
            self.held_reads += 1
            return 0 if off == 0x04 else FINE_TOP
        if off == 0x04:
            return (cyc // CYCLES_PER_COARSE) & 0xFFFFFFFF
        if off == 0x08:
            return FINE_TOP - cyc % CYCLES_PER_COARSE
        if off == 0x18:
            self.extra += self.read_step
            return (cyc + self.extra) & 0xFFFFFFFF
        if off == 0x28:
            return self.status
        return self.regs.get(off, 0)

    def write(self, off, size, value):
        self.written = True
        if off == 0x28:
            self.status &= ~value & 3
            self._lines()
            return
        self.regs[off] = value
        if off == 0x10 and self.regs.get(0x2C, 0) & 1:
            n = value & 0xFFFF
            self.deadline0 = self.clock.cycles(TIMER_HZ) + n * UNIT if n else self._next_boundary()
            if self.keep_log:
                self.arm_log.append((self.clock.now_ns, n))
        elif off == 0x2C:
            if not value & 1:
                self.deadline0 = None
            elif self.deadline0 is None and not self.regs.get(0x10, 0) & 0xFFFF:
                self.deadline0 = self._next_boundary()

    def _next_boundary(self):
        c = self.clock.cycles(TIMER_HZ)
        return (c // UNIT + 1) * UNIT

    def _rearm(self):
        """Periodic mode: with +0x10 low 16 bits == 0 and event 0 enabled the timer ticks at every unit boundary."""
        if not self.regs.get(0x10, 0) & 0xFFFF:
            self.deadline0 = self._next_boundary()


class AppTimers:
    """TIMER_APP_OS / DD / GP1 / GP2 at 0xC0014000, 0x40 bytes per unit, VIC lines 24-27.

    Register storage only; no event ever fires. Their ISRs write 0x80 to unit+0x20.
    """
    name = 'TIMER_APP'

    def __init__(self):
        self.regs = {}

    def read(self, off, size):
        return self.regs.get(off & ~3, 0)

    def write(self, off, size, value):
        self.regs[off & ~3] = value

    def advance(self):
        pass

    def next_event_ns(self):
        return None

    def pending_events(self):
        return []
