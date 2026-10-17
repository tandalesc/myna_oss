"""dbcore_wasm.py: the binding of the compiled CPU core for Python that itself runs as WebAssembly (Pyodide): class Core with
the methods of dbcore.Core, over the WebAssembly module of the core. Standard library, plus `js` and `pyodide.ffi`.

    import dbcore_wasm                          # after web/pycore.js was loaded on the JavaScript side
    dbcore_wasm.load(open('dbcore.wasm', 'rb').read())
    c = dbcore_wasm.Core()
    m = machine.Machine(core=dbcore_wasm.Core())

Python cannot call the module directly (it is another WebAssembly instance with a memory of its own), so every call goes
through JavaScript: web/pycore.js instantiates the module, gives each core an object with the dbc_* calls bound to it, and
serves the module's two imports from the functions set_ext() installs. The constants are those of dbcore.py.

What differs from dbcore.Core:
- HOST_POINTERS is False: no c_window(), and mem_read_into() takes a buffer only.
- nand_regs() and nand_cmd() give objects whose attributes read and write the structure in the module's memory, one call
  per word (the ctypes structures are the memory itself).
- An exception raised in a function given to set_ext() is not lost: the run is stopped after that instruction and the
  call that was under way (run, set_line, dev_advance, dev_read, dev_write) raises it.
- With no read function installed a window reads as memory, as natively; but the NAND command machine cannot tell and
  calls the store all the same (the page register is then left as it is).
- set_ext_dev() gives one external window functions of its own (read(off, size), write(off, size, value)), which is
  the cheapest call from the module into Python; set_nand_store() leaves the chip's contents on the JavaScript side.
- load_snapshot(), state_load() and mem_write() also take a JavaScript Uint8Array, which then does not pass through Python.
SPDX-License-Identifier: MIT"""
import dbcore as _d
from pyodide.ffi import JsProxy, create_proxy, to_js

globals().update({n: v for n, v in vars(_d).items() if n.isupper() and isinstance(v, (int, float, str, tuple, dict))})
M32 = 0xFFFFFFFF

_glue = None


def load(wasm, pycore=None):
    """Instantiate the module and make it the one Core() uses. wasm: its bytes, or a JavaScript buffer or
    WebAssembly.Module. pycore: the object of web/pycore.js (default: globalThis.dbcorePy). Returns the instance's glue
    object, which Core() also takes as its argument."""
    global _glue
    if pycore is None:
        import js
        pycore = getattr(js, 'dbcorePy', None)
        if pycore is None:
            raise OSError('dbcore_wasm: web/pycore.js is not loaded (no globalThis.dbcorePy)')
    _glue = pycore.instantiate(_js(wasm))
    return _glue


def _js(data):
    """Bytes for a call into JavaScript: a Uint8Array (a copy), or the JavaScript object as it is."""
    if isinstance(data, JsProxy):
        return data
    return to_js(data if isinstance(data, (bytes, bytearray)) else bytes(data))


def _word(spec):
    off, size = spec
    if size == 8:
        return property(lambda self: self._g.peek64(self._p + off), lambda self, v: self._g.poke64(self._p + off, int(v)))
    return property(lambda self: self._g.peek32(self._p + off), lambda self, v: self._g.poke32(self._p + off, int(v) & M32))


class _Pair:
    """NandRegs.tim: two words."""
    def __init__(self, g, p):
        self._g, self._p = g, p

    def __len__(self):
        return 2

    def __getitem__(self, i):
        return self._g.peek32(self._p + 4 * range(2)[i])

    def __setitem__(self, i, v):
        self._g.poke32(self._p + 4 * range(2)[i], int(v) & M32)

    def __iter__(self):
        return iter((self[0], self[1]))


class NandRegs:
    """The words the NAND kinds share with the model outside, in the module's memory (dbcore.NAND_REGS_WORDS)."""
    def __init__(self, g, p):
        self._g, self._p = g, p

    tim = property(lambda self: _Pair(self._g, self._p + _d.NAND_REGS_TIM))
    pend = property(lambda self: self._g.view(self._p + _d.NAND_REGS_PEND, 8).to_bytes(),
                    lambda self, v: self._g.put(self._p + _d.NAND_REGS_PEND, _js(bytes(v)[:8])))


class NandCmd:
    """The words of the NAND command machine's structure, in the module's memory (dbcore.NAND_CMD_WORDS). The arrays are
    reached through Core.nand_buf(), nand_array(), nand_log()."""
    def __init__(self, g, p):
        self._g, self._p = g, p


for _n, _s in _d.NAND_REGS_WORDS.items():
    setattr(NandRegs, _n, _word(_s))
for _n, _s in _d.NAND_CMD_WORDS.items():
    setattr(NandCmd, _n, _word(_s))


class Core:
    """One CPU with its memory in the WebAssembly module. The methods are those of dbcore.Core."""
    HOST_POINTERS = False
    # the calls that go to JavaScript as they are: same arguments, a plain number back
    _FAST = ('reg', 'request_stop', 'add_hook', 'del_hook', 'icount', 'dev_get', 'dev_set', 'event_count', 'clear_events', 'irq_out',
             'clock_set', 'clock_rate')

    def __init__(self, glue=None):
        self._g = g = glue if glue is not None else _glue
        if g is None:
            raise OSError('dbcore_wasm: no module (call load() first)')
        self._k = k = g.core()
        self._c = k.ptr
        self._px = {}                       # the proxies of the functions given to the module, alive until replaced
        self._why = None                    # the stop reason of the last run
        self._nk = 0
        for name in self._FAST:
            setattr(self, name, getattr(k, name))
        self._run, self._stop, self._adv, self._next, self._sl = k.run, k.stop_reason, k.dev_advance, k.dev_next_event, k.set_line
        self.has_slices = hasattr(g.exports, 'dbc_run_slices')      # Core.run_slices is there (a module built before it has none)

    def fresh(self):
        """Another core in the same instance of the module, empty."""
        return type(self)(self._g)

    def close(self):
        if self._k is not None:
            for name in self._FAST:
                self.__dict__.pop(name, None)
            self._k.close(); self._k = None
            for p in self._px.values():
                p.destroy()
            self._px = {}

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _proxy(self, key, f):
        old = self._px.pop(key, None)
        p = None
        if f is not None:
            p = self._px[key] = create_proxy(f)
        return p, old

    # ---- memory
    def map_ram(self, addr, size):
        if self._k.map_ram(addr, size):
            raise ValueError('map_ram(%#x, %#x): address and size must be multiples of 4K' % (addr, size))

    def map_ext(self, addr, size, dev):
        if self._k.map_ext(addr, size, dev):
            raise ValueError('map_ext(%#x, %#x): address and size must be multiples of 4K' % (addr, size))

    def set_ext(self, read=None, write=None, user=False):
        """read(dev, offset, size) -> value and write(dev, offset, size, value) for the external windows; with user=True
        they take one more argument in front, as in dbcore.Core. They may call back into this core."""
        rd, old_r = self._proxy('rd', read)
        wr, old_w = self._proxy('wr', write)
        self._k.set_ext(rd, wr, bool(user))
        for p in (old_r, old_w):
            if p is not None:
                p.destroy()

    def set_ext_dev(self, dev, read=None, write=None):
        """Functions for external window `dev` alone, called in place of those of set_ext: read(offset, size) -> value,
        write(offset, size, value). A bound method of a device model does."""
        rd, old_r = self._proxy(('rd', dev), read)
        wr, old_w = self._proxy(('wr', dev), write)
        self._k.set_dev(dev, rd, wr)
        for p in (old_r, old_w):
            if p is not None:
                p.destroy()

    def set_nand_store(self, store):
        """Serve the store calls of the NAND command machine on the JavaScript side: `store` is an object of pycore.js's
        nandStore() (JsNandStore.js of this file). None: they go to the read function again."""
        self._k.set_store(store)

    def c_window(self, read, write):
        raise NotImplementedError('c_window: this core has no C function pointers (HOST_POINTERS)')

    def mem_read(self, addr, n):
        v = self._k.mem_read(addr, n)
        if v is None:
            raise ValueError('mem_read(%#x, %d)' % (addr, n))
        return v.to_bytes()

    def mem_read32(self, addr):
        v = self._k.mem_read32(addr)
        if v is None:
            raise ValueError('mem_read32(%#x)' % addr)
        return v

    def mem_read_into(self, addr, target, n):
        """Copy n bytes into `target`, a writable buffer of at least n bytes."""
        if isinstance(target, int):
            raise TypeError('mem_read_into: this core takes no host address (HOST_POINTERS)')
        v = self._k.mem_read(addr, n)
        if v is None:
            raise ValueError('mem_read_into(%#x, %d)' % (addr, n))
        v.assign_to(memoryview(target)[:n])

    def mem_write(self, addr, data):
        data = _js(data)
        if self._k.mem_write(addr, data):
            raise ValueError('mem_write(%#x, %d bytes)' % (addr, data.length))

    def load_snapshot(self, data):
        self._why = None
        if self._k.load_snapshot(_js(data)):
            raise ValueError('load_snapshot: not a snapshot')

    # ---- registers and inputs
    def reg(self, i):
        return self._k.reg(i)

    def set_reg(self, i, value):
        self._k.set_reg(i, value & M32)

    def regs(self):
        """r0-r15 and CPSR."""
        return list(self._k.regs())

    def set_irq(self, level):
        self._k.set_irq(1 if level else 0)

    def set_fiq(self, level):
        self._k.set_fiq(1 if level else 0)

    # ---- running
    def run(self, max_insns):
        r = self._run(max_insns)
        self._why = r & 7
        return r >> 3

    def stop_reason(self):
        w = self._why
        return self._stop() if w is None else w

    def run_why(self, max_insns):
        """run() and stop_reason() in one: (instructions completed, why it returned)."""
        r = self._run(max_insns)
        self._why = w = r & 7
        return r >> 3, w

    def run_slices(self, quantum, max_slices, due_ns=None, until_ns=None, last_pc=0xFFFFFFFF):
        """As dbcore.Core.run_slices."""
        r = self._k.run_slices(quantum, max_slices, -1 if due_ns is None else due_ns, -1 if until_ns is None else until_ns, last_pc)
        self._why = w = r & 7
        r >>= 3
        return r >> 33, bool(r >> 32 & 1), r & 0xFFFFFFFF, w

    def slice_pc(self):
        return self._k.slice_pc()

    def request_stop(self):
        self._k.request_stop()

    def add_hook(self, vaddr):
        return self._k.add_hook(vaddr)

    def del_hook(self, vaddr):
        self._k.del_hook(vaddr)

    def icount(self):
        return self._k.icount()

    # ---- compiled devices
    def map_dev(self, addr, size, kind):
        if self._k.map_dev(addr, size, kind):
            raise ValueError('map_dev(%#x, %#x, %d): not a span of whole pages inside one external window' % (addr, size, kind))

    def dev_read(self, kind, off, size):
        """An access to the device itself (no window, no shadow). The value, or None when the device declines."""
        v = self._k.dev_read(kind, off, size)
        if v == -1:
            raise ValueError('dev_read(%d, %#x, %d)' % (kind, off, size))
        return None if v == -2 else v

    def dev_write(self, kind, off, size, value):
        """True when the device took the write, False when it declines."""
        r = self._k.dev_write(kind, off, size, value & M32)
        if r < 0:
            raise ValueError('dev_write(%d, %#x, %d)' % (kind, off, size))
        return bool(r)

    def dev_get(self, kind, field):
        return self._k.dev_get(kind, field)

    def dev_set(self, kind, field, value):
        self._k.dev_set(kind, field, value)

    def dev_advance(self, kind=0):
        self._adv(kind)

    def dev_next_event(self, kind=0):
        """Time of the next event in ns, or None."""
        return self._next(kind)

    def nand_regs(self):
        """The shared words of the NAND kinds (valid until close())."""
        return NandRegs(self._g, self._k.dev_regs(_d.K_NAND_DATA))

    def nand_cmd(self):
        """The words of the NAND command machine's state (valid until close())."""
        self._nk = at = self._k.dev_regs(_d.K_NAND_CLE)
        k = NandCmd(self._g, at)
        if k.size != _d.NAND_CMD_SIZE:
            raise ValueError('nand_cmd: the module has another layout of the structure (%d bytes, here %d): rebuild it' % (k.size, _d.NAND_CMD_SIZE))
        return k

    def _nand_at(self, name):
        if not self._nk:
            self.nand_cmd()
        return self._nk + _d.NAND_CMD_ARRAYS[name][0]

    def nand_buf(self):
        """The page register of the command machine (NAND_RAW bytes)."""
        return self._g.view(self._nand_at('buf'), _d.NAND_RAW).to_bytes()

    def nand_set_buf(self, data):
        """Fill the page register from `data` (NAND_RAW bytes)."""
        if len(data) != _d.NAND_RAW:
            raise ValueError('nand_set_buf: %d bytes' % len(data))
        self._g.put(self._nk + 176 if self._nk else self._nand_at('buf'), _js(data))

    def nand_array(self, name):
        """The bytes of array `name` of the command machine: 'addr' or 'ids' (8 bytes each), 'count' (8 u64)."""
        return self._g.view(self._nand_at(name), _d.NAND_CMD_ARRAYS[name][1]).to_bytes()

    def nand_set_array(self, name, data):
        """Set the first len(data) bytes of 'addr' or 'ids'."""
        data = bytes(data)
        if name not in ('addr', 'ids') or len(data) > 8:
            raise ValueError('nand_set_array(%r, %d bytes)' % (name, len(data)))
        if data:
            self._g.put(self._nand_at(name), _js(data))

    def nand_log(self, n):
        """The first n entries of the command machine's log, 16 bytes each (the reader sets `nlog` back to 0)."""
        return self._g.view(self._nand_at('log'), 16 * min(n, _d.NAND_LOG_CAP)).to_bytes()

    def port_grant(self, data, write=False):
        """Lease bytes to the NAND data port: reads hand out `data` in order; with write=True writes fill len(data) bytes
        (`data` may then be that number)."""
        if write:
            n = data if isinstance(data, int) else len(data)
            r = self._k.port_grant(None, n, True)
        else:
            data = bytes(data); n = len(data)
            r = self._k.port_grant(_js(data), n, False)
        if r:
            raise ValueError('port_grant: %d bytes is too long' % n)

    def port_take(self, cap=0):
        """End the lease: (bytes handed out or taken in, the bytes a write lease took in, at most `cap` of them)."""
        n = self._k.port_take(cap)
        return n, (self._k.taken(min(n, cap)).to_bytes() if cap and n else b'')

    # ---- clock and interrupt lines
    def clock_set(self, insns, skipped_ns):
        self._k.clock_set(insns, skipped_ns)

    def clock_rate(self, ns_per_insn):
        self._k.clock_rate(ns_per_insn)

    def clock_get(self, what=_d.C_NOW_NS):
        return self._k.clock_get(what)

    def set_line(self, n, level):
        self._sl(n, 1 if level else 0)

    def line(self, n):
        return bool(self._k.line(n))

    def irq_out(self):
        """Outputs of the compiled interrupt controllers: bit 0 IRQ, bit 1 FIQ."""
        return self._k.irq_out()

    # ---- state
    def state_save(self, js=False):
        """The state container as bytes (js=True: as the JavaScript Uint8Array it is copied to, without a copy into Python)."""
        v = self._k.state_save()
        if v is None:
            raise ValueError('state_save: the module wrote no container')
        return v if js else v.to_bytes()

    def state_load(self, data):
        self._why = None
        r = self._k.state_load(_js(data))
        if r:
            raise ValueError('state_load: %s' % ('not a state container, or cut short' if r == -1 else 'a section in a version this core does not know'))

    # ---- event log
    def event_count(self):
        return self._k.event_count()

    def event(self, i):
        """(icount, kind, pc, far, fsr) of entry i."""
        e = self._k.event(i)
        if e is None:
            raise IndexError(i)
        return tuple(e)

    def events(self):
        return [tuple(e) for e in self._k.events().to_py()]

    def clear_events(self):
        self._k.clear_events()


class JsNandStore:
    """The contents of a NAND chip kept on the JavaScript side (pycore.js nandStore), as Python sees them. `js` is the
    object for Core.set_nand_store(); the methods are what a model in Python needs when it has to look at or change the
    chip itself (an access the core's machine declined, a file of the changed pages to save)."""
    def __init__(self, image=None, in_place=False, glue=None):
        """image: a JavaScript Uint8Array of whole pages (it stays where it is), bytes (copied once), or None."""
        g = glue if glue is not None else _glue
        self.js = g.nandStore(None if image is None else _js(image), bool(in_place))

    def page_bytes(self, page):
        return bytearray(self.js.page(page).to_bytes())

    def program(self, page, data):
        return self.js.program(page, _js(data))

    def erase(self, page):
        return self.js.erase(page)

    def changed_pages(self):
        return list(self.js.changed())

    def export_changed(self):
        """The changed pages in the layout of the NAND model's overlay file (per page: u32 number, the page)."""
        return self.js.exportChanged().to_bytes()

    def import_changed(self, data):
        self.js.importChanged(_js(data))

    def counts(self):
        return dict(reads=self.js.reads, programs=self.js.programs, erases=self.js.erases)
