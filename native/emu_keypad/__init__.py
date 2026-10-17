"""Inputs: keypad matrix controller (0xC0015000, VIC lines 30/31) + Inputs object + JSON-lines control channel.

    --attach emu_keypad:attach            (db3210.py; control file from the environment variable EMU_KEYPAD_CTL, poll period EMU_KEYPAD_POLL_MS)
    kp = emu_keypad.attach(machine, irq, ctl_path='/tmp/keys.jsonl'); kp.inputs.press('select')

No change to the harness is needed: the model wraps `irq_system.step` (which Machine.run calls between slices and db3210 looks up per slice)
for its periodic work, and registers a timer-protocol object so an idle (WFI) CPU is woken for a scheduled release.
"""
import importlib
import os

from .keypad import KeypadController, LINE_BF, LINE_BR
from .inputs import Inputs, default_keymap

KEYPAD_BASE = 0xC0015000


def __getattr__(name):
    """keymap and its tables (KEY_INDEX, KEY_CODE, MATRIX, SWITCHES) on first use: a device with a key map of its own (KEYMAP)
    never imports the default one, which holds the stock firmware's key codes."""
    if name == 'keymap':
        return default_keymap()
    if name in ('KEY_INDEX', 'KEY_CODE', 'MATRIX', 'SWITCHES'):
        return getattr(default_keymap(), name)
    raise AttributeError('module %r has no attribute %r' % (__name__, name))


class KeypadSystem:
    def __init__(self, controller, inputs):
        self.ctl, self.inputs = controller, inputs

    def summary(self):
        return self.ctl.summary() + '; inputs applied %d' % len(self.inputs.applied)


def _find_pmic(machine):
    """The AB3100 model of emu_i2c (I2C0 at 0xC0004000, slave 0x48), if attached; looked up lazily so the attach order does not matter."""
    def get():
        try:
            hit = machine.bus.find(0xC0004000)
            return hit[1].bus.slaves.get(0x48)
        except Exception:
            return None
    return get


def _connect_gpio(machine, inputs):
    """Route the `slide` and `lens_cover` switches to the SoC GPIO model (native/emu_gpio, 0xC0016000) if it is attached."""
    try:
        hit = machine.bus.find(0xC0016000)
        if hit and hasattr(hit[1], 'set_switch'):
            import emu_gpio
            emu_gpio.connect_inputs(hit[1], inputs)
    except Exception:
        pass


def _connect_accel(machine, inputs):
    """Route the `orientation` switch to the accelerometer model of emu_i2c (I2C1 at 0xC0005000, slave 0x1d). The model is
    looked up each time, so the attach order does not matter; without it the switch only changes its recorded state. The
    readings of each position come from the device's key map (ORIENTATION_G), else from the default one."""
    ORIENTATION_G = getattr(inputs.km, 'ORIENTATION_G', None) or default_keymap().ORIENTATION_G

    def apply(state):
        try:
            accel = machine.bus.find(0xC0005000)[1].bus.slaves.get(0x1D)
        except Exception:
            accel = None
        if accel is not None and hasattr(accel, 'set_phone_g'):
            accel.set_phone_g(*ORIENTATION_G[state])
    inputs.backends['orientation'] = apply
    apply(inputs.switches['orientation'])


def _connect_pmic(machine, inputs):
    """Route the `usb` and `charger` switches to the PMIC model (native/emu_i2c: status level + event) if it is attached."""
    try:
        pmic = _find_pmic(machine)()
        if pmic is not None and hasattr(pmic, 'set_usb'):
            import emu_i2c
            emu_i2c.connect_inputs(pmic, inputs)
    except Exception:
        pass


def device_keymap(profile=None):
    """The key map module of a device: the module that the profile names in KEYMAP, else emu_keypad.keymap (the stock key table).
    Without a profile: the selected device (devices.load())."""
    if profile is None:
        import devices
        profile = devices.load()
    name = getattr(profile, 'KEYMAP', None)
    return importlib.import_module(name) if name else default_keymap()


def attach(machine, irq_system, log=None, ctl_path=None, poll_ms=None):
    log = log or (lambda s: print(s, flush=True))
    ctl = KeypadController(set_line=irq_system.vic.set_line, log=log)
    machine.attach(KEYPAD_BASE, 0x1000, ctl, 'KEYPAD')
    ctl_path = ctl_path or os.environ.get('EMU_KEYPAD_CTL') or None
    poll_ms = float(poll_ms or os.environ.get('EMU_KEYPAD_POLL_MS') or 20.0)
    inputs = Inputs(ctl, irq_system.now_ns, log=log, poll_ms=poll_ms, ctl_path=ctl_path, pmic=_find_pmic(machine), keymap=device_keymap())
    ctl.inputs = inputs                         # lets emu_gpio.attach find the Inputs object when it is attached after us
    _connect_gpio(machine, inputs)              # ... and this covers emu_gpio attached before us (slide / lens_cover backends)
    _connect_pmic(machine, inputs)              # same for emu_i2c (usb / charger backends)
    _connect_accel(machine, inputs)             # the `orientation` switch -> accelerometer readings
    if hasattr(irq_system, 'timers'):
        irq_system.timers.append(inputs)        # next_event_ns() keeps an idle CPU waking for scheduled actions
    def tick():
        inputs.advance()
        machine.irq_pending = irq_system.vic.irq_out      # a line raised by advance() must reach the CPU in this very step

    def due():                                  # the next scheduled action, the next look at the control file
        t = inputs.sched[0][0] if inputs.sched else None
        if inputs.ctl_path and (t is None or inputs._next_poll_ns < t): t = inputs._next_poll_ns
        return t
    if hasattr(irq_system, 'wrap_step'):
        irq_system.wrap_step(tick, due)
    else:
        prev_step = irq_system.step
        def step():
            prev_step()
            tick()
        irq_system.step = step
    sys_ = KeypadSystem(ctl, inputs)
    if ctl_path:
        log('[sim] keypad: control file %s (poll %.0f ms emulated)' % (ctl_path, poll_ms))
    return sys_
