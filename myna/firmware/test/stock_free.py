#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Myna runs on the simulator without anything of the stock firmware: the telephony test (sim_telephony.py, both networks)
under an import guard.

    make -C myna/firmware
    native/.venv/bin/python -I myna/firmware/test/stock_free.py [ARGS OF sim_telephony.py]

The guard refuses, and records, an import of:
  - the stock modem stand-in (emu_modem_mock, with its release tables and its reference data), the boot-ROM model of the
    modem CPU (emu_rom_acc), the stand-ins at stock addresses (emu_shim)
  - a device profile that is not a firmware of our own (a folder of native/devices without BOOT_ELF), and the stock
    firmware's file tools of native/devices (source.py, container.py)
  - the stock key table (emu_keypad/keymap.py) and the stock phones' converter tables (emu_i2c/battery_stock.py)
  - Unicorn and capstone, unless --core unicorn is asked for: Myna's engine is the compiled core
A refused import counts even when the code around it catches the error. After the run, every file of the repository that
was imported must be in myna/web/platform.txt (the list that the page and the release take), in a BOOT_ELF device
folder, or in this folder (with --core unicorn also the Unicorn engine's files, which the release does not have). Exit
status 0 only when the telephony test passed and nothing was refused or unlisted.
"""
import importlib.abc, os, runpy, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
DEVICES = os.path.join(ROOT, 'native', 'devices')
BLOCKED_TOP = {'emu_modem_mock', 'emu_rom_acc', 'emu_shim', 'refdata', 'releases'}
BLOCKED = {'emu_keypad.keymap', 'devices.source', 'devices.container', 'emu_i2c.battery_stock'}
UNICORN_FILES = ('native/emu/machine.py', 'native/emu/decode.py')     # the Unicorn engine's side: allowed with --core unicorn only


def own_devices():
    """The device folders with a firmware of our own: their profile names BOOT_ELF."""
    out = set()
    for d in os.listdir(DEVICES):
        init = os.path.join(DEVICES, d, '__init__.py')
        if os.path.isfile(init):
            with open(init, encoding='utf-8') as f:
                if 'BOOT_ELF' in f.read():
                    out.add(d)
    return out


class Guard(importlib.abc.MetaPathFinder):
    def __init__(self, own, engines):
        self.own, self.engines, self.refused = own, engines, []

    def find_spec(self, name, path=None, target=None):
        parts = name.split('.')
        bad = (parts[0] in BLOCKED_TOP or name in BLOCKED or 'refdata' in parts or 'releases' in parts
               or (parts[0] == 'devices' and len(parts) > 1 and parts[1] not in self.own and name not in ('devices.myna',))
               or (parts[0] in ('unicorn', 'capstone') and not self.engines))
        if bad:
            self.refused.append(name)
            raise ImportError('stock_free.py: %s may not be imported by a run of Myna' % name)
        return None


def listed():
    with open(os.path.join(ROOT, 'myna', 'web', 'platform.txt'), encoding='utf-8') as f:
        return {os.path.join(ROOT, l.strip()) for l in f if l.strip() and not l.startswith('#')}


def main():
    args = sys.argv[1:]
    own = own_devices()
    guard = Guard(own, engines='unicorn' in args)
    sys.meta_path.insert(0, guard)
    sys.argv = [os.path.join(HERE, 'sim_telephony.py')] + args
    code = 0
    try:
        runpy.run_path(sys.argv[0], run_name='__main__')
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:                          # a refused import that nothing caught ends the run here
        print('stock-free: the run stopped: %s: %s' % (type(e).__name__, e))
        code = 1
    finally:
        sys.meta_path.remove(guard)
    allowed, unlisted, used = listed(), [], 0
    if guard.engines:
        allowed |= {os.path.join(ROOT, p) for p in UNICORN_FILES}
    for m in list(sys.modules.values()):
        f = getattr(m, '__file__', None)
        if not f or not os.path.abspath(f).startswith(ROOT + os.sep):
            continue
        f = os.path.abspath(f)
        rel = os.path.relpath(f, ROOT)
        if rel.startswith(os.path.join('native', '.venv') + os.sep):
            continue                                # the virtual environment's own start-up file
        used += 1
        in_device = any(f.startswith(os.path.join(DEVICES, d) + os.sep) for d in own)
        if not (f in allowed or in_device or f.startswith(HERE + os.sep)):
            unlisted.append(rel)
    print('stock-free: %d files of the repository imported; refused: %s; not in myna/web/platform.txt: %s' % (
        used, ', '.join(sorted(set(guard.refused))) or 'none', ', '.join(sorted(unlisted)) or 'none'))
    if guard.refused or unlisted:
        code = code or 1
    print('stock-free: %s' % ('PASS' if code == 0 else 'FAIL'))
    sys.exit(code)


if __name__ == '__main__':
    main()
