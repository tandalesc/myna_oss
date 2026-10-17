#!/usr/bin/env python3
"""Boot the stock firmware of a device (--device, default: the selected device, devices.selected()) from its boot loader with the
device models attached. The launcher of a firmware of our own (native/sim/db3210.py) imports SysCtrl and chip_path from here.

  native/.venv/bin/python -I native/boot.py [--device NAME] [--platform 0xE8] [--max-seconds N] [--trace-calls] [--report] [--break ADDR]

Needs the two firmware containers of the device, as downloaded, or the factory flash image made from them (README.md, "Quick start").
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'emu_nand'))
from emu.stubs import FreeRunTimer, NoCardMmci
import nand_model
from emu_irq import IrqTimerSystem
import devices


def chip_path(profile, want='factory', say=None):
    """The flash image a run starts from: SIM_CHIP (another image, tools/fs_install.py), else the profile's factory image, or
    its custom image for want='custom'. An image that is not in place is made from the downloaded firmware files
    (devices/source.py); raises source.Missing when they are not there."""
    from devices import source
    return os.environ.get('SIM_CHIP') or source.chip(profile, want, say)


class SysCtrl:
    """0xC0011000 system block: only the chip-id word is known. Other registers keep what was written."""

    def __init__(self, platform):
        self.regs = {0x400: platform}

    def read(self, off, size):
        return self.regs.get(off, 0)

    def write(self, off, size, value):
        self.regs[off] = value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--device', default=devices.selected(), help='device profile (module of native/devices)')
    ap.add_argument('--platform', type=lambda x: int(x, 0), default=0xE8,
                    help='low byte of 0xC0011400: 0xC8/0xD8/0xE8/0xF0 = platform revision 1..4')
    ap.add_argument('--max-seconds', type=float, default=120)
    ap.add_argument('--trace-calls', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--no-irq', action='store_true', help='do not attach the VIC pair / sleep timer (use the free-run stub)')
    ap.add_argument('--ips', type=float, default=100e6, help='emulated instructions per second (timer time base)')
    ap.add_argument('--break', dest='breaks', action='append', default=[], type=lambda x: int(x, 0))
    a = ap.parse_args()

    from emu.machine import Machine          # here: the classes above are also used where Unicorn is not installed
    from devices import source               # here: the launcher imports this file for SysCtrl alone in a run of a firmware of our own
    profile = devices.select(a.device)
    try:
        chip = chip_path(profile, say=lambda s: print('[boot] ' + s, flush=True))
        for line in source.warnings(profile, source.untested(chip)): print('[boot] ' + line, flush=True)
        pcore = devices.image(profile, 'PCORE.CXC', chip)
    except source.Missing as e:
        sys.exit('\n'.join('[boot] ' + line for line in str(e).splitlines()))
    m = Machine(uart_log=devices.run_file('boot-uart.log', profile))
    m.load_pcore(pcore)
    m.plant_boot_stubs()
    m.attach(0xC0011000, 0x1000, SysCtrl(a.platform))
    m.attach(0xC0001000, 0x1000, NoCardMmci())
    irq = None
    if a.no_irq:
        m.attach(0xC001A000, 0x1000, FreeRunTimer())
    else:
        irq = IrqTimerSystem(m, ips=a.ips).install()      # VIC0/VIC1 + timer block at 0xC001A000 + WFI fast-forward
    nand = nand_model.NandSystem(chip, platform_version=a.platform)
    for base, size, dev in nand.windows():
        m.attach(base, size, dev)
    if a.trace_calls:
        m.enable_call_trace()
    for b in a.breaks:
        m.add_break(b)
    why = m.run(devices.pcore_entry(profile, chip), max_seconds=a.max_seconds, step=irq.step if irq else None, slice_insns=20000)
    print(f'\n[stopped: {why}; {m.insns:,} insns]')
    print(m.dump_regs())
    if irq:
        print(irq.summary())
    if a.report:
        for addr, (pc, kind, n, last, ok) in sorted(m.bus.touched.items()):
            if not ok:
                print(f'  {addr:#010x} {kind:2s} x{n:<6d} first pc {pc:#010x} last {last:#x}')


if __name__ == '__main__':
    main()
