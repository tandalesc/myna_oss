"""machine.py: the simulator's `Machine` on the compiled core (dbcore.Core) instead of Unicorn.

Same surface as emu.machine.Machine as far as the launcher (sim/db3210.py), the attach modules and the device models use it:
memory map, device bus, boot-ROM stand-ins, entry hooks, the interrupt input, the slice loop. The device models are the same
Python objects (`read(off, size)`, `write(off, size, value)`); every hardware window is an external window of the core whose
callbacks go to the bus. `Machine.uc` is a small object with the Unicorn calls the models use (mem_read, mem_write, reg_read,
reg_write, ...), so no model has to change.

What differs from the Unicorn machine, by design:
- Exceptions (aborts, SWI, undefined instruction, IRQ) are taken inside the core. A slice does not end at one.
- `insns` counts the instructions the core completed. (The Unicorn machine charges a whole slice when a slice ends at an abort
  or SWI, and one instruction when it ends at a wait-for-interrupt.)
- The interrupt input is a level given to the core, which samples it at every instruction boundary.
- A wait-for-interrupt is reported by the core; nothing is guessed from the code before the pc.
- No polling-loop skip, no block slices.
- An MCR / MRC p15 in user mode takes the undefined-instruction exception; `undefined_summary()` lists such events.
- `uc.mem_read` / `uc.mem_write` raise MemError for a span that is not inside one piece of RAM or one hardware window
  mapped on purpose (Unicorn: UcError); memory the core mapped by itself at a first access is not reachable through them.

Compiled devices. Some device models have a compiled twin inside the core that behaves as the Python model does. `devices`
(constructor argument; else the environment variable DBCORE_DEVICES; a comma-separated list, `all` or `none`) chooses per
device; the default is all of them (DEVICES):
- `nand`: the data port of the NAND model and its three bookkeeping accesses (ready poll, timing registers, address cycles).
  `add_native_port` / `add_native_window` give the model what emu/native_port.py gives it on the Unicorn machine; the model
  itself is unchanged and keeps everything else. Without it `add_native_port` returns None and the model serves every access.
- `nandcmd` (needs `nand`): the command state machine of the NAND model with its page register and ECC engine (NandInCore
  below). The contents of the chip stay with the model, which the core calls once per page read, program and erase.
- `timer`: the sleep / OS timer (emu_irq.timer.SleepTimer) and with it the clock (emu_irq.clock.Clock).
- `vic`: the pair of interrupt controllers (emu_irq.vic.VicPair). They then drive the interrupt input of the CPU themselves.
- `sysctl`, `clkprof`: the launcher's system control block (AppSysCtrl) and clock profile (ClockProfile): registers that
  store what is written, with a rule or two for reads. A twin is used only when it answers a fixed sequence of accesses
  as the object attached does, so a model that has changed since stays in Python. While `bus.write` is replaced by
  something that is not the bus's own method (the launcher wraps it to see the writes of the boot loader), the writes to
  system control are declined by the core and take that way.
A device is taken over when its Python object is attached (`attach`): the state it has goes into the core, and the object
stays in place as a view (same class plus a mix-in below): its attributes and methods read and change the state in the core,
so the scheduler, the other models and the tools go on using it as before. The clock stays the one clock of the Python
models: the view keeps a copy that is equal to the core's at all times, because every change is made through it.

The core. Everything here goes through the methods of dbcore.Core, so a machine can be made on any object that has them:
`Machine(core=...)` takes one made by the caller (dbcore_wasm.Core over the WebAssembly module, in a browser); without it
the machine asks Machine.make_core when that is set, and else makes a dbcore.Core, whose needs are those of dbcore.py
(DBCORE_LIB or DBCORE_OUT). Two things only a core in
the address space of the host can do, and the core says so (Core.HOST_POINTERS): C function pointers for the helper of
emu/native_port.py (add_native_window returns (None, None) without them; the windows are served all the same), and a
host address as the target of uc.mem_map_ptr (without them the caller passes a writable buffer instead).

The modules of the emulator tree (emu.bus, emu.uart, emu.loaders, emu.mmu) are imported from sys.path, as the launcher
sets it up. Where the package `emu` cannot be imported as a whole (its __init__ brings in the Unicorn machine), those
four are taken from its folder alone.
SPDX-License-Identifier: MIT"""
import atexit
import collections
import copy
import importlib
import operator
import os
import random
import struct
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbcore


def _emu(*names):
    """The named modules of the package `emu`. When the package does not import (no Unicorn here), it is entered as a
    bare folder, without running its __init__: none of the modules asked for needs it."""
    try:
        return [importlib.import_module('emu.' + n) for n in names]
    except ImportError:
        if 'emu' in sys.modules:
            raise
        folder = next((d for d in (os.path.join(p or '.', 'emu') for p in sys.path) if os.path.isfile(os.path.join(d, names[0] + '.py'))), None)
        if folder is None:
            raise
        pkg = types.ModuleType('emu'); pkg.__path__ = [folder]
        sys.modules['emu'] = pkg
        try:
            return [importlib.import_module('emu.' + n) for n in names]
        except ImportError:
            del sys.modules['emu']
            raise


loaders, mmu, _bus, _uart = _emu('loaders', 'mmu', 'bus', 'uart')
Bus, Uart = _bus.Bus, _uart.Uart

PAGE = 0x1000
SDRAM_BASE, SDRAM_SIZE = 0x48000000, 0x04000000
TCM_SIZE = 0x10000
HW_REGIONS = [(0xA0000000, 0x10000000), (0xC0000000, 0x10000000), (0x60000000, 0x10000000), (0x80000000, 0x20000000)]
STUB_BASE = 0x4bffe000                 # boot-ROM stand-ins: an unused page at the top of SDRAM
UART_BASE = 0xC0013000
M32 = 0xFFFFFFFF

# Unicorn's register numbers (unicorn.arm_const), which the models pass to uc.reg_read / reg_write -> ids of the core
UC_CPSR, UC_LR, UC_PC, UC_SP, UC_SPSR, UC_R0, UC_CP_REG = 3, 10, 11, 12, 13, 66, 139
REG = {UC_CPSR: dbcore.CPSR, UC_LR: dbcore.LR, UC_PC: dbcore.PC, UC_SP: dbcore.SP, UC_SPSR: dbcore.SPSR}
REG.update({UC_R0 + i: i for i in range(13)})
GPR = [UC_R0 + i for i in range(13)] + [UC_SP, UC_LR, UC_PC]
# cp15 (crn, crm, op1, op2) -> id of the core
CP15 = {(1, 0, 0, 0): dbcore.SCTLR, (2, 0, 0, 0): dbcore.TTBR, (3, 0, 0, 0): dbcore.DACR, (13, 0, 0, 0): dbcore.FCSE,
        (5, 0, 0, 0): dbcore.DFSR, (5, 0, 0, 1): dbcore.IFSR, (6, 0, 0, 0): dbcore.FAR}
CP15_CONST = {(0, 0, 0, 0): 0x41069265, (0, 0, 0, 1): 0x01DD20D2}
VECTOR_CUTS = (0x08, 0x0C, 0x10, 0xFFFF0008, 0xFFFF000C, 0xFFFF0010)      # SWI, prefetch abort, data abort; low and high vectors
IRQ_VECTORS = (0x18, 0xFFFF0018)
EVENT_NAMES = {1: 'data abort', 2: 'prefetch abort', 3: 'SWI', 4: 'undefined instruction', 5: 'IRQ', 6: 'FIQ'}
CURVE_SLICES = 250
EVENT_LOG_KEEP = 4096                       # entries of the core's exception log at which run() counts and empties it
DEVICES = ('nand', 'nandcmd', 'timer', 'vic', 'sysctl', 'clkprof')      # the devices that have a compiled twin; all of them are used by default


def device_set(spec=None):
    """The compiled devices to use: `spec` (a list of names, or a string as DBCORE_DEVICES), else DBCORE_DEVICES, else all."""
    if spec is None:
        spec = os.environ.get('DBCORE_DEVICES')
    if spec is None:
        return frozenset(DEVICES)
    names = [x.strip() for x in spec.split(',')] if isinstance(spec, str) else list(spec)
    out = set()
    for n in names:
        if n == 'all': out.update(DEVICES)
        elif n in DEVICES: out.add(n)
        elif n not in ('', 'none'):
            raise ValueError('compiled device %r: the names are %s, all, none' % (n, ', '.join(DEVICES)))
    return frozenset(out)


# ---- views: the Python objects of devices whose state lives in the core --------------------------------------------------
def _word(field, conv=int):
    """Property: one word of the state of the compiled device `self._k`."""
    def get(self):
        return conv(self._core.dev_get(self._k, field))
    def put(self, value):
        self._core.dev_set(self._k, field, int(value))
    return property(get, put)


class _Words:
    """A row of state words as a list (the vector tables of an interrupt controller)."""
    def __init__(self, core, kind, first, n):
        self._a = (core, kind, first, n)

    def __len__(self):
        return self._a[3]

    def __getitem__(self, i):
        core, kind, first, n = self._a
        if isinstance(i, slice):
            return [self[j] for j in range(*i.indices(n))]
        if not -n <= i < n:
            raise IndexError(i)
        return core.dev_get(kind, first + i % n)

    def __setitem__(self, i, value):
        core, kind, first, n = self._a
        if not -n <= i < n:
            raise IndexError(i)
        core.dev_set(kind, first + i % n, value)

    def __iter__(self):
        return (self[i] for i in range(self._a[3]))

    def __eq__(self, other):
        return list(self) == list(other)

    def __repr__(self):
        return repr(list(self))


class _TimerRegs:
    """SleepTimer.regs: what was written, by offset. Offsets never written read as absent."""
    def __init__(self, core):
        self._core = core

    def get(self, off, default=0):
        return self._core.dev_get(dbcore.K_TIMER, dbcore.T_REG + off) if 0 <= off < 0x1000 else default

    def __getitem__(self, off):
        return self.get(off)

    def __setitem__(self, off, value):
        self._core.dev_set(dbcore.K_TIMER, dbcore.T_REG + off, value & M32)

    def items(self):
        return [(o, v) for o in range(0x1000) for v in (self.get(o),) if v]

    def __repr__(self):
        return repr(dict(self.items()))


class ClockView:
    """Mix-in over emu_irq.clock.Clock. The clock is the core's (insns charged, ns skipped, ns per instruction); this object
    holds an equal copy for reading and sends every change to the core at once. refresh() reads the core's values.
    The time (now_ns) is worked out when one of the three changes and kept: the models read it some hundred thousand times
    per emulated second."""
    def _bind(self, core):
        d = self.__dict__
        self._core = core
        self._v = [d.pop('insns'), d.pop('skipped_ns')]
        self._rate = d.pop('ns_per_insn')
        self._now = int(self._v[0] * self._rate) + self._v[1]
        core.clock_rate(self._rate); core.clock_set(*self._v)

    def refresh(self):
        g = self._core.clock_get
        self._v[:] = [g(dbcore.C_INSNS), g(dbcore.C_SKIPPED_NS)]
        self._rate = struct.unpack('<d', struct.pack('<Q', g(dbcore.C_RATE_BITS)))[0]
        self._now = int(self._v[0] * self._rate) + self._v[1]

    @property
    def now_ns(self):
        return self._now

    def charged(self, n):
        """The core has set the instruction count to n itself (Core.run_slices): take it over, nothing to send."""
        v = self._v
        v[0] = n; self._now = int(n * self._rate) + v[1]

    @property
    def insns(self):
        return self._v[0]

    @insns.setter
    def insns(self, n):
        v = self._v
        if n != v[0]:
            v[0] = n; self._now = int(n * self._rate) + v[1]; self._core.clock_set(n, v[1])

    @property
    def skipped_ns(self):
        return self._v[1]

    @skipped_ns.setter
    def skipped_ns(self, n):
        v = self._v
        if n != v[1]:
            v[1] = n; self._now = int(v[0] * self._rate) + n; self._core.clock_set(v[0], n)

    @property
    def ns_per_insn(self):
        return self._rate

    @ns_per_insn.setter
    def ns_per_insn(self, x):
        self._rate = x; self._now = int(self._v[0] * x) + self._v[1]; self._core.clock_rate(x)


class TimerView:
    """Mix-in over emu_irq.timer.SleepTimer: the timer is the core's. advance() fires what is due at the clock's time, as
    the Python model's does; the lines go to the interrupt controllers in the core, or come back to the Python pair
    through the machine. The log of armings is not kept (the count is: `arms`)."""
    _k = dbcore.K_TIMER
    keep_log = False

    def _bind(self, core):
        d = self.__dict__
        for off, value in d.pop('regs').items():
            core.dev_set(dbcore.K_TIMER, dbcore.T_REG + off, value)
        dl = d.pop('deadline0')
        for name, field in (('status', dbcore.T_STATUS), ('extra', dbcore.T_EXTRA), ('written', dbcore.T_WRITTEN), ('held_reads', dbcore.T_HELD_READS),
                            ('fired', dbcore.T_FIRED), ('line0', dbcore.T_LINE0), ('line1', dbcore.T_LINE1), ('read_step', dbcore.T_READ_STEP)):
            core.dev_set(dbcore.K_TIMER, field, int(d.pop(name)))
        core.dev_set(dbcore.K_TIMER, dbcore.T_DEADLINE0, dbcore.NO_EVENT if dl is None else dl)
        d.pop('arm_log', None); d.pop('keep_log', None)
        self._core = core
        self._adv = (core.dev_advance, core.dev_next_event)

    status = _word(dbcore.T_STATUS)
    extra = _word(dbcore.T_EXTRA)
    written = _word(dbcore.T_WRITTEN, bool)
    held_reads = _word(dbcore.T_HELD_READS)
    fired = _word(dbcore.T_FIRED)
    arms = _word(dbcore.T_ARMS)
    line0 = _word(dbcore.T_LINE0)
    line1 = _word(dbcore.T_LINE1)
    read_step = _word(dbcore.T_READ_STEP)

    @property
    def deadline0(self):
        t = self._core.dev_get(dbcore.K_TIMER, dbcore.T_DEADLINE0)
        return None if t == dbcore.NO_EVENT else t

    @deadline0.setter
    def deadline0(self, t):
        self._core.dev_set(dbcore.K_TIMER, dbcore.T_DEADLINE0, dbcore.NO_EVENT if t is None else t)

    @property
    def regs(self):
        return _TimerRegs(self._core)

    @property
    def arm_log(self):
        return []

    def advance(self):
        self._adv[0](dbcore.K_TIMER)

    def next_event_ns(self):
        return self._adv[1](dbcore.K_TIMER)

    def read(self, off, size):
        return self._core.dev_read(dbcore.K_TIMER, off, size)

    def write(self, off, size, value):
        self._core.dev_write(dbcore.K_TIMER, off, size, value)


class VicView:
    """Mix-in over emu_irq.vic.Vic: one controller of the pair in the core."""
    def _bind(self, core, kind):
        d = self.__dict__
        self._core, self._k = core, kind
        for name, field in (('lines', dbcore.V_LINES), ('soft', dbcore.V_SOFT), ('enable', dbcore.V_ENABLE), ('select', dbcore.V_SELECT),
                            ('protection', dbcore.V_PROTECTION), ('defvect', dbcore.V_DEFVECT), ('reads_vect', dbcore.V_READS_VECT),
                            ('writes_vect', dbcore.V_WRITES_VECT)):
            core.dev_set(kind, field, d.pop(name))
        for name, first in (('vectaddr', dbcore.V_VECTADDR), ('vectcntl', dbcore.V_VECTCNTL)):
            for i, x in enumerate(d.pop(name)):
                core.dev_set(kind, first + i, x)
        self.cur_prio = d.pop('cur_prio')

    lines = _word(dbcore.V_LINES)
    soft = _word(dbcore.V_SOFT)
    enable = _word(dbcore.V_ENABLE)
    select = _word(dbcore.V_SELECT)
    protection = _word(dbcore.V_PROTECTION)
    defvect = _word(dbcore.V_DEFVECT)
    reads_vect = _word(dbcore.V_READS_VECT)
    writes_vect = _word(dbcore.V_WRITES_VECT)

    @property
    def vectaddr(self):
        return _Words(self._core, self._k, dbcore.V_VECTADDR, 16)

    @property
    def vectcntl(self):
        return _Words(self._core, self._k, dbcore.V_VECTCNTL, 16)

    @property
    def cur_prio(self):
        """The slots in service, innermost last (a copy)."""
        g = self._core.dev_get
        return [g(self._k, dbcore.V_PRIO + i) for i in range(g(self._k, dbcore.V_DEPTH))]

    @cur_prio.setter
    def cur_prio(self, slots):
        slots = list(slots)[-16:]
        for i, x in enumerate(slots):
            self._core.dev_set(self._k, dbcore.V_PRIO + i, x)
        self._core.dev_set(self._k, dbcore.V_DEPTH, len(slots))

    def read(self, off, size):
        return self._core.dev_read(self._k, off, size)

    def write(self, off, size, value):
        self._core.dev_write(self._k, off, size, value)


class VicPairView:
    """Mix-in over emu_irq.vic.VicPair: the pair is the core's and drives the interrupt input of the CPU there. The
    callbacks on_irq / on_fiq are not called any more."""
    def _bind(self, core):
        d = self.__dict__
        self._core = core
        self._sl = (core.set_line, core.irq_out)
        core.dev_set(dbcore.K_VIC0, dbcore.V_EDGES, d.pop('irq_edges'))
        d.pop('irq_out'); d.pop('fiq_out')
        core.dev_set(dbcore.K_VIC0, dbcore.V_ON, 1)

    _k = dbcore.K_VIC0
    irq_edges = _word(dbcore.V_EDGES)

    @property
    def irq_out(self):
        return bool(self._sl[1]() & 1)

    @property
    def fiq_out(self):
        return bool(self._sl[1]() & 2)

    def set_line(self, n, level):
        self._sl[0](n, level)

    def get_line(self, n):
        return self._core.line(n)

    def update(self):
        pass                                # the core recomputes the outputs at every change


class _Regs:
    """The registers of a block in the core as the dict its model keeps: {offset: value}, one per `step` bytes. A register
    that holds zero reads as absent."""
    def __init__(self, core, kind, step):
        self._a = (core, kind, step)

    def _at(self, off):
        core, kind, step = self._a
        if type(off) is not int or not 0 <= off < PAGE or off % step:
            raise KeyError(off)
        return core, kind, dbcore.S_REG + off

    def get(self, off, default=None):
        try:
            core, kind, field = self._at(off)
        except KeyError:
            return default
        return core.dev_get(kind, field) or default

    def __getitem__(self, off):
        core, kind, field = self._at(off)
        return core.dev_get(kind, field)

    def __setitem__(self, off, value):
        core, kind, field = self._at(off)
        core.dev_set(kind, field, value & M32)

    def __contains__(self, off):
        return self.get(off) is not None

    def items(self):
        core, kind, step = self._a
        return [(o, v) for o in range(0, PAGE, step) for v in (core.dev_get(kind, dbcore.S_REG + o),) if v]

    def keys(self):
        return [o for o, _ in self.items()]

    def __iter__(self):
        return iter(self.keys())

    def __len__(self):
        return len(self.items())

    def __eq__(self, other):
        return dict(self.items()) == {o: v for o, v in dict(other).items() if v}

    def __repr__(self):
        return repr(dict(self.items()))


class _RegsView:
    """The registers are the core's. read() and write() are the model's: they take no notice of the access size (the bus
    cuts a value to it). A write that arrives here was declined by the core, or comes from outside the CPU."""
    _step = 1

    def _bind(self, core, kind, attr):
        regs = self.__dict__.pop(attr)
        self._core, self._k = core, kind
        self._regs = _Regs(core, kind, self._step)
        self._set = (core.dev_set, dbcore.S_REG)
        for off, value in regs.items():
            self._regs[off] = value

    def read(self, off, size):
        return self._core.dev_read(self._k, off, 4)

    def write(self, off, size, value):
        f, reg = self._set
        f(self._k, reg + off, value & M32)


class SysCtlView(_RegsView):
    """Mix-in over the launcher's AppSysCtrl (system control, 0xC0011000): the block is the core's. `regs` is a live view
    of its registers, by byte offset."""
    regs = property(operator.attrgetter('_regs'))


class ClkProfView(_RegsView):
    """Mix-in over the launcher's ClockProfile (0xA0004000): the block is the core's. `r` is a live view of its
    registers, by the offset of the word."""
    _step = 4
    r = property(operator.attrgetter('_regs'))


_PROBE_OFFS = (0x000, 0x001, 0x004, 0x005, 0x006, 0x008, 0x020, 0x021, 0x024, 0x028, 0x029, 0x400, 0x4CC, 0x4CF, 0x4D0, 0x4D1, 0x4D3, 0x4D4, 0xFFC, 0xFFF)


def _answers_alike(dev, attr, kind, fresh, steps=1500):
    """None when the compiled register block `kind` answers a fixed sequence of reads and writes as a copy of the model
    object `dev` does (on a core of its own, which fresh() makes, so nothing is left behind); else a text naming the first
    access that differed. `attr` names the model's dict of registers."""
    twin = copy.copy(dev)
    setattr(twin, attr, dict(getattr(dev, attr)))
    rnd = random.Random(kind)
    core = fresh()
    try:
        for off, value in getattr(twin, attr).items():
            core.dev_set(kind, dbcore.S_REG + off, value)
        for n in range(1, steps + 1):
            off = rnd.choice(_PROBE_OFFS) if rnd.random() < 0.8 else rnd.randrange(PAGE)
            size = rnd.choice((1, 2, 4, 4))
            if rnd.random() < 0.5:
                value = rnd.choice((0, 4, 2, 6, 1, 0x14, M32, rnd.getrandbits(32))) & ((1 << 8 * size) - 1)
                twin.write(off, size, value)
                if not core.dev_write(kind, off, size, value):
                    return 'access %d, a write of %d bytes at +%#05x of %#x: the compiled block declines it' % (n, size, off, value)
            else:
                want, got = twin.read(off, size) & ((1 << 8 * size) - 1), core.dev_read(kind, off, size)
                if want != got:
                    return 'access %d, a read of %d bytes at +%#05x: the model gives %#x, the compiled block %#x' % (n, size, off, want, got)
        return None
    finally:
        core.close()


class _Bus(Bus):
    """The device bus (emu.bus.Bus), which also says when its `write` is replaced: on_write_swap(foreign) is called with
    True when the new one is not a method of the bus itself (a wrapper that wants to see the writes), with False when
    it is one again."""
    on_write_swap = None

    def __init__(self, log=None):
        super().__init__(log)
        self._write = Bus.write.__get__(self, type(self))

    def _set_write(self, f):
        self._write = f
        if self.on_write_swap is not None:
            self.on_write_swap(self.write_is_foreign())

    write = property(operator.attrgetter('_write'), _set_write)

    def write_is_foreign(self):
        return getattr(self._write, '__self__', None) is not self

    def set_accounting(self, on):
        super().set_accounting(on)
        if on:
            self.write = Bus.write.__get__(self, type(self))


class _PortLib:
    """Stands for the library of emu/native_port.py: the names of its entry points, which add_native_window maps to window
    kinds of the core."""
    port_mmio, port_wmmio, reg_ctrl_r, reg_ctrl_w, reg_ale_w = 'port_mmio', 'port_wmmio', 'reg_ctrl_r', 'reg_ctrl_w', 'reg_ale_w'


_PORT_KINDS = {('port_mmio', 'port_wmmio'): dbcore.K_NAND_DATA, ('reg_ctrl_r', 'reg_ctrl_w'): dbcore.K_NAND_CTRL, (None, 'reg_ale_w'): dbcore.K_NAND_ALE}


class CorePort:
    """What emu.native_port.StreamPort is to the NAND model, on the data port inside the core: grant() leases the rest of
    the page register to reads or to writes, take() ends the lease and says how many bytes went through. `c` holds the
    words the model shares with the compiled register file (busy count, queued address cycles, timing registers)."""
    lib = _PortLib

    def __init__(self, core, base, size):
        self.core, self.base, self.size = core, base, size
        self.c = core.nand_regs()
        self.ptr = None
        self._buf = None; self._pos0 = 0; self._n = 0; self._write = False
        self._keep = []

    def grant(self, buf, pos, limit, write=False):
        """Lease bytes buf[pos:limit] (a bytearray, which must not be touched until take()) to reads, or to writes."""
        self._buf, self._pos0, self._n, self._write = buf, pos, limit - pos, write
        try:
            if write:
                self.core.port_grant(limit - pos, True)
            else:
                self.core.port_grant(bytes(memoryview(buf)[pos:limit]))
        except ValueError:
            pass                            # a span the port does not take: no lease, the model serves

    def take(self):
        """End the lease. Returns the number of bytes handed out, or taken in, since grant(); the bytes taken in are in the
        buffer then."""
        if self._write:
            n, got = self.core.port_take(self._n)
            if n:
                self._buf[self._pos0:self._pos0 + n] = got[:n]
        else:
            n = self.core.port_take()[0]
        self._buf = None; self._write = False
        return n

    @property
    def served(self):
        return self.c.served

    def covers(self, addr):
        return self.base <= addr < self.base + self.size

    def set_page(self, addr, host_ptr):
        pass                                # the shadow pages are the core's


class _NandTrap:
    """Mix-in over the NAND model's chip and system objects. While the state is in the core the attributes that hold it are
    absent from the object, so that a look at one of them comes here: a plain value is read from the core, anything else
    (and every assignment) first brings the state back."""
    def __getattr__(self, name):
        link = self.__dict__.get('_link')
        if link is not None and link.in_core and name in link.TRAPPED:
            if name in link.WORDS:
                return link.words()[name]
            link.pull()
            return getattr(self, name)
        raise AttributeError('%r object has no attribute %r' % (type(self).__name__, name))

    def __setattr__(self, name, value):
        link = self.__dict__.get('_link')
        if link is not None and link.in_core and not link.in_store and name in link.TRAPPED:
            link.pull()
        object.__setattr__(self, name, value)


class _NandSystemView(_NandTrap):
    """Mix-in over nand_model.NandSystem (see NandInCore)."""
    def _base_log(self):
        return next(c.__dict__['access_log'] for c in type(self).__mro__ if c is not _NandSystemView and 'access_log' in c.__dict__)

    @property
    def access_log(self):
        return self._base_log().fget(self)

    @access_log.setter
    def access_log(self, v):
        link = self.__dict__.get('_link')
        if link is not None:
            link.pull()                     # a trace sees every access: the model serves while it is set
        self._base_log().fset(self, v)


class _NandWindowView:
    """Mix-in over nand_model.NandBus and NandCtrl: an access that arrives here was declined by the core (or the state is
    with the model). The model takes the state back, serves, and gives it to the core again if the core can hold it."""
    def read(self, offset, size):
        link = self._link
        if link.in_core:
            link.decline(self, offset, None)
        v = super().read(offset, size)
        link.push()
        return v

    def write(self, offset, size, value):
        link = self._link
        if link.in_core:
            link.decline(self, offset, value)
        super().write(offset, size, value)
        link.push()


class NandInCore:
    """The NAND model (emu_nand/nand_model.py: NandSystem `nand`, module `nm`) with its command state machine in the core.

    The state of the chip and of the controller (mode, command, address cycles, page register and position, status, the
    open program, ECC engine, control register) is in one place at a time. push() puts it into the core (the structure of Core.nand_cmd())
    and switches the core's machine on: every access to the four windows is then served there, and the model's objects
    lose those attributes. pull() brings it back and switches the machine off. An access the core declines arrives at the
    model's window objects, which pull, serve as ever, and push again; push() leaves the state with the model when the
    core cannot hold it (an ID or unique-ID read under way, more than eight address cycles, a row outside the chip, the
    test hook fail_next, a trace in access_log, a chip with the ST unique-ID command), and the model then serves as it
    does without this class, lease of the data port included.

    The contents of the chip stay with the model. The core calls store() once for a page read (chip.page_bytes), a
    program (chip._do_program) and an erase (chip._do_erase), so whatever wraps those methods sees every call, with
    chip.buf and chip.status as the model would have them.

    The model's logs (chip.cmd_log, nand.ecc_log) are kept when keep_logs is set: the core logs up to
    dbcore.NAND_LOG_CAP entries, declines what would add to a full log, and pull() moves the entries into the lists.
    With keep_logs False nothing is logged and the lists stay as they are; the counts of the core (counts()) go on.
    Machine passes False unless asked (see its keep_nand_logs): only tests read the lists, and in a minute of emulated
    time they grow by tens of MB."""
    CHIP = frozenset(('mode', 'cmd', '_addr', 'buf', 'pos', 'prog_page', 'status', 'cb_page', 'buf_valid', 'last_row', 'st_seq', 'fail_next', 'cmd_log'))
    SYSTEM = frozenset(('ecc', 'ctrl_val', 'ecc_log'))
    TRAPPED = CHIP | SYSTEM
    WORDS = frozenset(('mode', 'cmd', 'pos', 'prog_page', 'status', 'cb_page', 'buf_valid', 'last_row', 'fail_next', 'ctrl_val'))
    _CODE = {m: i for i, m in enumerate(dbcore.NAND_MODES) if m}
    _LOG = {dbcore.L_READ: 'read', dbcore.L_CBREAD: 'cbread', dbcore.L_PROGRAM: 'program', dbcore.L_ERASE: 'erase',
            dbcore.L_UNKNOWN: 'unknown cmd', dbcore.L_RESET: 'reset'}

    def __init__(self, core, nand, nm, keep_logs=True):
        self.nand, self.chip, self.nm = nand, nand.chip, nm
        self.in_core = self.in_store = False
        self.keep_logs = keep_logs
        self.pulls = 0
        self.declined = collections.Counter()       # what the core declined while it had the state
        self._ecc = self._cmd_log = self._ecc_log = None
        self.bind(core)
        for obj, mixin in ((nand.chip, _NandTrap), (nand, _NandSystemView), (nand.bus, _NandWindowView), (nand.ctrl, _NandWindowView)):
            base = type(obj)
            obj.__class__ = type(base.__name__ + 'InCore', (mixin, base), {'__doc__': mixin.__doc__})
            obj.__dict__['_link'] = self

    def bind(self, core):
        """Use this core (at the start, and after a state was loaded into a fresh one)."""
        self.core = core
        self.k = k = core.nand_cmd()
        self._set_buf = core.nand_set_buf
        nm = self.nm
        k.off_ctrl, k.off_status, k.off_ecc = nm.R_CTRL, nm.R_STATUS, nm.R_ECC

    # ---- the state, one way and the other
    def push(self):
        """Give the state to the core. False (nothing changed) when the core cannot hold it or may not serve."""
        if self.in_core:
            return True
        nand, chip, k = self.nand, self.chip, self.k
        c = nand._c
        if c is None or not c.reg_on or nand.port is None or chip.st_uid or chip.fail_next or chip.st_seq:
            return False
        if nand._leased:
            nand.sync()
        mode = self._CODE.get(chip.mode)
        cmd, addr, e = chip.cmd, chip.addr, nand.ecc
        pages = chip.pages
        opt = (chip.prog_page, chip.cb_page, chip.last_row)
        if (mode is None or not (cmd is None or 0 <= cmd <= 0xFF) or len(addr) > 8 or not 0 <= chip.pos < dbcore.NAND_POS_MAX
                or not 0 <= chip.status <= 0xFF or len(chip.buf) != dbcore.NAND_RAW or not 0 <= nand.ctrl_val <= M32
                or not 0 < pages < dbcore.NAND_NONE or len(chip.ids) > 8
                or not (opt[0] is None or 0 <= opt[0] < pages) or any(not (x is None or 0 <= x < dbcore.NAND_NONE) for x in opt[1:])):
            return False
        idx, rp, cp = e.idx, e.rp, e.cp            # (this folds in what the engine was fed)
        k.mode, k.cmd, k.naddr = mode, dbcore.NAND_NO_CMD if cmd is None else cmd, len(addr)
        self.core.nand_set_array('addr', addr)
        k.pos, k.status, k.buf_valid, k.ctrl_val = chip.pos, chip.status, bool(chip.buf_valid), nand.ctrl_val
        k.prog_page, k.cb_page, k.last_row = (dbcore.NAND_NONE if x is None else x for x in opt)
        k.pages, k.nids = pages, len(chip.ids)
        self.core.nand_set_array('ids', chip.ids)
        k.ecc_idx = idx
        k.ecc_even = sum(rp[2 * i] << i for i in range(9)); k.ecc_odd = sum(rp[2 * i + 1] << i for i in range(9))
        k.ecc_col = sum(b << i for i, b in enumerate(cp))
        self._set_buf(bytes(chip.buf))
        k.log_on = bool(self.keep_logs)
        d, sd = chip.__dict__, nand.__dict__
        self._cmd_log, self._ecc, self._ecc_log = d['cmd_log'], sd['ecc'], sd['ecc_log']
        for n in self.CHIP: d.pop(n, None)
        for n in self.SYSTEM: sd.pop(n, None)
        self.in_core = True
        k.on = 1
        return True

    def words(self):
        """The plain values of the state in the core, by the model's attribute names."""
        k = self.k
        none = lambda x: None if x == dbcore.NAND_NONE else x
        return dict(mode=dbcore.NAND_MODES[k.mode], cmd=None if k.cmd == dbcore.NAND_NO_CMD else k.cmd, pos=k.pos, prog_page=none(k.prog_page),
                    status=k.status, cb_page=none(k.cb_page), buf_valid=bool(k.buf_valid), last_row=none(k.last_row), fail_next=False,
                    ctrl_val=k.ctrl_val)

    def pull(self):
        """Take the state back from the core (nothing to do when the model has it)."""
        if not self.in_core:
            return
        if self.in_store:
            raise RuntimeError('the NAND model was changed from inside a program or erase call of the core')
        k = self.k
        k.on = 0; self.in_core = False; self.pulls += 1
        w = self.words()
        d, sd = self.chip.__dict__, self.nand.__dict__
        sd['ctrl_val'] = w.pop('ctrl_val')
        d.update(w)
        d['buf'] = bytearray(self.core.nand_buf()); d['_addr'] = list(self.core.nand_array('addr')[:k.naddr]); d['st_seq'] = []; d['cmd_log'] = self._cmd_log
        e = self._ecc
        e._idx = k.ecc_idx; e._pend = bytearray()
        e._rp = [(k.ecc_odd if i & 1 else k.ecc_even) >> (i >> 1) & 1 for i in range(18)]
        e._cp = [k.ecc_col >> i & 1 for i in range(6)]
        sd['ecc'] = e; sd['ecc_log'] = self._ecc_log
        self.drain()
        self.chip._ale_state()

    def drain(self):
        """Move the core's log entries into the model's lists."""
        k = self.k; n = k.nlog
        if not n:
            return
        raw = self.core.nand_log(n); k.nlog = 0
        cmd_log, ecc_log, names = self._cmd_log, self._ecc_log, self._LOG
        for w0, w1 in struct.iter_unpack('<QQ', raw):
            kind, value, row = w0 & 0xFF, w0 >> 8 & 0xFFFFFF, w0 >> 32
            if kind == dbcore.L_ECC: ecc_log.append((None if row == dbcore.NAND_NONE else row, w1, value))
            elif kind == dbcore.L_READ: cmd_log.append(('read', row, w1))
            elif kind == dbcore.L_UNKNOWN: cmd_log.append(('unknown cmd', value))
            elif kind == dbcore.L_RESET: cmd_log.append(('reset',))
            else: cmd_log.append((names[kind], row))

    def decline(self, window, offset, value):
        """An access that the core declined arrives at the model: count it by what it is, and take the state back."""
        nm = self.nm
        if window is self.nand.ctrl: what = 'controller +%#x %s' % (offset, 'read' if value is None else 'write')
        elif offset >= nm.OFF_ALE: what = 'address latch read' if value is None else 'address cycle'
        elif offset >= nm.OFF_CLE: what = 'command latch read' if value is None else 'command %#04x' % (value & 0xFF)
        else: what = 'data read' if value is None else 'data write'
        self.declined[what] += 1
        self.pull()

    # ---- the store
    def store(self, dev, page):
        """A store call of the core (the read callback with device number STORE_*)."""
        chip, k = self.chip, self.k
        if dev == dbcore.STORE_READ:
            data = bytes(chip.page_bytes(page))
            if len(data) != dbcore.NAND_RAW:
                raise ValueError('NAND page %d has %d bytes' % (page, len(data)))
            self._set_buf(data)
            return 0
        d = chip.__dict__
        d['buf'] = bytearray(self.core.nand_buf()); d['status'] = k.status; d['fail_next'] = False; d['cmd_log'] = []
        self.in_store = True
        try:
            (chip._do_program if dev == dbcore.STORE_PROGRAM else chip._do_erase)(page)
        finally:
            self.in_store = False
            status = d.pop('status')
            for n in ('buf', 'fail_next', 'cmd_log'): d.pop(n, None)
        return status & 1

    # ---- reports
    def counts(self):
        """{name: number} of what the core's machine served."""
        g = self.core.dev_get
        return {n: g(dbcore.K_NAND_CLE, dbcore.N_COUNT + i) for i, n in ((dbcore.L_READ, 'page reads'), (dbcore.L_CBREAD, 'copy-back reads'),
                (dbcore.L_PROGRAM, 'programs'), (dbcore.L_ERASE, 'erases'), (dbcore.L_RESET, 'resets'), (dbcore.L_UNKNOWN, 'unknown commands'), (dbcore.L_ECC, 'ECC reads'))}

    def summary(self):
        return ('NAND command machine in the core: %s; declined to the model: %s; state taken back %d times'
                % (', '.join('%s %s' % (format(v, ','), n) for n, v in self.counts().items()),
                   ', '.join('%s x%d' % kv for kv in sorted(self.declined.items(), key=lambda kv: -kv[1])) or 'nothing', self.pulls))


def for_launcher(a, out=None, make_core=None):
    """The Machine class for sim/db3210.py --core own, after a look at the launcher's parsed options `a`. Raises ValueError
    with one line for an option this machine cannot serve and OSError when the library is not built; an option that has
    no meaning here is named through out(line) and ignored. make_core: a function that makes the core of each machine
    (see Machine, `core`); the library of dbcore.py is not looked for then."""
    if a.mode != 'full':
        raise ValueError('needs --mode full (--mode %s builds its application CPU on Unicorn)' % a.mode)
    if a.slice_replay:
        raise ValueError('--slice-replay is not supported (a slice log of the Unicorn machine does not fit this core)')
    build = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'build.sh')
    try:
        if make_core is None and Machine.make_core is None:
            dbcore.library()
    except AttributeError as e:
        raise OSError('the library %s is older than this tree (%s): run %s' % (dbcore.find_library(), e, build))
    except OSError as e:
        raise OSError('the library of the compiled core is not built: run %s (%s)' % (build, e))
    ignored = [n for n, on in (('--block-slices', a.block_slices), ('--slice-log', a.slice_log)) if on]
    if ignored and out:
        out('[sim] --core own: %s ignored (this core counts every instruction and ends a slice exactly)' % ', '.join(ignored))
    made = []

    def at_end():
        for m in made:
            report(m, *([out] if out else []))

    class Launched(Machine):
        def __init__(self, *args, **kw):
            if make_core is not None and kw.get('core') is None:
                kw['core'] = make_core()
            super().__init__(*args, **kw)
            if not made:                # the summary lines when the launcher ends, however it ends
                atexit.register(at_end)
            made.append(self)

    return Launched


def report(m, out=lambda s: print(s, flush=True)):
    """The summary lines of a run: instructions, exceptions taken, device accesses through Python and in the core."""
    out('[own] core: %s instructions%s, %d entry-hook stops; exceptions taken: %s'
        % (format(m.core.icount(), ','), ' (time charged by slices, as the Unicorn machine)' if m.charge_slices else '', m.hook_hits, ', '.join('%s %d' % kv for kv in m.event_counts().items()) or 'none'))
    out('[own] device accesses through Python: %s reads, %s writes' % (format(m.bus.nread, ','), format(m.bus.nwrite, ',')))
    out('[own] compiled devices: %s; accesses served in the core (reads / writes): %s'
        % (', '.join(sorted(set(m.compiled))) or 'none', '; '.join('%s %s / %s' % (n, format(r, ','), format(w, ',')) for n, (r, w) in m.compiled_counts().items()) or 'none'))
    if m._nand is not None:
        out('[own] ' + m._nand.summary())
    for pc, n, word, cp15 in m.undefined_summary():
        out('[own] undefined instruction at pc %#010x x%d: word %s%s'
            % (pc, n, 'not readable now' if word is None else '%#010x' % word, ' = MCR / MRC p15 (user mode)' if cp15 else ''))


INF = float('inf')


class MemError(Exception):
    """A virtual address that the page table does not map (read_virt), or a span of uc.mem_read / mem_write outside the
    memory and windows mapped on purpose."""


class UcShim:
    """The Unicorn calls that device models and attach modules make on `machine.uc`, on the core."""

    def __init__(self, machine):
        self._m = machine
        self._core = machine.core

    # ---- registers
    def reg_read(self, reg, opt=None):
        if reg == UC_CP_REG:
            return self._m._cp(opt[3], opt[4], opt[5], opt[6])
        return self._core.reg(REG[reg])

    def reg_write(self, reg, value):
        c = self._core
        if reg == UC_CP_REG:
            self._m.cp_write(value[3], value[4], value[5], value[6], value[7]); return
        if reg == UC_PC:                         # as Unicorn: bit 0 selects Thumb state; the write wakes a halted CPU
            cpsr = c.reg(dbcore.CPSR)
            if bool(cpsr & 0x20) != bool(value & 1):
                c.set_reg(dbcore.CPSR, cpsr ^ 0x20)
            c.set_reg(dbcore.PC, value & ~1)
            return
        c.set_reg(REG[reg], value)

    # ---- memory
    def _mapped(self, address, size):
        m = self._m
        if not any(b <= address and address + size <= b + s for b, s in m._ram) and not any(b <= address and address + size <= b + s for b, s in m.hw_regions):
            raise MemError('uc.mem: %#x..%#x is not inside mapped memory' % (address, address + size))

    def mem_read(self, address, size):
        self._mapped(address, size)
        return bytearray(self._core.mem_read(address, size))

    def mem_write(self, address, data):
        self._mapped(address, len(data))
        self._core.mem_write(address, bytes(data))

    def mem_map(self, address, size, perms=7):
        self._m._map_ram(address, size)

    def mem_map_ptr(self, address, size, perms, ptr):
        """RAM that the caller also wants to see in its own buffer. The core keeps the bytes; the buffer is brought up to date
        before an entry-hook callback on a boot-ROM stand-in (where the launcher looks at it) and by Machine.sync_host().
        `ptr`: the address of the buffer, as for Unicorn, or the buffer itself (bytearray, mmap, memoryview), which is
        the only form a core without HOST_POINTERS takes."""
        if isinstance(ptr, int) and not self._core.HOST_POINTERS:
            raise TypeError('uc.mem_map_ptr: this core takes no host address; pass the buffer itself')
        self._m._map_ram(address, size)
        self._m._host.append((address, size, ptr))

    def mem_unmap(self, address, size):
        self._m._ram = [r for r in self._m._ram if not (r[0] >= address and r[0] + r[1] <= address + size)]

    def mem_regions(self):
        for b, s in sorted(self._m._ram):
            yield b, b + s - 1, 7

    # ---- control
    def emu_stop(self):
        self._core.request_stop()

    def hook_del(self, handle):
        self._m._del_hook(handle)

    def ctl_remove_cache(self, begin, end):
        pass

    def hook_add(self, *a, **k):
        raise NotImplementedError('uc.hook_add: use Machine.add_entry_hook (the core has entry hooks only)')

    def emu_start(self, *a, **k):
        raise NotImplementedError('uc.emu_start: use Machine.run')


class Machine:
    make_core = None                        # when set: a function that makes the core of a machine that is given none

    def __init__(self, uart_log=None, echo=True, log=None, mmio=False, block_slices=False, lib=None, charge_slices=None, devices=None, keep_nand_logs=None,
                 core=None):
        self.log = log or (lambda s: print(s, file=sys.stderr))
        self.mmio = mmio                    # accepted and ignored: the windows are external windows of the core either way
        self.block = None                   # no block slices: the core counts every instruction and stops exactly
        # core: an empty core made by the caller, any object with the methods of dbcore.Core; else what Machine.make_core
        # makes (a harness sets it, so that machines built by code it does not own get its kind of core); else one of
        # the library `lib`
        if core is None:
            core = type(self).make_core() if type(self).make_core is not None else dbcore.Core(lib)
        self.core = core
        self.devices = device_set(devices)  # compiled devices to use (see the module text)
        self.compiled = []                  # names of the devices taken over so far
        self._vic = None                    # the pair of interrupt controllers, when it is the core's
        self._line_out = None               # set_line(n, level) of the Python pair, for lines that compiled devices drive
        self._nand_model = None             # (NandSystem, base of its bus window), noted when it is attached
        # keep_nand_logs: the NAND model's lists of commands and ECC reads (chip.cmd_log, nand.ecc_log). Nothing but tests
        # reads them, and they grow with the run, so the core's machine does not feed them unless asked: True here, or the
        # environment variable DBCORE_NAND_LOGS=1. (The model serves as ever when the core declines; it appends there.)
        self.keep_nand_logs = os.environ.get('DBCORE_NAND_LOGS', '0') != '0' if keep_nand_logs is None else keep_nand_logs
        self._nand = None                   # NandInCore, when the command machine of the NAND model is the core's
        self._sysctl = None                 # the system control block, when it is the core's
        self.uc = UcShim(self)
        self.slice_log = None
        self.slice_plan = None
        self._ram = []                      # (base, size) of the RAM mapped on purpose
        self._host = []                     # (base, size, host pointer): see UcShim.mem_map_ptr
        self._map_ram(SDRAM_BASE, SDRAM_SIZE)
        self._map_ram(0, TCM_SIZE)
        self.demand = collections.OrderedDict()
        self.hw_pages = set()
        self.bus = _Bus(self.log)
        self.bus.on_write_swap = self._bus_write_swapped
        self.uart = self.bus.attach(UART_BASE, 0x1000, Uart(uart_log, echo))
        self.cp15 = collections.OrderedDict()
        self.irq_vector = 0x18
        self.irq_prompt = 0
        self.insns = 0
        self.stop_reason = None
        self.call_trace = None
        self.aborts = 0
        self.idle_cb = None
        self.spin_skip = False              # accepted and ignored
        self.spin_skipped = 0
        self.spin_wfi_guess = 0
        self.stop_on_wfi = True
        self.hook_hits = 0
        # Set at every device access that arrives at a model, at every entry hook, and by whoever acts on a model from
        # outside a run; cleared by the scheduler's step (emu_irq.IrqTimerSystem.step), which lets the models' ticks rest
        # after a slice in which nothing reached them and none of them is due.
        self.touched = True
        # Several slices in one call of the core (Core.run_slices) while nothing needs Python between them: at most this
        # many (DBCORE_QUANTA; 1 = one dbc_run per slice, as a recording needs it). run() says in `quanta` how many
        # quanta of its caller it went through, and in `quantum_end` where the last one was to end.
        self.max_quanta = max(1, int(os.environ.get('DBCORE_QUANTA') or 32))
        self.quanta = 1
        self.quantum_end = 0
        self._clock = None                  # the clock, when it is the core's (with the timer)
        self._multi = False                 # inside Core.run_slices, and no device was reached yet (see _multi_sync)
        self._hooks = {}                    # address -> list of (handle, callback)
        self._next_handle = 1
        self._error = None                  # exception raised in a device model during a run
        self._last_pc = None
        self._ev_kinds = collections.Counter()      # exceptions taken, by kind, that have left the core's log
        self._ev_undef = collections.Counter()      # pc -> undefined-instruction exceptions, the same
        # charge_slices: count emulated time as the Unicorn machine does, for comparing runs with it. A slice ends when an
        # abort or an SWI has been taken (the run stops at the vector) and is charged in full; a slice that ends in a
        # wait-for-interrupt is charged one instruction; after a wake-up with the interrupt masked the instructions up to the
        # unmask are charged one by one on top (_step_until_unmasked). One thing is not reproduced: the Unicorn machine watches
        # a masked CPU for UNMASK_STEPS (2000) instructions only and then holds the interrupt back to the end of the slice;
        # the core takes it at the unmask, as the CPU. A Unicorn run with that limit lifted is reproduced exactly.
        # Default: the environment variable DBCORE_CHARGE_SLICES (1 = on).
        self.charge_slices = os.environ.get('DBCORE_CHARGE_SLICES', '0') != '0' if charge_slices is None else charge_slices
        self.executed = 0                   # instructions the core completed (= insns unless charge_slices)
        # DBCORE_CURVE: a file that gets a line every CURVE_SLICES slices: instructions charged, executed, ns skipped
        # (what tools/cmp_runs.py --overcharge reads; it is of use with charge_slices)
        self._curve = open(os.environ['DBCORE_CURVE'], 'w') if os.environ.get('DBCORE_CURVE') else None
        self._curve_n = 0
        self._cut = False
        self._owed = False
        self._wfi_end = 0                   # max_insns of the run() that ended asleep in a wait-for-interrupt (see run)
        if self.charge_slices:
            for v in VECTOR_CUTS:
                core.add_hook(v)
        self.hw_regions = []
        self._bases = []                    # window number -> base address
        self._install_ext()
        for base, size in HW_REGIONS:
            self.add_hw_region(base, size)

    # ---- the bus behind the external windows ---------------------------
    def _install_ext(self):
        bus = self.bus; bases = self._bases; pc = self._pc; core = self.core
        def fail(e):
            if self._error is None:
                self._error = e
            core.request_stop()
        def rd(user, dev, off, size):
            try:
                if dev >= dbcore.STORE_ERASE:            # the NAND command machine in the core asks for a page, a program, an erase
                    if dev != dbcore.STORE_READ:         # (a page read changes nothing outside the core and sees no time)
                        if self._multi: self._multi_sync()
                        self.touched = True
                    return self._nand.store(dev, off)
                if self._multi: self._multi_sync()
                self.touched = True
                return bus.read(bases[dev] + off, size, pc)
            except BaseException as e:
                fail(e); return 0
        def wr(user, dev, off, size, value):
            try:
                if self._multi: self._multi_sync()
                self.touched = True
                if dev == dbcore.LINES_DEV:              # a compiled device changed an interrupt line of the Python controllers
                    self._line_out(off, bool(value))
                else:
                    bus.write(bases[dev] + off, size, value, pc)
            except BaseException as e:
                fail(e)
        core.set_ext(rd, wr, user=True)

    def _multi_sync(self):
        """A device is reached from inside Core.run_slices: the slices that went by since the call began are taken into
        the counts first, so that the models see the clock of the slice that runs, as the core does. Once per call: the
        call ends with the slice in which the host was called (a page read of the NAND store aside, which does not
        come here)."""
        self._multi = False
        c = self.core.clock_get(dbcore.C_INSNS)
        self.executed += c - self.insns; self.insns = c
        self._clock.charged(c)

    def _map_ram(self, addr, size):
        self.core.map_ram(addr, size)
        self._ram.append((addr, size))

    # ---- loading -------------------------------------------------------
    def load(self, addr, data, name=''):
        start = addr & ~(PAGE - 1); end = (addr + len(data) + PAGE - 1) & ~(PAGE - 1)
        if not any(b <= start and end <= b + s for b, s in self._ram):
            self._map_ram(start, end - start)
        self.core.mem_write(addr, bytes(data))
        self.log(f'loaded {name:16s} {addr:#010x}..{addr + len(data):#010x}')

    def load_pcore(self, path):
        a, d = loaders.load_pcore(path); self.load(a, d, 'PCORE(paged)')

    def load_cxc(self, path, name=None):
        a, d = loaders.load_cxc(path); self.load(a, d, name or path.rsplit('/', 1)[-1])

    def plant_boot_stubs(self, cb44=None):
        """TCM[0x40] -> putc(r0=char) ; TCM[0x44] -> second ROM callback."""
        w = self.core.mem_write
        putc = STUB_BASE
        w(putc, struct.pack('<4I', 0xE59F1004, 0xE5C10000, 0xE12FFF1E, UART_BASE))
        cb2 = STUB_BASE + 0x20
        w(cb2, cb44 or struct.pack('<2I', 0xE3A00000, 0xE12FFF1E))
        w(0x40, struct.pack('<II', putc, cb2))
        self.stubs = {'putc': putc, 'cb44': cb2}

    # ---- devices -------------------------------------------------------
    def _pc(self):
        """For the bus, during a device access: the address of the instruction that makes it (the core is one ahead)."""
        core = self.core
        return core.reg(dbcore.PC) - (2 if core.reg(dbcore.CPSR) & 0x20 else 4)

    def add_hw_region(self, base, size):
        """Route all accesses in [base, base+size) (whole 4K pages) through the bus."""
        self.hw_regions.append((base, size))
        self._bases.append(base)
        self.core.map_ext(base, size, len(self._bases) - 1)

    def attach(self, base, size, dev, name=None):
        """Plug a device model (plain class with read/write) into the bus; adds a hardware window if uncovered."""
        if not self._in_hw(base) or not self._in_hw(base + size - 1):
            self.add_hw_region(base & ~(PAGE - 1), (base + size + PAGE - 1 & ~(PAGE - 1)) - (base & ~(PAGE - 1)))
        self.bus.attach(base, size, dev, name)
        self._take_over(base, size, dev)
        return dev

    # ---- compiled devices ----------------------------------------------
    def _view(self, obj, mixin):
        """Turn a model object into a view of the device in the core: same class, with the mix-in in front."""
        base = type(obj)
        obj.__class__ = type(base.__name__ + 'InCore', (mixin, base), {'__doc__': mixin.__doc__})

    def _take_over(self, base, size, dev):
        """Called for every device attached: when it is one with a compiled twin that is switched on, move it into the core."""
        t = type(dev)
        if (base | size) & (PAGE - 1):
            return
        if t.__name__ == 'NandBus' and hasattr(getattr(dev, 's', None), 'chip'):
            self._nand_model = (dev.s, base)
            return
        if t.__name__ == 'SleepTimer' and t.__module__.split('.')[-1] == 'timer':
            if 'timer' in self.devices:
                self._line_out = dev.set_line           # where its lines go while the controllers are Python objects
                self._view(dev.clock, ClockView); dev.clock._bind(self.core)
                self._clock = dev.clock
                self._view(dev, TimerView); dev._bind(self.core)
                self.core.map_dev(base, size, dbcore.K_TIMER)
                self.compiled.append('timer')
            elif self._vic is not None and getattr(dev.set_line, '__self__', None) is self._vic:
                dev.set_line = self._vic.set_line       # taken before the pair moved: the same call, without the detour
        elif 'vic' in self.devices and any(k.__name__ == 'Vic' and k.__module__.split('.')[-1] == 'vic' for k in t.__mro__):
            # (the second controller of a pair is a view already when its window is attached)
            pair = getattr(dev.notify, '__self__', None)
            if pair is None or type(pair).__name__ not in ('VicPair', 'VicPairInCore') or dev not in (pair.vic0, pair.vic1):
                return
            if self._vic is None:
                self._view(pair, VicPairView); pair._bind(self.core)
                self._view(pair.vic0, VicView); pair.vic0._bind(self.core, dbcore.K_VIC0)
                self._view(pair.vic1, VicView); pair.vic1._bind(self.core, dbcore.K_VIC1)
                self._vic = pair
                self.compiled.append('vic')
            if pair is self._vic:
                self.core.map_dev(base, size, dbcore.K_VIC0 if dev is pair.vic0 else dbcore.K_VIC1)
        elif 'sysctl' in self.devices and t.__name__ == 'AppSysCtrl' and self._take_regs(base, size, dev, 'sysctl', dbcore.K_SYSCTL, 'regs', SysCtlView):
            self._sysctl = dev
            self._bus_write_swapped(self.bus.write_is_foreign())
        elif 'clkprof' in self.devices and t.__name__ == 'ClockProfile':
            self._take_regs(base, size, dev, 'clkprof', dbcore.K_CLKPROF, 'r', ClkProfView)

    def _take_regs(self, base, size, dev, name, kind, attr, view):
        """Move a block of stored registers (a model object with its dict of registers in `attr`) into the core, if the
        compiled block can hold what it has and answers as it does. True when it was moved."""
        regs = getattr(dev, attr, None)
        step = view._step
        if (size != PAGE or name in self.compiled or type(regs) is not dict
                or not all(type(o) is int and 0 <= o < PAGE and o % step == 0 and type(v) is int and 0 <= v <= M32 for o, v in regs.items())):
            return False
        diff = _answers_alike(dev, attr, kind, self.core.fresh)
        if diff:
            self.log('[own] %s at %#x: the compiled device does not answer as this %s does (first difference: %s); the Python model serves'
                     % (name, base, type(dev).__name__, diff))
            return False
        self._view(dev, view); dev._bind(self.core, kind, attr)
        self.core.map_dev(base, size, kind)
        self.compiled.append(name)
        return True

    def _bus_write_swapped(self, foreign):
        """bus.write was replaced. While it is not the bus's own method, the writes to system control go through it: the
        core declines them (the launcher watches them that way until the boot loader has started the modem)."""
        if self._sysctl is not None:
            self.core.dev_set(dbcore.K_SYSCTL, dbcore.S_WR_OUT, 1 if foreign else 0)

    def add_native_port(self, base, size):
        """Serve [base, base+size) (whole pages, at most 64K, inside one hardware window) through the data port of the core:
        while the device model has leased a buffer to the port, reads take its next bytes (or, with a write lease, writes
        fill it) without a Python call; every other access reaches the bus exactly as before. Returns the port for the
        device model, or None when the compiled NAND device is switched off (nothing is changed then)."""
        region = next(((b, s) for b, s in self.hw_regions if b <= base and base + size <= b + s), None)
        if 'nand' not in self.devices or region is None or size > 0x10000 or (base | size) & (PAGE - 1):
            return None
        port = CorePort(self.core, base, size)
        self.add_native_window(base, size, port, port.lib.port_mmio, port.lib.port_wmmio, port)
        self.compiled.append('nand')
        return port

    def add_native_window(self, base, size, port, read_c, write_c, pages):
        """Give [base, base+size) (whole pages inside a hardware window) to the compiled half of the NAND model: `read_c` and
        `write_c` name the entry points as emu/native_port.py does (attributes of port.lib). Returns (read, write) C
        function pointers of the Python path, as the Unicorn machine does, or (None, None) from a core that cannot make
        them (Core.HOST_POINTERS); the core needs none, since it passes on whatever the compiled half declines by itself."""
        assert not (base | size) & (PAGE - 1)
        kind = _PORT_KINDS[(read_c, write_c)]
        self.core.map_dev(base, size, kind)
        if kind == dbcore.K_NAND_ALE and 'nandcmd' in self.devices and self._nand is None and self._nand_model is not None:
            nand, bus_base = self._nand_model           # the last of the model's windows: its command machine moves too
            nm = sys.modules[type(nand).__module__]
            if nand.port is port and base == bus_base + nm.OFF_ALE:
                self.core.map_dev(bus_base + nm.OFF_CLE, nm.OFF_ALE - nm.OFF_CLE, dbcore.K_NAND_CLE)
                self._nand = NandInCore(self.core, nand, nm, keep_logs=self.keep_nand_logs)
                self.compiled.append('nandcmd')
        if not self.core.HOST_POINTERS:
            return None, None
        bus = self.bus; pc = self._pc
        slow, wcb = self.core.c_window(lambda off, sz: bus.read(base + off, sz, pc),
                                       lambda off, sz, value: bus.write(base + off, sz, value & ((1 << 8 * sz) - 1), pc))
        port._keep += [slow, wcb]
        return slow, wcb

    def attach_nand_regs(self, nand, ctrl_base, ale_base, off_ready, off_tim0, off_tim1):
        """What emu.native_port.attach_nand_regs does for the NAND model `nand` whose data port add_native_port made, with
        nothing of the host's: the controller page at ctrl_base (ready polls, the two timing registers) and the 64K of
        address cycles at ale_base go to the compiled half, and the model keeps that state in the port's words from now
        on. False (nothing changed) without a port."""
        port = nand.port
        if port is None:
            return False
        c = port.c
        c.off_ready, c.off_tim0, c.off_tim1 = off_ready, off_tim0, off_tim1
        self.add_native_window(ctrl_base, 0x1000, port, port.lib.reg_ctrl_r, port.lib.reg_ctrl_w, None)
        self.add_native_window(ale_base, 0x10000, port, None, port.lib.reg_ale_w, None)
        nand.use_port_state(True)
        return True

    def compiled_counts(self):
        """{name: (reads, writes)} served inside the core, for the window kinds in use."""
        g = self.core.dev_get
        kinds = (('nand data port', dbcore.K_NAND_DATA), ('nand registers', dbcore.K_NAND_CTRL), ('nand address cycles', dbcore.K_NAND_ALE),
                 ('nand commands', dbcore.K_NAND_CLE),
                 ('timer', dbcore.K_TIMER), ('vic0', dbcore.K_VIC0), ('vic1', dbcore.K_VIC1),
                 ('system control', dbcore.K_SYSCTL), ('clock profile', dbcore.K_CLKPROF))
        out = {n: (g(k, dbcore.F_READS), g(k, dbcore.F_WRITES)) for n, k in kinds}
        return {n: v for n, v in out.items() if v != (0, 0)}

    def _hw_span(self, a, n):
        return any(a < b + s and b < a + n for b, s in self.hw_regions)

    def _in_hw(self, a):
        return any(b <= a < b + s for b, s in self.hw_regions)

    def _nread(self):
        return self.bus.nread

    def _nwrite(self):
        return self.bus.nwrite

    # ---- cp15 and memory through the MMU -------------------------------
    def _cp(self, crn, crm, op1, op2):
        key = (crn, crm, op1, op2)
        i = CP15.get(key)
        if i is not None:
            return self.core.reg(i)
        return CP15_CONST.get(key, 0)

    def cp_read(self, crn, crm=0, op1=0, op2=0):
        return self._cp(crn, crm, op1, op2)

    def cp_write(self, crn, crm, op1, op2, val):
        i = CP15.get((crn, crm, op1, op2))
        if i is None:
            raise ValueError('cp_write: c%d,c%d,%d,%d is not reachable from outside the core' % (crn, crm, op1, op2))
        self.core.set_reg(i, val)

    def _read_phys32(self, pa):
        return self.core.mem_read32(pa)

    def read_virt(self, va, n):
        """Read guest memory at a virtual address (software walk when SCTLR.M is set, privileged read)."""
        core = self.core
        sctlr = core.reg(dbcore.SCTLR)
        if not (sctlr & 1):
            return core.mem_read(va, n)
        ttb, dacr = core.reg(dbcore.TTBR), core.reg(dbcore.DACR)
        sr = ((sctlr >> 8) & 1, (sctlr >> 9) & 1)
        out = b''
        while n:
            ok, pa = mmu.translate(va, False, True, ttb, dacr, sr, self._read_phys32)
            if not ok:
                raise MemError('read_virt: %#x is not mapped' % va)
            chunk = min(n, 0x400 - (va & 0x3FF))
            out += core.mem_read(pa, chunk); va += chunk; n -= chunk
        return out

    def sync_host(self):
        """Copy the RAM mapped with uc.mem_map_ptr into the caller's buffers."""
        for base, size, ptr in self._host:
            self.core.mem_read_into(base, ptr, size)

    # ---- entry hooks ---------------------------------------------------
    def add_entry_hook(self, addr, cb):
        """cb(uc, addr, size, user) each time execution arrives at addr, before the instruction there. Returns a handle for
        uc.hook_del."""
        addr &= ~1
        h = self._next_handle; self._next_handle += 1
        self._hooks.setdefault(addr, []).append((h, cb))
        self.core.add_hook(addr)
        return h

    def _del_hook(self, handle):
        for addr, lst in list(self._hooks.items()):
            lst[:] = [x for x in lst if x[0] != handle]
            if not lst:
                del self._hooks[addr]; self.core.del_hook(addr)

    def add_break(self, addr):
        def cb(uc, address, size, _):
            self.stop_reason = f'breakpoint {address:#x}'
        self.add_entry_hook(addr, cb)


    # ---- interrupts ----------------------------------------------------
    _irq_level = False

    @property
    def irq_pending(self):
        if self._vic is not None:
            return self._vic.irq_out
        return self._irq_level

    @irq_pending.setter
    def irq_pending(self, level):
        if self._vic is not None:           # the controllers in the core drive the input; callers pass their output
            return
        level = bool(level)
        if level != self._irq_level:
            self._irq_level = level
            self.core.set_irq(level)

    def raise_irq(self):
        self.irq_pending = True

    def inject_irq(self):
        """The core takes the interrupt itself at the next instruction boundary with CPSR.I clear: nothing to do here."""
        return False

    def _step_until_unmasked(self, limit=2000):
        """Called after a wake-up from wait-for-interrupt with an interrupt pending. The core needs no help: a CPU woken with
        the interrupt masked runs on and takes it at the instruction that unmasks it. With charge_slices the way to that
        instruction is walked here in single steps and every step is charged, as the Unicorn machine does; True once the
        interrupt is unmasked or taken."""
        if not self.charge_slices:
            return False
        core = self.core; steps = 0
        while steps < limit:
            cpsr = core.reg(dbcore.CPSR)
            if not cpsr & 0x80 or (steps and cpsr & 0x1f == 0x12 and core.reg(dbcore.PC) in IRQ_VECTORS):
                return True
            done, at_wfi = self._go(1)
            self.executed += done; self.insns += 1; steps += 1
            if at_wfi:
                core.set_reg(dbcore.PC, core.reg(dbcore.PC))
            if self._cut:                               # an abort or SWI in a step: the Unicorn machine meets it again in
                self._cut = False; self._owed = True    # the next slice and charges that slice in full
                return False
            if self.stop_reason:
                return False
        return not core.reg(dbcore.CPSR) & 0x80

    # ---- run -----------------------------------------------------------
    def _go(self, n, done=0, r=None):
        """Up to n instructions. Returns (instructions completed, halted in wait-for-interrupt). done, r: the slice was begun
        by the core (run_slices) and ended after `done` instructions with stop reason r: it is taken up from there."""
        core = self.core
        run, why = core.run, core.stop_reason
        while True:
            if r is None:
                done += run(n - done)
                r = why()
            if r == dbcore.STOP_BUDGET:
                return done, False
            if r == dbcore.STOP_WFI:
                return done, True
            if r == dbcore.STOP_HOOK:
                r = None
                pc = core.reg(dbcore.PC)
                cbs = self._hooks.get(pc)
                if cbs is None:
                    if self.charge_slices and pc in VECTOR_CUTS:
                        self._cut = True
                        return done, False
                    continue
                self.hook_hits += 1; self.touched = True
                if self._host and STUB_BASE <= pc < STUB_BASE + PAGE: self.sync_host()
                size = 2 if core.reg(dbcore.CPSR) & 0x20 else 4
                for _h, cb in list(cbs):
                    cb(self.uc, pc, size, None)
                if self.stop_reason or done >= n:
                    return done, False
                continue
            if r == dbcore.STOP_REQUEST:
                r = None
                if self._error is not None:
                    e, self._error = self._error, None
                    raise e
                if self.stop_reason or done >= n:
                    return done, False
                continue
            pc = core.reg(dbcore.PC)
            if r == dbcore.STOP_FETCH_UNMAPPED:
                self.stop_reason = f'fetch from unmapped memory at pc {pc:#x}'
            else:
                self.stop_reason = f'instruction not modelled, or exceptions without end, at pc {pc:#x}'
            return done, False

    def run(self, entry=None, max_insns=0, max_seconds=0, slice_insns=50000, step=None, quanta=1, due=None, until_ns=None):
        """Run until stop. `step()` (optional) is called between slices (timers etc.).
        quanta, due, until_ns: for a caller that calls again and again with max_insns one slice further (a quantum per
        call) and whose step() lets its models rest while the machine is not touched and the time due() is not reached
        (emu_irq.IrqTimerSystem). This call may then go through up to `quanta` such quanta as long as each is one whole
        slice after which step() would do nothing but set the clock and advance the timer, which the core does itself
        (Core.run_slices), and the clock is not past until_ns. It ends as the last of those calls would have ended;
        `quanta` of the machine says how many it stood for, `quantum_end` is the max_insns of the last."""
        core = self.core; t0 = time.time(); self.stop_reason = None
        nevents = core.event_count
        self.quanta = 1
        if quanta > 1 and (due is None or step is None or max_seconds or self.charge_slices or self._curve is not None or self.max_quanta < 2
                           or self._clock is None or self._vic is None or not getattr(core, 'has_slices', False)):
            quanta = 1
        # A run that ended asleep in a wait-for-interrupt (the idle callback had nothing yet) is taken up where it stopped:
        # this call ends where that one would have, had the callback let it go on. So step() is called at the same
        # instruction counts whichever way the caller wakes the CPU; a caller that paces by the host's clock chooses by it.
        end, self._wfi_end = self._wfi_end, 0
        if max_insns and self.insns < end < max_insns and not self.charge_slices:
            max_insns = end
        if entry is not None and (entry & ~1) != core.reg(dbcore.PC):     # None: go on from the PC
            self.uc.reg_write(UC_PC, entry)
        while True:
            n = slice_insns if not max_insns else min(slice_insns, max_insns - self.insns)
            if n <= 0:
                self.stop_reason = 'max-insns'; break
            if nevents() >= EVENT_LOG_KEEP:
                self.drain_events()
            if self._curve is not None:
                self._curve_n += 1
                if self._curve_n % CURVE_SLICES == 0:
                    self._curve.write('%d %d %d\n' % (self.insns, self.executed, core.clock_get(2)))
                    self._curve.flush()
            if self._owed:
                self._owed = False
                self.insns += n
                continue
            if quanta > 1 and n == slice_insns == max_insns - self.insns and not self.touched:
                # A quantum of the caller begins and nothing is waiting for the models: whole slices in the core.
                t = due(); at = self.insns
                self._multi = True
                try:
                    k, same, done, r = core.run_slices(n, min(quanta, self.max_quanta), None if t == INF else int(t), None if until_ns is None else int(until_ns // 1),
                                                       0xFFFFFFFF if self._last_pc is None else self._last_pc)
                finally:
                    self._multi = False
                quanta = 1
                if k:                                   # k quanta went by: each one slice, charged, the timer advanced
                    at += k * n
                    self.executed += at - self.insns; self.insns = at
                    self._clock.charged(at)
                    max_insns = at
                    self.quanta = k
                if r == dbcore.STOP_BUDGET:             # the last of them is to be looked at by step(), as every slice was before
                    if self.stop_reason:
                        break
                    step()
                    pc = core.reg(dbcore.PC)
                    if same and self._spinning(pc):
                        cpsr = core.reg(dbcore.CPSR)
                        if not self.irq_pending or cpsr & 0x80:
                            self.stop_reason = f'halted in branch-to-self loop at pc {pc:#x} (IRQs masked: {bool(cpsr & 0x80)})'
                            break
                    self._last_pc = pc
                    continue                            # n is 0 now: 'max-insns'
                if k:                                   # the slice that ended otherwise opens the next quantum
                    self._last_pc = core.slice_pc()
                    max_insns = self.insns + n
                    self.quanta = k + 1
                done, at_wfi = self._go(n, done, r)
            else:
                done, at_wfi = self._go(n)
            self.executed += done
            if not self.charge_slices:
                self.insns += done
            elif self._cut:
                self._cut = False
                self.insns += n
                if self.stop_reason:
                    break
                continue                                # as the Unicorn machine: no step() after a slice an exception ended
            else:
                self.insns += 1 if at_wfi else n
            if self.stop_reason:
                break
            if step: step()
            pc = core.reg(dbcore.PC)
            if at_wfi:
                if self.idle_cb:
                    keep = self.idle_cb()
                    if not keep and not self.irq_pending:
                        self.stop_reason = f'WFI at pc {pc - 4:#x}: idle callback has nothing scheduled'
                        self._wfi_end = max_insns
                        break
                elif self.stop_on_wfi and not self.irq_pending:
                    self.stop_reason = f'WFI (wait for interrupt) at pc {pc - 4:#x}, no interrupt source pending'
                    break
                core.set_reg(dbcore.PC, pc)             # the CPU goes on after the idle callback, interrupt or not
                if self.charge_slices and self.irq_pending:
                    if not self._step_until_unmasked():
                        if self.stop_reason:
                            break
                        continue
                    pc = core.reg(dbcore.PC)
            elif pc == self._last_pc and self._spinning(pc):
                # checked when two slices in a row end at the same pc (the page walk for the code is not free)
                cpsr = core.reg(dbcore.CPSR)
                if not self.irq_pending or cpsr & 0x80:
                    self.stop_reason = f'halted in branch-to-self loop at pc {pc:#x} (IRQs masked: {bool(cpsr & 0x80)})'
                    break
            self._last_pc = pc
            if max_seconds and time.time() - t0 > max_seconds:
                self.stop_reason = 'max-seconds'; break
        self.quantum_end = max_insns
        return self.stop_reason

    def _spinning(self, pc):
        """True if the instruction at the pc is a branch to itself."""
        try:
            if self.core.reg(dbcore.CPSR) & 0x20:
                return struct.unpack('<H', self.read_virt(pc, 2))[0] == 0xE7FE
            return struct.unpack('<I', self.read_virt(pc, 4))[0] == 0xEAFFFFFE
        except MemError:
            return False

    # ---- reports -------------------------------------------------------
    def dump_regs(self):
        r = self.core.regs(); cpsr = r[16]
        s = ' '.join(f'r{i}={v:#010x}' for i, v in enumerate(r[:13]))
        s += f'\nsp={r[13]:#010x} lr={r[14]:#010x} pc={r[15]:#010x} ' \
             f'cpsr={cpsr:#010x} ({"thumb" if cpsr & 0x20 else "arm"}, mode {cpsr & 0x1f:#x})'
        return s

    def drain_events(self):
        """Count the entries of the core's exception log and empty it. run() does this now and then, so that the log stays
        small however long the run is; the totals are kept here."""
        core = self.core
        for e in core.events():
            self._ev_kinds[e[1]] += 1
            if e[1] == dbcore.EV_UNDEFINED:
                self._ev_undef[e[2]] += 1
        core.clear_events()

    def event_counts(self):
        """Exceptions the core has taken since this machine was made, by name."""
        self.drain_events()
        return {EVENT_NAMES.get(k, str(k)): v for k, v in sorted(self._ev_kinds.items())}

    def undefined_summary(self):
        """[(pc, count, word at the pc or None, the word is an MCR / MRC p15)] of the undefined-instruction events so far.
        The word is read through the page table as it is now. The core refuses MCR / MRC p15 in user mode only."""
        self.drain_events()
        out = []
        for pc, n in sorted(self._ev_undef.items()):
            try:
                w = struct.unpack('<I', self.read_virt(pc, 4))[0]
            except MemError:
                w = None
            cp15 = w is not None and (w & 0x0F000010) == 0x0E000010 and (w >> 8) & 0xF == 15
            out.append((pc, n, w, cp15))
        return out
