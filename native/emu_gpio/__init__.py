"""SoC GPIO block (0xC0016000, VIC lines 32..36) with the slide and lens-cover inputs.

    --attach emu_gpio:attach            (db3210.py)
    g = emu_gpio.attach(machine, irq); g.block.set_switch('slide', 'open')

The `slide` and `lens_cover` switches of emu_keypad (`{"switch":"slide","state":"open"}` on its control channel) are routed here:
whichever of the two modules is attached second completes the hook-up (emu_gpio.connect_inputs), so the attach order does not matter.

Straps: a device profile may name GPIO_STRAPS = {(bank, pin): level}, input pins that resistors on its board tie high or low
(a board ID). They are external levels from power-on, set before the firmware runs; no interrupt, no pin event. A profile
without it (every stock one) leaves the levels of DEFAULT_EXT. Myna's flip: {(3, 0): 1} (myna/spec/07-gpio-power.md, 1.3).
"""
from .gpio import GpioBlock, PINS, LINE0, NBANKS

GPIO_BASE = 0xC0016000
KEYPAD_BASE = 0xC0015000


class GpioSystem:
    def __init__(self, block):
        self.block = block

    def summary(self):
        return self.block.summary()


def connect_inputs(block, inputs):
    """Register the GPIO-backed switches as backends of an emu_keypad Inputs object and take over its current switch states."""
    for name in PINS:
        if name in inputs.switches:             # slide, lens_cover (memstick is not an emu_keypad switch: block.set_switch only)
            inputs.backends[name] = lambda state, name=name: block.set_switch(name, state)
            block.set_switch(name, inputs.switches[name])
    block.inputs = inputs


def _device(machine, base):
    try:
        hit = machine.bus.find(base)
        return hit[1] if hit else None
    except Exception:
        return None


def apply_straps(block, straps):
    """The board's strapped input levels (GPIO_STRAPS of the profile), as external levels from power-on."""
    for (bank, pin), level in sorted((straps or {}).items()):
        if not (0 <= bank < NBANKS and 0 <= pin < 8):
            raise ValueError('GPIO_STRAPS: no pin %d of bank %d' % (pin, bank))
        bit = 1 << pin
        block.ext[bank] = (block.ext[bank] & ~bit) | (bit if level else 0)


def attach(machine, irq_system, log=None):
    log = log or machine.log
    block = GpioBlock(set_line=irq_system.vic.set_line, log=log)
    apply_straps(block, getattr(getattr(machine, 'profile', None), 'GPIO_STRAPS', None))
    machine.attach(GPIO_BASE, 0x1000, block, 'GPIO')
    kp = _device(machine, KEYPAD_BASE)          # emu_keypad attached first: hook up now; otherwise emu_keypad.attach does it
    if getattr(kp, 'inputs', None) is not None:
        connect_inputs(block, kp.inputs)
    return GpioSystem(block)
