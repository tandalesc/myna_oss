"""Deterministic emulated time (no unicorn import).

Time = executed instructions * ns_per_insn + time skipped while the guest sleeps in WFI.
`ips` is the assumed instruction rate: ARM926EJ-S at roughly 200 MHz, about 0.5 instructions per cycle, so 100 MIPS
by default (10 ns per instruction). Change it with Clock(ips=...) or clock.set_ips().
"""

CLK32K = 32768
TIMER_HZ = 4_094_000            # C001A004/8 counter clock: 0x3ff8 fine counts per 4 ms coarse step


class Clock:
    def __init__(self, ips=100_000_000):
        self.set_ips(ips)
        self.insns = 0
        self.skipped_ns = 0

    def set_ips(self, ips):
        self.ips = ips
        self.ns_per_insn = 1e9 / ips

    def sync(self, insns):
        """Called with the machine's executed-instruction count (slice granular) between slices."""
        self.insns = insns

    @property
    def now_ns(self):
        return int(self.insns * self.ns_per_insn) + self.skipped_ns

    def cycles(self, hz):
        """Ticks of a clock of `hz` since power-on."""
        return self.now_ns * hz // 1_000_000_000

    def ns_of_cycle(self, cycle, hz):
        """Earliest emulated time (ns) at which cycles(hz) >= cycle."""
        return -(-cycle * 1_000_000_000 // hz)

    def skip_to(self, ns):
        """Fast-forward (guest idle): advance time to `ns` without executing instructions."""
        now = self.now_ns
        if ns > now:
            self.skipped_ns += ns - now
