"""Device bus: maps address ranges to plain-Python device models. No Unicorn import.

A device is any object with read(offset, size) -> int and write(offset, size, value).
Optional: `name` attribute, `reset()`.
"""
import collections


class Bus:
    def __init__(self, log=None):
        self.ranges = []                   # (base, end, dev, name)
        self.touched = collections.OrderedDict()   # addr -> [first_pc, 'r'/'w'/'rw', count, last_value, handled]
        self._seen = set()
        self._cache = {}
        self.nread = self.nwrite = 0               # access counts, used by Machine's polling-loop detector
        self.log = log or (lambda s: None)

    def attach(self, base, size, dev, name=None):
        name = name or getattr(dev, 'name', type(dev).__name__)
        self.ranges.append((base, base + size, dev, name))
        self.ranges.sort(key=lambda r: r[0])
        self._cache.clear()
        return dev

    def find(self, addr):
        hit = self._cache.get(addr >> 12)
        if hit is not None:
            b, e, d = hit
            if b <= addr < e:
                return b, d, None
        for b, e, d, n in self.ranges:
            if b <= addr < e:
                if b <= (addr & ~0xFFF) and e > (addr | 0xFFF):      # range covers the whole page: safe to cache
                    self._cache[addr >> 12] = (b, e, d)
                return b, d, n
        return None

    def set_accounting(self, on):
        """False: drop the per-address `touched` bookkeeping and unhandled-access logging (watch mode); counters stay."""
        if on:
            self.__dict__.pop('read', None); self.__dict__.pop('write', None)
        else:
            self.read, self.write = self._read_lean, self._write_lean

    def _read_lean(self, addr, size, pc):
        self.nread += 1
        hit = self._cache.get(addr >> 12)
        if hit is not None and hit[0] <= addr < hit[1]:
            return hit[2].read(addr - hit[0], size) & ((1 << (8 * size)) - 1)
        hit = self.find(addr)
        return 0 if hit is None else hit[1].read(addr - hit[0], size) & ((1 << (8 * size)) - 1)

    def _write_lean(self, addr, size, value, pc):
        self.nwrite += 1
        hit = self._cache.get(addr >> 12)
        if hit is not None and hit[0] <= addr < hit[1]:
            hit[2].write(addr - hit[0], size, value); return
        hit = self.find(addr)
        if hit is not None:
            hit[1].write(addr - hit[0], size, value)

    def _note(self, addr, kind, pc, value, handled):
        t = self.touched.get(addr)
        if t is None:
            self.touched[addr] = [pc, kind, 1, value, handled]
        else:
            if kind not in t[1]:
                t[1] += kind
            t[2] += 1
            t[3] = value
        if not handled:
            key = (pc, addr, kind)
            if key not in self._seen:
                self._seen.add(key)
                self.log(f'[hw] unhandled {"read " if kind == "r" else "write"} {addr:#010x}'
                         + ('' if kind == 'r' else f' = {value:#x}') + f' from pc {pc:#x}')

    # pc is a callable: the CPU is only asked where it is for a first touch or an unhandled access
    def read(self, addr, size, pc):
        self.nread += 1
        hit = self.find(addr)
        if hit is None:
            self._note(addr, 'r', pc(), 0, False)
            return 0
        v = hit[1].read(addr - hit[0], size) & ((1 << (8 * size)) - 1)
        t = self.touched.get(addr)
        if t is None:
            self.touched[addr] = [pc(), 'r', 1, v, True]
        else:
            if t[1] != 'r' and 'r' not in t[1]:
                t[1] += 'r'
            t[2] += 1; t[3] = v
        return v

    def write(self, addr, size, value, pc):
        self.nwrite += 1
        hit = self.find(addr)
        if hit is None:
            self._note(addr, 'w', pc(), value, False)
            return
        t = self.touched.get(addr)
        if t is None:
            self.touched[addr] = [pc(), 'w', 1, value, True]
        else:
            if 'w' not in t[1]:
                t[1] += 'w'
            t[2] += 1; t[3] = value
        hit[1].write(addr - hit[0], size, value)
