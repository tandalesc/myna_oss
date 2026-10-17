"""DB3210 native-firmware emulator core (see README.md)."""


def __getattr__(name):
    # the Unicorn machine is imported when it is first asked for: emu.bus, emu.uart, emu.loaders, emu.mmu need no Unicorn
    if name in ('Machine', 'PCORE_ENTRY'):
        from . import machine
        return getattr(machine, name)
    raise AttributeError('module %r has no attribute %r' % (__name__, name))
