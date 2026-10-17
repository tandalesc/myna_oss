"""dbcore.py: ctypes binding of the compiled CPU core (the `dbc_*` C interface). Standard library only.

    from dbcore import Core
    c = Core()                                  # loads the library, see find_library()
    c.load_snapshot(open(path, 'rb').read())
    c.map_ext(0x80000000, 0x1000, dev=3)
    c.set_ext(read=lambda dev, off, size: 0, write=lambda dev, off, size, value: None)
    done = c.run(1_000_000); why = c.stop_reason()

The library is looked for in: the file named by DBCORE_LIB; the folder named by DBCORE_OUT; the default build folder
(`build/` next to build.sh). Register ids, stop reasons and event kinds are the constants below.

Compiled devices (see the README, "Compiled devices"): map_dev() gives a span of an external window to one of them (K_*);
dev_read / dev_write reach a device directly, dev_get / dev_set one word of its state (the F_* and per-device field numbers);
dev_advance / dev_next_event are its timed events; clock_set / clock_rate / clock_get the clock they all read; set_line / line /
irq_out the interrupt lines; port_grant / port_take the lease of the NAND data port, nand_regs() the words that device shares,
nand_cmd() the state of its command machine (which calls the store through the read callback: STORE_*);
state_save / state_load the whole state as one container. System control and the clock profile (K_SYSCTL, K_CLKPROF)
are register blocks with no call of their own.

Whoever uses a core (the machine adapter, machine.py) goes through the methods of Core only, so that another class with the
same methods can stand in its place: dbcore_wasm.py is that class over the WebAssembly module. The constants of this file
are of use there too, so the file can be imported where ctypes is missing; only making a Core needs it. What a core of
this file alone can do is said by HOST_POINTERS (see Core).
SPDX-License-Identifier: MIT"""
import functools
import os
import sys
try:
    import ctypes
except ImportError:                 # the constants are still of use (dbcore_wasm.py); a Core of this file cannot be made
    ctypes = None

# register ids of reg() / set_reg()
R0, SP, LR, PC, CPSR, SPSR = 0, 13, 14, 15, 16, 17        # r0-r15 and SPSR are those of the current mode; PC = next instruction
MODES = ('usr', 'fiq', 'irq', 'svc', 'abt', 'und')
BANK = {m: (18 + 3 * i, 19 + 3 * i, 20 + 3 * i) for i, m in enumerate(MODES)}      # mode -> ids of (sp, lr, spsr)
FIQ_R8, USR_R8 = 36, 41                                   # five ids each: r8-r12
SCTLR, TTBR, DACR, FCSE, DFSR, IFSR, FAR = 46, 47, 48, 49, 50, 51, 52

# stop_reason()
STOP_BUDGET, STOP_WFI, STOP_REQUEST, STOP_HOOK, STOP_FETCH_UNMAPPED, STOP_UNHANDLED = range(6)
# event kinds
EV_DATA_ABORT, EV_PREFETCH_ABORT, EV_SWI, EV_UNDEFINED, EV_IRQ, EV_FIQ = range(1, 7)

# compiled devices: window kinds of map_dev and device numbers of the dev_* calls
K_HOST, K_NAND_DATA, K_NAND_CTRL, K_NAND_ALE, K_TIMER, K_VIC0, K_VIC1, K_NAND_CLE, K_SYSCTL, K_CLKPROF = range(10)
LINES_DEV = 0xFFFFFFFF            # device number of the write callback that reports an interrupt line: (LINES_DEV, line, 4, level)
NO_EVENT = 0xFFFFFFFFFFFFFFFF     # dev_next_event: nothing armed; also the timer's field T_DEADLINE0 when no event is armed
# dev_get / dev_set fields. Every kind: accesses served
F_READS, F_WRITES = 0xF0, 0xF1
# NAND kinds (read only): position and end of the lease, read lease, write lease; N_COUNT + L_*: commands and ECC reads the
# command machine served; the machine is on; bytes of NandCmd
N_POS, N_LIMIT, N_ACTIVE, N_WACTIVE = range(4)
N_COUNT, N_ON, N_SIZE = 0x10, 0x20, 0x21
# the store of the NAND command machine: device numbers of the read callback (offset = page, size 4). STORE_READ: put the
# page (0x840 bytes, data and spare area) into NandCmd.buf; STORE_PROGRAM: program the page from NandCmd.buf (bits go from 1
# to 0 only) and return 0, or 1 for a failure; STORE_ERASE: erase the block that holds the page, same result
STORE_READ, STORE_PROGRAM, STORE_ERASE = 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC
# NandCmd: mode; "none" of cmd and of the page fields; kinds of log entries (and indices of count)
NAND_MODES = ('idle', 'id', 'read', 'status', None, 'prog', 'addr')
NAND_NO_CMD, NAND_NONE, NAND_POS_MAX, NAND_RAW, NAND_LOG_CAP = 0x100, 0xFFFFFFFF, 0x7FFF0000, 0x840, 1024
L_ECC, L_READ, L_CBREAD, L_PROGRAM, L_ERASE, L_UNKNOWN, L_RESET = range(1, 8)
# the structures of nand_regs() and nand_cmd(), little-endian: name -> (byte offset, bytes) of the words, and of the arrays
NAND_REGS_WORDS = dict(reg_on=(0, 4), busy=(4, 4), ale_ok=(16, 4), npend=(20, 4), off_ready=(32, 4), off_tim0=(36, 4), off_tim1=(40, 4),
                       served=(48, 8), wserved=(56, 8))
NAND_REGS_TIM, NAND_REGS_PEND, NAND_REGS_SIZE = 8, 24, 64
NAND_CMD_WORDS = dict(on=(0, 4), mode=(4, 4), cmd=(8, 4), naddr=(12, 4), pos=(24, 4), status=(28, 4), buf_valid=(32, 4), ctrl_val=(36, 4),
                      prog_page=(40, 4), cb_page=(44, 4), last_row=(48, 4), pages=(52, 4), ecc_idx=(56, 8), ecc_odd=(64, 4), ecc_even=(68, 4),
                      ecc_col=(72, 4), nids=(76, 4), off_ctrl=(88, 4), off_status=(92, 4), off_ecc=(96, 4), log_on=(100, 4), nlog=(104, 4),
                      size=(108, 4))
NAND_CMD_ARRAYS = dict(addr=(16, 8), ids=(80, 8), count=(112, 64), buf=(176, NAND_RAW), log=(176 + NAND_RAW, 16 * NAND_LOG_CAP))
NAND_CMD_SIZE = 176 + NAND_RAW + 16 * NAND_LOG_CAP
# timer; T_REG + offset = the register stored at that offset of the window
T_STATUS, T_DEADLINE0, T_FIRED, T_EXTRA, T_WRITTEN, T_HELD_READS, T_ARMS, T_LINE0, T_LINE1, T_READ_STEP = range(10)
T_REG = 0x1000
# interrupt controllers (per controller; V_EDGES and V_ON belong to the pair); V_VECTADDR + i, V_VECTCNTL + i, V_PRIO + i
V_LINES, V_SOFT, V_ENABLE, V_SELECT, V_PROTECTION, V_DEFVECT, V_READS_VECT, V_WRITES_VECT, V_DEPTH, V_EDGES = range(10)
V_VECTADDR, V_VECTCNTL, V_PRIO, V_ON = 0x10, 0x20, 0x30, 0xFE
# system control and the clock profile; S_REG + offset = the register stored at that offset of the window (the clock
# profile has one per word). S_WR_OUT (system control): its writes are declined and go to the write callback
S_WR_OUT, S_REG = 0, 0x1000
# clock_get
C_NOW_NS, C_INSNS, C_SKIPPED_NS, C_RATE_BITS = range(4)


if ctypes is not None:
    class NandRegs(ctypes.Structure):
        """The words the NAND kinds share with the model outside (Core.nand_regs())."""
        _fields_ = [('reg_on', ctypes.c_uint32), ('busy', ctypes.c_uint32), ('tim', ctypes.c_uint32 * 2), ('ale_ok', ctypes.c_uint32),
                    ('npend', ctypes.c_uint32), ('pend', ctypes.c_uint8 * 8), ('off_ready', ctypes.c_uint32), ('off_tim0', ctypes.c_uint32),
                    ('off_tim1', ctypes.c_uint32), ('pad', ctypes.c_uint32), ('served', ctypes.c_uint64), ('wserved', ctypes.c_uint64)]


    class NandCmd(ctypes.Structure):
        """The state of the NAND command machine (Core.nand_cmd()): the model outside fills it in and sets `on`; with `on` clear
        the state is the model's again. `buf` is the page register, which the store calls fill and read. A log entry is two
        words: kind | value << 8 | row << 32, and a second number (bytes fed for an ECC read, the column for a page read)."""
        _fields_ = [('on', ctypes.c_uint32), ('mode', ctypes.c_uint32), ('cmd', ctypes.c_uint32), ('naddr', ctypes.c_uint32), ('addr', ctypes.c_uint8 * 8),
                    ('pos', ctypes.c_uint32), ('status', ctypes.c_uint32), ('buf_valid', ctypes.c_uint32), ('ctrl_val', ctypes.c_uint32),
                    ('prog_page', ctypes.c_uint32), ('cb_page', ctypes.c_uint32), ('last_row', ctypes.c_uint32), ('pages', ctypes.c_uint32),
                    ('ecc_idx', ctypes.c_uint64), ('ecc_odd', ctypes.c_uint32), ('ecc_even', ctypes.c_uint32), ('ecc_col', ctypes.c_uint32),
                    ('nids', ctypes.c_uint32), ('ids', ctypes.c_uint8 * 8), ('off_ctrl', ctypes.c_uint32), ('off_status', ctypes.c_uint32),
                    ('off_ecc', ctypes.c_uint32), ('log_on', ctypes.c_uint32), ('nlog', ctypes.c_uint32), ('size', ctypes.c_uint32),
                    ('count', ctypes.c_uint64 * 8), ('buf', ctypes.c_uint8 * NAND_RAW), ('log', ctypes.c_uint64 * (2 * NAND_LOG_CAP))]


    EXT_READ = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32)
    EXT_WRITE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32)
    # the callbacks of a window of emu/native_port.py, which the adapter hands to that module (Core.c_window)
    SLOW_R = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint, ctypes.c_void_p)
    SLOW_W = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint, ctypes.c_uint64, ctypes.c_void_p)

_NAMES = ('libdbcore.dylib', 'libdbcore.so', 'dbcore.dll')


def find_library():
    """Path of the shared library: DBCORE_LIB, else DBCORE_OUT, else the default build folder."""
    p = os.environ.get('DBCORE_LIB')
    if p:
        return p
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = [d for d in (os.environ.get('DBCORE_OUT'), os.path.join(os.path.dirname(here), 'build')) if d]
    for d in dirs:
        for n in _NAMES:
            if os.path.isfile(os.path.join(d, n)):
                return os.path.join(d, n)
    raise OSError('dbcore: no library found in %s (run build.sh, or set DBCORE_LIB or DBCORE_OUT)' % ', '.join(dirs))


_lib = None


def library(path=None):
    """The loaded library with its prototypes set (loaded once)."""
    global _lib
    if _lib is not None and path is None:
        return _lib
    if ctypes is None:
        raise OSError('dbcore: no ctypes here, so no library can be loaded (in a browser: dbcore_wasm.py)')
    L = ctypes.CDLL(path or find_library())
    P, u32, u64, i32 = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_int
    pu32, pu64 = ctypes.POINTER(u32), ctypes.POINTER(u64)
    for name, res, args in (
            ('dbc_new', P, ()), ('dbc_free', None, (P,)),
            ('dbc_map_ram', i32, (P, u32, u32)), ('dbc_map_ext', i32, (P, u32, u32, u32)),
            ('dbc_set_ext', None, (P, EXT_READ, EXT_WRITE, P)),
            ('dbc_mem_read', i32, (P, u32, ctypes.c_void_p, u32)), ('dbc_mem_write', i32, (P, u32, ctypes.c_char_p, u32)),
            ('dbc_load_snapshot', i32, (P, ctypes.c_char_p, u32)),
            ('dbc_reg', u32, (P, u32)), ('dbc_set_reg', None, (P, u32, u32)),
            ('dbc_set_irq', None, (P, i32)), ('dbc_set_fiq', None, (P, i32)),
            ('dbc_run', u64, (P, u64)), ('dbc_stop_reason', u32, (P,)), ('dbc_request_stop', None, (P,)),
            ('dbc_run_slices', u64, (P, u64, u32, u64, u64, u32)), ('dbc_slice_pc', u32, (P,)),
            ('dbc_add_hook', i32, (P, u32)), ('dbc_del_hook', None, (P, u32)),
            ('dbc_icount', u64, (P,)), ('dbc_event_count', u32, (P,)),
            ('dbc_event', i32, (P, u32, pu64, pu32, pu32, pu32, pu32)), ('dbc_clear_events', None, (P,)),
            ('dbc_map_dev', i32, (P, u32, u32, u32)), ('dbc_dev_read', i32, (P, u32, u32, u32, pu32)), ('dbc_dev_write', i32, (P, u32, u32, u32, u32)),
            ('dbc_dev_get', u64, (P, u32, u32)), ('dbc_dev_set', None, (P, u32, u32, u64)),
            ('dbc_dev_advance', None, (P, u32)), ('dbc_dev_next_event', u64, (P, u32)), ('dbc_dev_regs', P, (P, u32)),
            ('dbc_port_grant', i32, (P, ctypes.c_void_p, u32, i32)), ('dbc_port_take', u32, (P, ctypes.c_void_p, u32)),
            ('dbc_clock_set', None, (P, u64, u64)), ('dbc_clock_rate', None, (P, ctypes.c_double)), ('dbc_clock_get', u64, (P, u32)),
            ('dbc_set_line', None, (P, u32, i32)), ('dbc_line', i32, (P, u32)), ('dbc_irq_out', u32, (P,)),
            ('dbc_state_size', u32, (P,)), ('dbc_state_save', u32, (P, ctypes.c_void_p, u32)), ('dbc_state_load', i32, (P, ctypes.c_char_p, u32))):
        f = getattr(L, name); f.restype = res; f.argtypes = args
    if path is None:
        _lib = L
    return L


class Core:
    """One CPU with its memory. Methods mirror the C interface; errors of the calls that return a status raise ValueError.

    HOST_POINTERS says what only a core in the address space of the host can do: mem_read_into() to a host address and
    c_window(), C function pointers for a helper compiled outside. A user asks before it relies on either.

    The calls of _FAST are, on an instance, the library's functions with the core bound (no Python frame in between); they
    take and return what the methods of the same names below do."""
    HOST_POINTERS = True
    _FAST = ('reg', 'run', 'stop_reason', 'request_stop', 'icount', 'dev_get', 'event_count', 'clear_events', 'irq_out')

    def __init__(self, lib=None):
        self._l = l = library(lib) if lib is None or isinstance(lib, str) else lib
        self.has_slices = hasattr(l, 'dbc_run_slices')       # Core.run_slices is there (a library built before it has none)
        self._c = c = l.dbc_new()
        self._rd = self._wr = None          # the ctypes callbacks must stay alive as long as the core uses them
        self._nk = 0                        # address of the NAND command machine's structure, once asked for
        for name in self._FAST:
            setattr(self, name, functools.partial(getattr(l, 'dbc_' + name), c))

    def fresh(self):
        """Another core of the same library, empty."""
        return type(self)(self._l)

    def close(self):
        if self._c:
            for name in self._FAST:
                self.__dict__.pop(name, None)
            self._l.dbc_free(self._c); self._c = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- memory
    def map_ram(self, addr, size):
        if self._l.dbc_map_ram(self._c, addr, size):
            raise ValueError('map_ram(%#x, %#x): address and size must be multiples of 4K' % (addr, size))

    def map_ext(self, addr, size, dev):
        if self._l.dbc_map_ext(self._c, addr, size, dev):
            raise ValueError('map_ext(%#x, %#x): address and size must be multiples of 4K' % (addr, size))

    def set_ext(self, read=None, write=None, user=False):
        """read(dev, offset, size) -> value and write(dev, offset, size, value) for the external windows. They may call
        set_irq, set_fiq, request_stop, mem_read and mem_write of this core. An exception raised inside one cannot cross the
        C call: it is printed by ctypes and the read returns 0.
        user=True: the two take one more argument in front, which means nothing (the C callbacks' `user`), and read returns
        a value of 32 bits; they are then called with no Python frame in between."""
        if user:
            self._rd = EXT_READ(read) if read else EXT_READ(0)
            self._wr = EXT_WRITE(write) if write else EXT_WRITE(0)
        else:
            self._rd = EXT_READ(lambda user, dev, off, size: read(dev, off, size) & 0xFFFFFFFF) if read else EXT_READ(0)
            self._wr = EXT_WRITE(lambda user, dev, off, size, value: write(dev, off, size, value)) if write else EXT_WRITE(0)
        self._l.dbc_set_ext(self._c, self._rd, self._wr, None)

    def c_window(self, read, write):
        """(read, write) as C function pointers with the signatures of a window of emu/native_port.py, calling
        read(offset, size) -> value and write(offset, size, value). Only with HOST_POINTERS; the caller keeps them alive."""
        return (SLOW_R(lambda uc, off, size, _: read(off, size)), SLOW_W(lambda uc, off, size, value, _: write(off, size, value)))

    def mem_read(self, addr, n):
        buf = ctypes.create_string_buffer(n)
        if self._l.dbc_mem_read(self._c, addr, buf, n):
            raise ValueError('mem_read(%#x, %d)' % (addr, n))
        return buf.raw

    def mem_read32(self, addr):
        """One little-endian word."""
        v = ctypes.c_uint32()
        if self._l.dbc_mem_read(self._c, addr, ctypes.byref(v), 4):
            raise ValueError('mem_read32(%#x)' % addr)
        return v.value

    def mem_read_into(self, addr, target, n):
        """Copy n bytes into `target`: a writable buffer of at least n bytes, or (only with HOST_POINTERS) an address of the host."""
        if not isinstance(target, int):
            target = (ctypes.c_char * n).from_buffer(target)
        if self._l.dbc_mem_read(self._c, addr, target, n):
            raise ValueError('mem_read_into(%#x, %d)' % (addr, n))

    def mem_write(self, addr, data):
        data = bytes(data)
        if self._l.dbc_mem_write(self._c, addr, data, len(data)):
            raise ValueError('mem_write(%#x, %d bytes)' % (addr, len(data)))

    def load_snapshot(self, data):
        data = bytes(data)
        if self._l.dbc_load_snapshot(self._c, data, len(data)):
            raise ValueError('load_snapshot: not a snapshot')

    # ---- registers and inputs
    def reg(self, i):
        return self._l.dbc_reg(self._c, i)

    def set_reg(self, i, value):
        self._l.dbc_set_reg(self._c, i, value & 0xFFFFFFFF)

    def regs(self):
        """r0-r15 and CPSR."""
        return [self._l.dbc_reg(self._c, i) for i in range(17)]

    def set_irq(self, level):
        self._l.dbc_set_irq(self._c, 1 if level else 0)

    def set_fiq(self, level):
        self._l.dbc_set_fiq(self._c, 1 if level else 0)

    # ---- running
    def run(self, max_insns):
        return self._l.dbc_run(self._c, max_insns)

    def stop_reason(self):
        return self._l.dbc_stop_reason(self._c)

    def run_why(self, max_insns):
        """run() and stop_reason() in one: (instructions completed, why it returned)."""
        return self._l.dbc_run(self._c, max_insns), self._l.dbc_stop_reason(self._c)

    def run_slices(self, quantum, max_slices, due_ns=None, until_ns=None, last_pc=0xFFFFFFFF):
        """Slices of `quantum` instructions with the host's work between two slices done in the core (the instructions
        charged to the clock, the timer's event fired) while nothing needs the host: until the host was called in a slice,
        the clock reaches due_ns or passes until_ns (None: no such time), max_slices are done, or a slice ends at the pc
        the one before ended at (last_pc for the first). Returns (whole slices, the last of them ended at the pc of the
        one before, instructions of a slice that ended otherwise than by its budget and is left to the caller, its stop
        reason: 0 when there is no such slice)."""
        r = self._l.dbc_run_slices(self._c, quantum, max_slices, NO_EVENT if due_ns is None else due_ns, NO_EVENT if until_ns is None else until_ns, last_pc)
        return r >> 33, bool(r >> 32 & 1), r & 0xFFFFFFFF, self._l.dbc_stop_reason(self._c)

    def slice_pc(self):
        """The pc at the end of the last whole slice of run_slices()."""
        return self._l.dbc_slice_pc(self._c)

    def request_stop(self):
        self._l.dbc_request_stop(self._c)

    def add_hook(self, vaddr):
        return self._l.dbc_add_hook(self._c, vaddr)

    def del_hook(self, vaddr):
        self._l.dbc_del_hook(self._c, vaddr)

    def icount(self):
        return self._l.dbc_icount(self._c)

    # ---- compiled devices
    def map_dev(self, addr, size, kind):
        """Give [addr, addr + size), which must lie in one external window, to compiled device `kind` (K_HOST: back to the
        callbacks alone). What the device declines still reaches the callbacks, with the numbers of that external window."""
        if self._l.dbc_map_dev(self._c, addr, size, kind):
            raise ValueError('map_dev(%#x, %#x, %d): not a span of whole pages inside one external window' % (addr, size, kind))

    def dev_read(self, kind, off, size):
        """An access to the device itself (no window, no shadow). The value, or None when the device declines."""
        v = ctypes.c_uint32()
        r = self._l.dbc_dev_read(self._c, kind, off, size, v)
        if r < 0:
            raise ValueError('dev_read(%d, %#x, %d)' % (kind, off, size))
        return v.value if r else None

    def dev_write(self, kind, off, size, value):
        """True when the device took the write, False when it declines."""
        r = self._l.dbc_dev_write(self._c, kind, off, size, value & 0xFFFFFFFF)
        if r < 0:
            raise ValueError('dev_write(%d, %#x, %d)' % (kind, off, size))
        return bool(r)

    def dev_get(self, kind, field):
        return self._l.dbc_dev_get(self._c, kind, field)

    def dev_set(self, kind, field, value):
        self._l.dbc_dev_set(self._c, kind, field, value & 0xFFFFFFFFFFFFFFFF)

    def dev_advance(self, kind=0):
        """Fire the events of the device (0: of all) that are due at the clock's time. The scheduler calls it between slices."""
        self._l.dbc_dev_advance(self._c, kind)

    def dev_next_event(self, kind=0):
        """Time of the next event in ns, or None."""
        t = self._l.dbc_dev_next_event(self._c, kind)
        return None if t == NO_EVENT else t

    def nand_regs(self):
        """The shared words of the NAND kinds, as a live structure inside the core (valid until close())."""
        return NandRegs.from_address(self._l.dbc_dev_regs(self._c, K_NAND_DATA))

    def nand_cmd(self):
        """The state of the NAND command machine, as a live structure inside the core (valid until close()). Its words
        are read and set as attributes (NAND_CMD_WORDS); for its arrays there are the methods below, which a core
        that has no structures of the host serves too."""
        self._nk = at = self._l.dbc_dev_regs(self._c, K_NAND_CLE)
        k = NandCmd.from_address(at)
        if k.size != ctypes.sizeof(NandCmd):
            raise ValueError('nand_cmd: the library has another layout of the structure (%d bytes, here %d): rebuild it' % (k.size, ctypes.sizeof(NandCmd)))
        return k

    def _nand_at(self, name):
        if not self._nk:
            self.nand_cmd()
        return self._nk + NAND_CMD_ARRAYS[name][0]

    def nand_buf(self):
        """The page register of the command machine (NAND_RAW bytes)."""
        return ctypes.string_at(self._nk + 176 if self._nk else self._nand_at('buf'), NAND_RAW)

    def nand_set_buf(self, data):
        """Fill the page register from `data` (bytes, NAND_RAW of them)."""
        if len(data) != NAND_RAW:
            raise ValueError('nand_set_buf: %d bytes' % len(data))
        ctypes.memmove(self._nk + 176 if self._nk else self._nand_at('buf'), data, NAND_RAW)

    def nand_array(self, name):
        """The bytes of array `name` of the command machine: 'addr' or 'ids' (8 bytes each), 'count' (8 u64)."""
        return ctypes.string_at(self._nand_at(name), NAND_CMD_ARRAYS[name][1])

    def nand_set_array(self, name, data):
        """Set the first len(data) bytes of 'addr' or 'ids'."""
        data = bytes(data)
        if name not in ('addr', 'ids') or len(data) > 8:
            raise ValueError('nand_set_array(%r, %d bytes)' % (name, len(data)))
        ctypes.memmove(self._nand_at(name), data, len(data))

    def nand_log(self, n):
        """The first n entries of the command machine's log, 16 bytes each (the reader sets `nlog` back to 0)."""
        return ctypes.string_at(self._nand_at('log'), 16 * min(n, NAND_LOG_CAP))

    def port_grant(self, data, write=False):
        """Lease bytes to the NAND data port: reads hand out `data` in order; with write=True writes fill len(data) bytes
        (`data` may then be that number)."""
        if write:
            n = data if isinstance(data, int) else len(data); data = None
        else:
            data = bytes(data); n = len(data)
        if self._l.dbc_port_grant(self._c, data, n, 1 if write else 0):
            raise ValueError('port_grant: %d bytes is too long' % n)

    def port_take(self, cap=0):
        """End the lease: (bytes handed out or taken in, the bytes a write lease took in, at most `cap` of them)."""
        buf = ctypes.create_string_buffer(cap) if cap else None
        n = self._l.dbc_port_take(self._c, buf, cap)
        return n, (buf.raw[:min(n, cap)] if buf is not None else b'')

    # ---- clock and interrupt lines
    def clock_set(self, insns, skipped_ns):
        self._l.dbc_clock_set(self._c, insns, skipped_ns)

    def clock_rate(self, ns_per_insn):
        self._l.dbc_clock_rate(self._c, ns_per_insn)

    def clock_get(self, what=C_NOW_NS):
        return self._l.dbc_clock_get(self._c, what)

    def set_line(self, n, level):
        self._l.dbc_set_line(self._c, n, 1 if level else 0)

    def line(self, n):
        return bool(self._l.dbc_line(self._c, n))

    def irq_out(self):
        """Outputs of the compiled interrupt controllers: bit 0 IRQ, bit 1 FIQ."""
        return self._l.dbc_irq_out(self._c)

    # ---- state
    def state_save(self):
        """The state container (CPU, cp15, memory with its windows, clock, lines, compiled devices) as bytes."""
        n = self._l.dbc_state_size(self._c)
        buf = ctypes.create_string_buffer(n)
        got = self._l.dbc_state_save(self._c, buf, n)
        if not n or got != n:
            raise ValueError('state_save: %d of %d bytes' % (got, n))
        return buf.raw

    def state_load(self, data):
        data = bytes(data)
        r = self._l.dbc_state_load(self._c, data, len(data))
        if r:
            raise ValueError('state_load: %s' % ('not a state container, or cut short' if r == -1 else 'a section in a version this core does not know'))

    # ---- event log
    def event_count(self):
        return self._l.dbc_event_count(self._c)

    def event(self, i):
        """(icount, kind, pc, far, fsr) of entry i."""
        n = ctypes.c_uint64(); k = ctypes.c_uint32(); pc = ctypes.c_uint32(); far = ctypes.c_uint32(); fsr = ctypes.c_uint32()
        if self._l.dbc_event(self._c, i, n, k, pc, far, fsr):
            raise IndexError(i)
        return n.value, k.value, pc.value, far.value, fsr.value

    def events(self):
        return [self.event(i) for i in range(self.event_count())]

    def clear_events(self):
        self._l.dbc_clear_events(self._c)


if __name__ == '__main__':
    # dbcore.py SNAPSHOT INSTRUCTIONS: run a snapshot with no external windows and print the registers
    import json
    import time
    c = Core(); c.load_snapshot(open(sys.argv[1], 'rb').read())
    t = time.perf_counter(); done = c.run(int(float(sys.argv[2]))); dt = time.perf_counter() - t
    print(json.dumps(dict(done=done, stop=c.stop_reason(), secs=round(dt, 4), mips=round(done / max(dt, 1e-9) / 1e6, 1),
                          events=c.event_count(), regs=' '.join('%08x' % x for x in c.regs()))))
