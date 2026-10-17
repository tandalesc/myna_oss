"""I2C bus: routes the master's transfers to slave models by 7-bit address. Plain Python.

A slave is any object with
    start(read: bool) -> bool     addressed (after a start or repeated start); return False to not acknowledge
    write(byte) -> bool           one byte from the master; return False to not acknowledge
    read(ack: bool) -> int        one byte to the master (ack = the master will acknowledge it, i.e. more follow)
    stop()                        stop condition
An address without a slave is not acknowledged and logged once per (address, direction, context) with the context string
(`ctx()`: pc and the running task when attached through emu_i2c.attach).
"""
import collections


class I2cBus:
    def __init__(self, name, log=None, ctx=None):
        self.name = name
        self.log = log or (lambda s: None)
        self.ctx = ctx or (lambda: '')
        self.slaves = {}
        self.cur = None                 # slave of the running transfer
        self.cur_addr = None
        self.missing = collections.Counter()    # (addr, 'r'/'w') -> count of unanswered addressings
        self.missing_first = {}                 # (addr, 'r'/'w') -> context of the first one
        self.transfers = collections.Counter()  # (addr, 'r'/'w') -> count
        self.journal = None             # optional list of finished transfers: (addr, 'r'/'w', bytes, ctx)
        self._bytes = None

    def attach(self, addr7, slave):
        assert 0 <= addr7 < 0x80 and addr7 not in self.slaves, f'{self.name}: address {addr7:#x} taken'
        self.slaves[addr7] = slave
        return slave

    def _close(self):
        if self.journal is not None and self._bytes is not None:
            self.journal.append((self.cur_addr, self._dir, bytes(self._bytes), self._ctx))
        self._bytes = None

    def start(self, addr7, read):
        self._close()
        d = 'r' if read else 'w'
        self.cur_addr = addr7
        self.cur = self.slaves.get(addr7)
        if self.cur is None or not self.cur.start(read):
            k = (addr7, d)
            self.missing[k] += 1
            if k not in self.missing_first:
                self.missing_first[k] = self.ctx()
                self.log(f'[{self.name}] no slave at {addr7:#04x} ({"read" if read else "write"}), not acknowledged; {self.ctx()}')
            self.cur = None
            return False
        self.transfers[(addr7, d)] += 1
        self._bytes = bytearray(); self._dir = d; self._ctx = self.ctx() if self.journal is not None else ''
        return True

    def write(self, byte):
        if self.cur is None:
            return False
        if self._bytes is not None:
            self._bytes.append(byte)
        return bool(self.cur.write(byte))

    def read(self, ack):
        if self.cur is None:
            return 0xFF                 # released bus
        v = self.cur.read(ack) & 0xFF
        if self._bytes is not None:
            self._bytes.append(v)
        return v

    def stop(self):
        self._close()
        if self.cur is not None:
            self.cur.stop()
        self.cur = None

    def summary(self):
        t = ', '.join(f'{a:#04x}{d}:{n}' for (a, d), n in sorted(self.transfers.items())) or 'none'
        u = ', '.join(f'{a:#04x}{d}:{n}' for (a, d), n in sorted(self.missing.items())) or 'none'
        return f'[{self.name}] transfers {t}; unanswered {u}'


class RegisterSlave:
    """Common register-file slave: write = register pointer byte, then data bytes (pointer auto-increments);
    read = bytes from the pointer. Subclasses set `name`, `regs` defaults and override get()/put() for live registers."""
    name = 'regs'
    autoinc = True

    def __init__(self, log=None, defaults=None):
        self.log = log or (lambda s: None)
        self.regs = dict(defaults or {})
        self.ptr = 0
        self._first = False
        self.reads = collections.Counter()      # register -> count
        self.writes = collections.OrderedDict() # register -> list of values written (last 8)
        self.unknown_reads = collections.Counter()

    # ---- register semantics, overridable ----
    def get(self, reg):
        if reg not in self.regs:
            self.unknown_reads[reg] += 1
        return self.regs.get(reg, 0)

    def put(self, reg, value):
        self.regs[reg] = value

    # ---- bus side ----
    def start(self, read):
        self._first = not read
        return True

    def write(self, byte):
        if self._first:
            self.ptr = byte; self._first = False
            return True
        self.writes.setdefault(self.ptr, []).append(byte)
        del self.writes[self.ptr][:-8]
        self.put(self.ptr, byte)
        if self.autoinc:
            self.ptr = (self.ptr + 1) & 0xFF
        return True

    def read(self, ack):
        self.reads[self.ptr] += 1
        v = self.get(self.ptr)
        if self.autoinc:
            self.ptr = (self.ptr + 1) & 0xFF
        return v

    def stop(self):
        pass

    def summary(self):
        r = ' '.join(f'{k:02x}x{n}' for k, n in sorted(self.reads.items()))
        w = ' '.join(f'{k:02x}={",".join("%02x" % x for x in v)}' for k, v in sorted(self.writes.items()))
        return f'[{self.name}] read {r or "-"}; written {w or "-"}'
