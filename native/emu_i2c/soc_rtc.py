"""SoC real-time clock block at 0xC0017000 (VIC line 44).

It lives in this package because it is the other half of the PMIC clock: at start-up a driver copies the AB3100 time
(reg 0x5a..0x5f, Unix seconds in bytes 2..5) into +0x04 and from then on every "get time" reads +0x0c.

    +0x00  alarm match, seconds                         [V] written with the alarm time
    +0x04  load: write = set the counter                [V] (the driver then waits 100 ms)
    +0x0c  counter, Unix seconds, read                  [V]
    +0x10  bit0 = alarm pending, write 1 to clear       [V] the ISR reads it and writes it back with bit0 set
    +0x14  bit0 = alarm interrupt enable                [V] set at arming, cleared by the ISR
Counting rate (1 Hz from the 32 kHz clock), the match condition (counter >= alarm) and anything else in the block: [I].
"""
RTC_BASE, RTC_LINE = 0xC0017000, 44


class SocRtc:
    name = 'SOC-RTC'

    def __init__(self, set_line=None, now_ns=None, log=None):
        self.set_line = set_line or (lambda n, level: None)
        self.now_ns = now_ns or (lambda: 0)
        self.log = log or (lambda s: None)
        self.base, self.t0 = 0, 0       # counter = base + whole seconds since t0
        self.alarm = 0
        self.pending = 0
        self.enable = 0
        self.regs = {}
        self.loads = []                 # (ns, seconds) every write to +0x04
        self._level = False
        self._fired = False            # the match is an event: one pending bit per programmed alarm

    def seconds(self):
        return (self.base + (self.now_ns() - self.t0) // 1_000_000_000) & 0xFFFFFFFF

    def _update(self):
        level = bool(self.pending & self.enable & 1)
        if level != self._level:
            self._level = level
            self.set_line(RTC_LINE, level)

    def read(self, off, size):
        self.advance()
        if off == 0x00: return self.alarm
        if off == 0x0C: return self.seconds()
        if off == 0x10: return self.pending
        if off == 0x14: return self.enable
        return self.regs.get(off, 0)

    def write(self, off, size, value):
        if off == 0x00:
            self.alarm = value & 0xFFFFFFFF; self._fired = False
        elif off == 0x04:
            self.base, self.t0 = value & 0xFFFFFFFF, self.now_ns()
            self.loads.append((self.t0, self.base)); del self.loads[:-16]
            self._fired = False
        elif off == 0x10:
            self.pending &= ~value & 1
        elif off == 0x14:
            self.enable = value & 0xFFFF
        else:
            self.regs[off] = value
        self.advance()

    # ---- timer protocol of emu_irq.IrqTimerSystem (keeps an idle CPU waking for the alarm) ----
    def next_event_ns(self):
        if not (self.enable & 1) or self._fired or self.alarm <= self.seconds():
            return None
        return self.t0 + (self.alarm - self.base) * 1_000_000_000

    def pending_events(self):
        t = self.next_event_ns()
        return [(t, 'SoC RTC alarm', RTC_LINE)] if t is not None else []

    def advance(self):
        if self.enable & 1 and self.alarm and not self._fired and self.seconds() >= self.alarm:
            self.pending |= 1; self._fired = True
        self._update()

    def summary(self):
        return '[%s] counter %d, alarm %d (enable %d, pending %d), loads %s' % (
            self.name, self.seconds(), self.alarm, self.enable & 1, self.pending & 1,
            ' '.join('%d@%.1fms' % (s, t / 1e6) for t, s in self.loads) or '-')
