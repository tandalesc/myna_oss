"""DMA controller at 0xC0020000 (register layout is NOT a PL080).
No unicorn import. Layout, derived from the drivers of both CPUs:

  0x008/0x00c  TC status, channels 0-31 / 32-63 (read only, terminal count of the whole chain)
  0x010/0x014  TC clear (write 1)
  0x028/0x02c  error clear, 0x030/0x034 error status
  0x100+4n     channel config: bit0 start/enable, bits[2:1] type (0 mem->mem, 1 mem->periph, 2 periph->mem, 3 periph->periph)
               A type 1 / 2 / 3 channel moves data only when its peripheral asks: with no port attached at the peripheral's
               address the channel stays busy and nothing is copied (seen: the APEX block, channel 19 from 0xC003A7FC, 20 to 0xC003A000).
  0x200+4n     channel status: bit0 busy, bit1 stop pending
  0x400+16n    first descriptor: +0 control (bits[11:0] byte count, bit26 increment, bits 24+25 both set = last item of a message on a tx port), +4 source, +8 destination,
               +12 next descriptor address (0 = last). Memory descriptors have the same four words.

Peripherals attach with attach_port(address, port); a port offers dma_space() / dma_avail() / write_bytes()
/ read_bytes(). attach_mem(base, size, dev) makes a device's memory / registers reachable for memory-to-memory items. Transfers run synchronously inside write()/poke(); nothing depends on time.
"""
import operator
import struct

NCH = 64
_TC = operator.attrgetter('tc')


class _Chan:
    __slots__ = ('cfg', 'ctrl', 'src', 'dst', 'nxt', 'active', 'tc', 'items', 'bytes')

    def __init__(self):
        self.cfg = self.ctrl = self.src = self.dst = self.nxt = 0
        self.active = False
        self.tc = False
        self.items = 0
        self.bytes = 0


class Dmac:
    def __init__(self, read_mem, write_mem, set_line=None, line=0, name='dmac'):
        self.read_mem, self.write_mem = read_mem, write_mem
        self.set_line = set_line or (lambda n, lvl: None)
        self.line = line
        self.name = name
        self.ch = [_Chan() for _ in range(NCH)]
        self.ports = {}
        self.windows = []                # (base, size, device) for memory-to-memory items inside a device (attach_mem)
        self.err = 0
        self.r000 = 0
        self._level = False
        self._running = False
        self._again = False
        self.runaway = set()             # channels whose descriptor chain was cut off once (logged once each)
        self.no_request = {}             # channel -> unmodelled peripheral address it waits on (type 1 / 2 / 3 channels)
        self.on_unmodelled = None        # optional callback(channel, peripheral address, control, source, destination), once per channel and address
        self.unbacked = set()            # (channel, 'read' | 'write', address) of memory-to-memory items outside memory
        self.log = None
        self.completed = []            # (channel, total bytes) in completion order, for tests

    def attach_port(self, addr, port):
        self.ports[addr] = port

    def attach_mem(self, base, size, dev):
        """Device memory or registers that memory-to-memory items may address: dev.dma_read(offset, n) -> bytes, dev.dma_write(offset, data)."""
        self.windows.append((base, size, dev))

    # ---- register access ----------------------------------------------------------------------
    def read(self, off, size):
        if off == 0x000: return self.r000
        if off in (0x008, 0x00c):
            base = 0 if off == 0x008 else 32
            return sum(1 << i for i in range(32) if self.ch[base + i].tc)
        if off in (0x030, 0x034):
            return (self.err >> (0 if off == 0x030 else 32)) & 0xFFFFFFFF
        if 0x100 <= off < 0x100 + 4 * NCH:
            return self.ch[(off - 0x100) >> 2].cfg
        if 0x200 <= off < 0x200 + 4 * NCH:
            c = self.ch[(off - 0x200) >> 2]
            return 1 if c.active else 0
        if 0x400 <= off < 0x400 + 16 * NCH:
            c = self.ch[(off - 0x400) >> 4]
            return (c.ctrl, c.src, c.dst, c.nxt)[((off - 0x400) >> 2) & 3]
        return 0

    def write(self, off, size, v):
        if off == 0x000:
            self.r000 = v
        elif off in (0x010, 0x014):
            base = 0 if off == 0x010 else 32
            for i in range(32):
                if v >> i & 1: self.ch[base + i].tc = False
        elif off in (0x028, 0x02c):
            self.err &= ~((v & 0xFFFFFFFF) << (0 if off == 0x028 else 32))
        elif 0x100 <= off < 0x100 + 4 * NCH:
            c = self.ch[(off - 0x100) >> 2]
            was = c.cfg & 1
            c.cfg = v
            if v & 1 and not was:
                c.active, c.tc = True, False
                c.items, c.bytes = 0, 0
                self._note(f'start ch{(off - 0x100) >> 2} cfg={v:#x} ctrl={c.ctrl:#x} src={c.src:#x} dst={c.dst:#x} next={c.nxt:#x}')
            elif not v & 1 and was:
                c.active = False
        elif 0x400 <= off < 0x400 + 16 * NCH:
            c = self.ch[(off - 0x400) >> 4]
            w = ((off - 0x400) >> 2) & 3
            if w == 0: c.ctrl = v
            elif w == 1: c.src = v
            elif w == 2: c.dst = v
            else: c.nxt = v
        self.poke()

    def _note(self, s):
        if self.log: self.log(f'[{self.name}] {s}')

    # ---- engine -------------------------------------------------------------------------------
    def poke(self):
        if self._running:
            self._again = True
            return
        self._running = True
        try:
            while True:
                self._again = False
                progress = False
                for n, c in enumerate(self.ch):
                    if c.active and self._run(n, c):
                        progress = True
                if not (progress or self._again):
                    break
        finally:
            self._running = False
        self._update_irq()

    def _run(self, n, c):
        moved_any = False
        typ = (c.cfg >> 1) & 3
        steps = 0
        while c.active:
            steps += 1
            if steps > 4096:             # a circular descriptor chain with no rate-limited port (e.g. audio with no I2S model):
                if n not in self.runaway:                  # never spin inside one device callback; carry on at the next poke
                    self.runaway.add(n)
                    self._note(f'ch{n}: descriptor chain did not end after {steps - 1} steps (circular list, unmodelled peripheral?)')
                return False             # not 'progress': poke() would call straight back in
            count = c.ctrl & 0xFFF
            if count == 0:
                if c.nxt:
                    raw = self.read_mem(c.nxt, 16)
                    c.ctrl, c.src, c.dst, c.nxt = struct.unpack('<4I', raw)
                    c.items += 1
                    moved_any = True
                    continue
                c.active, c.tc = False, True
                c.cfg &= ~1
                self.completed.append((n, c.bytes))
                self._note(f'tc ch{n} bytes={c.bytes} items={c.items + 1}')
                return True
            sp, dp = self.ports.get(c.src), self.ports.get(c.dst)
            if sp is not None and dp is not None:
                return moved_any
            if (sp is None and typ & 2) or (dp is None and typ & 1):
                # a peripheral channel moves data only on its peripheral's request. Nothing modelled at that address = no request
                # ever: the channel stays busy with its count untouched (the address is a FIFO register, never memory to copy)
                side = c.src if sp is None and typ & 2 else c.dst
                if self.no_request.get(n) != side:
                    self.no_request[n] = side
                    self._note(f'ch{n}: peripheral {side:#x} is not modelled: channel waits (cfg={c.cfg:#x} ctrl={c.ctrl:#x} src={c.src:#x} dst={c.dst:#x})')
                    if self.on_unmodelled: self.on_unmodelled(n, side, c.ctrl, c.src, c.dst)
                return moved_any
            if sp is not None:
                k = min(count, sp.dma_avail())
                if k and k >= 4: k &= ~3
                if k <= 0: return moved_any
                data = sp.read_bytes(k)
                self.write_mem(c.dst, data)
                c.dst += len(data)
                k = len(data)
            elif dp is not None:
                k = min(count, dp.dma_space())
                if k and k >= 4: k &= ~3
                if k <= 0: return moved_any
                data = self.read_mem(c.src, k)
                dp.write_bytes(data)
                c.src += k
            else:                        # memory to memory. Either end may be inside a device (the APEX block's work memory
                data = self._mm_read(n, c.src, count)      # and registers are loaded this way, channel 36 -> 0xC0038000 / 0xC003A030..)
                self._mm_write(n, c.dst, data)
                c.src += count
                c.dst += count
                k = count
            c.ctrl = (c.ctrl & ~0xFFF) | (count - k)
            c.bytes += k
            moved_any = True
            if dp is not None and c.ctrl & 0xFFF == 0 and (c.ctrl >> 24) & 3 == 3 and hasattr(dp, 'end_message'):
                dp.end_message()         # bits 24+25 both set: the firmware sets them only on the last tx item of a frame (inferred end of message)
        return moved_any

    def _window(self, addr, count):
        for base, size, dev in self.windows:
            if base <= addr and addr + count <= base + size:
                return base, dev
        return None

    def _mm_read(self, n, addr, count):
        """Source of a memory-to-memory item: a device window (attach_mem), else memory; an address nothing backs reads as zeros."""
        w = self._window(addr, count)
        if w: return bytes(w[1].dma_read(addr - w[0], count))
        try:
            return self.read_mem(addr, count)
        except Exception:
            self._unbacked(n, 'read', addr, count)
            return bytes(count)

    def _mm_write(self, n, addr, data):
        """Destination of a memory-to-memory item; a write nothing backs is dropped, like a bus write to an unclaimed address."""
        w = self._window(addr, len(data))
        if w: w[1].dma_write(addr - w[0], data); return
        try:
            self.write_mem(addr, data)
        except Exception:
            self._unbacked(n, 'write', addr, len(data))

    def _unbacked(self, n, what, addr, count):
        if (n, what, addr) not in self.unbacked:
            self.unbacked.add((n, what, addr))
            self._note(f'ch{n}: memory-to-memory {what} of {count} bytes at {addr:#x}: no memory there (device register?), ignored')

    def _update_irq(self):
        lvl = any(map(_TC, self.ch)) or bool(self.err)      # (the 64 flags without a generator: this runs after every register write)
        if lvl != self._level:
            self._level = lvl
            self.set_line(self.line, lvl)
