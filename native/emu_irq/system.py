"""Wiring: VIC pair + sleep timer + clock + idle (WFI) fast-forward, for a Machine (emu/machine.py).

    sys_ = IrqTimerSystem(machine, ips=100_000_000)
    sys_.install()                       # attaches the devices and takes over machine.step via sys_.step
    machine.run(entry, step=sys_.step)

Core interface used (no core change needed): Machine.attach, Machine.irq_pending (level output to the CPU),
Machine.insns (slice granular), Machine.read_virt, Machine.stop_reason, Machine.stop_on_wfi.
"""
import os
from .clock import Clock
from .vic import VicPair
from .timer import SleepTimer, AppTimers

VIC0_BASE, VIC1_BASE, TIMER_BASE, APP_TIMER_BASE = 0xA0001000, 0xA0002000, 0xC001A000, 0xC0014000
WFI_MASK, WFI_BITS = 0xFFFF0FFF, 0xEE070F90          # mcr p15,0,Rd,c7,c0,4


class IrqTimerSystem:
    def __init__(self, machine, ips=100_000_000, log=None):
        self.m = machine
        self.log = log or machine.log
        self.clock = Clock(ips)
        self.vic = VicPair(on_irq=self._irq, on_fiq=self._fiq)
        self.timer = SleepTimer(self.clock, self.vic.set_line)
        self.app_timers = AppTimers()
        self.timers = [self.timer, self.app_timers]      # every device with next_event_ns() / advance() / pending_events()
        self.irq_taken_hint = 0
        self.idle_count = 0
        self.idle_skipped_ns = 0
        self.stalled = False
        self.irq_injected = 0
        self.unmask_timeouts = 0
        self.trace = []                 # (time_ns, insns, event) small ring
        self.trace_limit = 200
        self.steppers = []              # (fn, due) in attach order: what wrap_step() added to step()
        self.step_due = 0               # emulated time (ns) from which the steppers have work again (INF: none known)
        self.steps_run = self.steps_skipped = 0
        self.lazy_steps = os.environ.get('SIM_STEP_EVERY', '0') == '0'      # SIM_STEP_EVERY=1: the steppers after every slice, whatever the machine

    def install(self):
        m = self.m
        m.attach(VIC0_BASE, 0x1000, self.vic.vic0, 'VIC0')
        m.attach(VIC1_BASE, 0x1000, self.vic.vic1, 'VIC1')
        m.attach(TIMER_BASE, 0x1000, self.timer)
        m.attach(APP_TIMER_BASE, 0x1000, self.app_timers)
        m.idle_cb = self.idle
        return self

    # the VIC output is a level; the Machine injects when pending and CPSR.I is clear
    def _irq(self, level):
        self.m.irq_pending = level

    def _fiq(self, level):
        pass                            # FIQ is not modelled

    def _note(self, what):
        if len(self.trace) < self.trace_limit:
            self.trace.append((self.clock.now_ns, self.m.insns, what))

    def step(self):
        """Called by Machine.run between slices: the clock, the timer, the interrupt output, then the steppers (wrap_step) in
        the order they were added.
        A machine that says when one of its devices was reached (attribute `touched`: set by the machine at every device
        access that arrives at a model, at every entry hook and by whoever acts on a model from outside a run; cleared
        here) lets the steppers rest while nothing can have changed for them: they are run after a slice in which the
        machine was touched and from the time the earliest of their `due` functions named. A machine without the
        attribute gets them after every slice."""
        m = self.m
        self.clock.sync(m.insns)
        self.timer.advance()
        m.irq_pending = self.vic.irq_out
        steppers = self.steppers
        if not steppers:
            self.step_due = float('inf')
        else:
            touched = getattr(m, 'touched', None) if self.lazy_steps else None
            if touched is None:
                for fn, _due in steppers: fn()
            elif touched or self.clock.now_ns >= self.step_due:
                m.touched = False
                for fn, _due in steppers: fn()
                self.steps_run += 1
                self.step_due = self.steppers_due()
            else:
                self.steps_skipped += 1

    def wrap_step(self, fn, due=None):
        """Run fn() at the end of every step(), after what was added before. due() -> the earliest emulated time (ns) at which
        fn can have work if until then no device of the machine is reached and nothing acts on a model from outside (None:
        no such time; a time that is not in the future: now). It must not change anything. Without `due`, fn is needed
        after every slice. Something that replaced step() by hand (irq.step = ...) keeps the order: what is added after
        it is chained behind it the same way, and runs after every slice."""
        if 'step' in self.__dict__:
            prev = self.step
            def step():
                prev(); fn()
            self.step = step
        else:
            self.steppers.append((fn, due if due is not None else (lambda: 0)))
            self.step_due = 0

    def steppers_rest(self):
        """True when step() lets the steppers rest (see there): `step_due` is then the time from which they are needed."""
        return self.lazy_steps and 'step' not in self.__dict__ and getattr(self.m, 'touched', None) is not None

    def steppers_due(self):
        """The earliest time one of the steppers is due, INF when none names a time."""
        now, best = self.clock.now_ns, float('inf')
        for _fn, due in self.steppers:
            t = due()
            if t is not None and t < best:
                if t <= now: return t
                best = t
        return best

    def idle(self):
        """Machine.idle_cb: the CPU sits after WFI. Fast-forward emulated time to the next timer event."""
        if self.vic.irq_out:
            return True
        t = self.next_event_ns()
        if t is None:
            self.stalled = True
            return False
        before = self.clock.now_ns
        self.clock.skip_to(t)
        self.idle_count += 1
        self.idle_skipped_ns += self.clock.now_ns - before
        if self.idle_count == 1:
            self.log('[irq] first idle (WFI) at %.3f ms emulated, skipping to the next timer event' % (before / 1e6))
        self._note('idle: skipped %.3f ms to timer event' % ((self.clock.now_ns - before) / 1e6))
        self.timer.advance()
        self.m.irq_pending = self.vic.irq_out
        return True

    # ---- inspection ----
    def next_event_ns(self):
        ts = [t for t in (d.next_event_ns() for d in self.timers) if t is not None]
        return min(ts) if ts else None

    def pending_events(self):
        """List of (time_ns, description, line) for every armed timer event, soonest first."""
        out = []
        for d in self.timers:
            out.extend(d.pending_events())
        return sorted(out)

    def now_ns(self):
        return self.clock.now_ns

    def describe(self):
        """Human-readable timeline: emulated time and the armed events, for other packages."""
        ev = self.pending_events()
        lines = ['emulated time %.3f ms (%d instructions + %.3f ms idle skipped)'
                 % (self.clock.now_ns / 1e6, self.clock.insns, self.clock.skipped_ns / 1e6)]
        lines += ['  %12.3f ms  line %-2d %s' % (t / 1e6, line, what) for t, what, line in ev] or ['  no timer event armed']
        return '\n'.join(lines)

    def summary(self):
        return ('[irq] emulated %.1f ms, idle skips %d (%.1f ms), timer events %d, IRQs taken %d, VIC0 vector reads %d'
                % (self.clock.now_ns / 1e6, self.idle_count, self.idle_skipped_ns / 1e6, self.timer.fired,
                   self.vic.irq_edges, self.vic.vic0.reads_vect))
