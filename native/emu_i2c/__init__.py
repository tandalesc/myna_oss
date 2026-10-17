"""I2C controller and slave models."""
from .master import I2cMaster
from .bus import I2cBus, RegisterSlave
from .devices import Ab3100, Ab3100Test, Max7327, LedCommandDriver, Lis302dl, Si470x
from .battery import Battery
from .soc_rtc import SocRtc, RTC_BASE

I2C0_BASE, I2C0_LINE = 0xC0004000, 42
I2C1_BASE, I2C1_LINE = 0xC0005000, 43
KEYPAD_BASE = 0xC0015000


class I2cSystem:
    """What attach() returns: .masters = [I2C0, I2C1] controllers, .buses = their I2cBus objects."""

    def __init__(self, masters, buses):
        self.masters, self.buses = masters, buses
        self.i2c0, self.i2c1 = masters
        self.bus0, self.bus1 = buses

    def summary(self):
        out = []
        for c, b in zip(self.masters, self.buses):
            out += [c.summary(), b.summary()] + [s.summary() for s in b.slaves.values()]
        if getattr(self, 'soc_rtc', None) is not None:
            out.append(self.soc_rtc.summary())
        return '\n'.join(out)


def _wrap(irq, fn, due=None):
    """Have the scheduler call fn() after its slices (IrqTimerSystem.wrap_step, with the time fn is next needed); an
    interrupt system that has only step() gets fn chained behind that."""
    if hasattr(irq, 'wrap_step'):
        return irq.wrap_step(fn, due)
    prev = irq.step
    def step():
        prev(); fn()
    irq.step = step


def connect_inputs(pmic, inputs):
    """Register the PMIC-backed switches of an emu_keypad Inputs object: `usb` and `charger` become level + event
    (status reg 0x27 bit7 / bit3, EVENTA1 bit6 / bit3 on every change) instead of the one-shot event latch."""
    inputs.backends['usb'] = lambda state: pmic.set_usb(state == 'in')
    inputs.backends['charger'] = lambda state: pmic.set_charger(state == 'in')
    pmic.inputs = inputs


def _device(machine, base):
    try:
        hit = machine.bus.find(base)
        return hit[1] if hit else None
    except Exception:
        return None


def _profile(machine):
    """The device profile of the run: the launcher's (machine.profile), else the selected one (devices.load()), else None."""
    p = getattr(machine, 'profile', None)
    if p is None:
        try:
            import importlib
            p = importlib.import_module('devices').load()
        except Exception:
            p = None
    return p


def attach(machine, irq_system, log=None, ctx=None, slaves=True):
    """One-line adoption: `i2c = emu_i2c.attach(machine, irq)` after IrqTimerSystem.install().

    Attaches the two controllers to the machine's device bus (0xC0004000 -> VIC line 42, 0xC0005000 -> line 43, through
    irq_system.vic.set_line) and, unless slaves=False, populates the two buses with the slave models of the phone
    (emu_i2c.devices.populate). `ctx` is an optional callable returning a context string (pc / process) for the
    "no slave" log lines; `log` defaults to machine.log."""
    log = log or machine.log
    masters, buses = [], []
    for name, base, line in (('I2C0', I2C0_BASE, I2C0_LINE), ('I2C1', I2C1_BASE, I2C1_LINE)):
        bus = I2cBus(name, log=log, ctx=ctx)
        dev = I2cMaster(name, bus, set_irq=lambda level, line=line: irq_system.vic.set_line(line, level), log=log)
        machine.attach(base, 0x1000, dev, name)
        masters.append(dev); buses.append(bus)
    sys_ = I2cSystem(masters, buses)
    if slaves:
        from . import devices, battery
        devices.populate(sys_, log=log, irq_system=irq_system, analog=battery.analog(_profile(machine)))
        # Power-on reason: EVENTA1 bit 0 = ON button (0x08/0x40 charger, EVENTA2 0x80 alarm). With none the firmware has no
        # reason to stay on.
        sys_.pmic.raise_event(a1=0x01)
        # Power off: the firmware clears LDO_D (PMIC 0x42) as the last step of its shut-down. The CPU has no supply after that
        # write, so the run ends there: a stop reason on the machine, which every runner reports as the reason the CPU stopped
        # (db3210: "[sim] stopped: APP: powered off by the phone at T ms ..."). EMU_POWER_OFF=0 only records it.
        import os
        if os.environ.get('EMU_POWER_OFF', '1') != '0':
            def power_off(pmic=sys_.pmic):
                machine.stop_reason = 'powered off by the phone at %.1f ms (PMIC LDO_D 0x42 = 0x00)' % (pmic.powered_off_ns / 1e6)
                machine.powered_off = True
                machine.uc.emu_stop()
            sys_.pmic.on_power_off = power_off
        kp = _device(machine, KEYPAD_BASE)      # emu_keypad attached first: hook up now; otherwise emu_keypad.attach does it
        if getattr(kp, 'inputs', None) is not None:
            connect_inputs(sys_.pmic, kp.inputs)
        # SoC RTC (0xC0017000): the firmware loads it from the PMIC clock and reads the time there. EMU_SOC_RTC=0 leaves it out.
        if os.environ.get('EMU_SOC_RTC', '1') != '0' and _device(machine, RTC_BASE) is None and hasattr(irq_system, 'now_ns'):
            rtc = sys_.soc_rtc = SocRtc(set_line=irq_system.vic.set_line, now_ns=irq_system.now_ns, log=log)
            machine.attach(RTC_BASE, 0x1000, rtc, 'SOC-RTC')
            if hasattr(irq_system, 'timers'):
                irq_system.timers.append(rtc)
            def step():
                if rtc.enable & 1:
                    rtc.advance()
                    machine.irq_pending = irq_system.vic.irq_out

            def due():                  # the alarm; an alarm time that has passed fires at once
                if not rtc.enable & 1: return None
                if rtc.alarm and not rtc._fired and rtc.seconds() >= rtc.alarm: return 0
                return rtc.next_event_ns()
            _wrap(irq_system, step, due)
        # FM tuner: its operations take time and end with a pulse on its interrupt pin (the board wires `fm.set_int`)
        if hasattr(irq_system, 'now_ns') and hasattr(irq_system, 'timers'):
            fm = sys_.fm
            irq_system.timers.append(fm)
            def step_fm():
                if fm._done_ns is not None or fm._pulse_ns is not None:
                    fm.advance()
                    machine.irq_pending = irq_system.vic.irq_out
            _wrap(irq_system, step_fm, fm.next_event_ns)
    return sys_
