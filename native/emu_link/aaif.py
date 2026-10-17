"""AAIF: model of the CPU-to-CPU link block (0xC0022000 on both CPUs). No unicorn import.

 What the model implements:

  TX channel c (0..7)  base 0x000 + 0x40*c      RX channel c (0..7)  base 0x200 + 0x40*c
    +0x00 CTRL    bit0 enable, bit1 DMA request enable, bit2 (stored), bits 8..13 threshold, 16..23 depth-1
    +0x04 STATUS  tx: bit2 empty, bit3 space, bit4 full, bit6 done (write 1 to clear)
                  rx: bit2 empty (of current message), bit3 data, bit6 end-of-message (write 1 to clear)
    +0x08 LEVEL   bytes in FIFO (rx: readable bytes, 7 bits)
    +0x0c IRQEN   bit3 FIFO event, bit6 done / end-of-message
    +0x10 CMD     tx: bit0 commit (end of message), self-clearing
    +0x20 DATA    FIFO port, 1/2/4 byte accesses, little endian (also the DMA port)
  0x400 MODE, 0x404 (bit0 = link asleep: data on rx0 also raises the wake line),
  0x408, 0x410 stored, 0x500 channel IRQ enable set (tx bit c, rx bit 8+c), 0x504 channel IRQ enable clear.
  Writing bit0 of TX channel 7's CTRL (0x1c0) is the wake kick towards the peer.

Data written to TX channel c of one side appears in RX channel c of the other side (FIFO of 64 bytes each,
back-pressure into the TX FIFO when the peer's RX is disabled or full). Delivery is immediate (no timing).
"""
from collections import deque

FIFO_CAP = 64
NCH = 8
ST_EMPTY, ST_SPACE_OR_DATA, ST_FULL, ST_DONE = 0x04, 0x08, 0x10, 0x40


class _Tx:
    def __init__(self):
        self.ctrl = 0
        self.irqen = 0
        self.fifo = bytearray()
        self.pushed = 0            # absolute counters for commit boundaries
        self.moved = 0
        self.commits = deque()
        self.done = False
        self.cmd_pending = False


class _Rx:
    def __init__(self):
        self.ctrl = 0
        self.irqen = 0
        self.cmd = 0
        self.fifo = bytearray()
        self.total_in = 0
        self.total_out = 0
        self.bnd = deque()         # absolute end positions of completed messages

    def level(self):
        return len(self.fifo)

    def eom(self):
        """End-of-message latch: the oldest committed message has been read completely (cleared by software)."""
        return bool(self.bnd) and self.total_out >= self.bnd[0]


class _Port:
    """DMA view of one FIFO port (for Dmac.attach_port)."""

    def __init__(self, side, kind, ch):
        self.side, self.kind, self.ch = side, kind, ch

    def dma_space(self):
        s = self.side
        if self.kind != 'tx':
            return 0
        t = s.tx[self.ch]
        if not (t.ctrl & 1 and t.ctrl & 2):
            return 0
        return FIFO_CAP - len(t.fifo)

    def dma_avail(self):
        s = self.side
        if self.kind != 'rx':
            return 0
        r = s.rx[self.ch]
        if not (r.ctrl & 1 and r.ctrl & 2):
            return 0
        return r.level()

    def write_bytes(self, data):
        self.side._tx_push(self.ch, data)

    def end_message(self):
        self.side._chan_write('tx', self.ch, 0x10, 4, 1)

    def read_bytes(self, n):
        return self.side._rx_pop(self.ch, n)


class AaifSide:
    """One CPU's view of the block. read/write(offset, size[, value]) are relative to the block base."""

    def __init__(self, link, idx, lines, set_line, name):
        self.link, self.idx, self.name = link, idx, name
        self.lines = lines              # (rx, tx, wake) interrupt line numbers on this CPU
        self.set_line = set_line or (lambda n, lvl: None)
        self.tx = [_Tx() for _ in range(NCH)]
        self.rx = [_Rx() for _ in range(NCH)]
        self.mode = self.mask = self.r408 = self.r410 = 0
        self.chan_en = 0                # bit c tx, bit 8+c rx
        self.kick = False
        self.level = [False, False, False]
        self.dmac = None
        self.peer = None
        self.log = None                 # optional callable(str)
        self.stats = {'rx_bytes': 0, 'tx_bytes': 0, 'kicks_sent': 0, 'overrun': 0}

    # ---- wiring -------------------------------------------------------------------------------
    def connect_dma(self, dmac, base=0xC0022000):
        """Register the FIFO data ports with a DMA controller and let it be poked on state changes."""
        self.dmac = dmac
        for c in range(NCH):
            dmac.attach_port(base + 0x20 + 0x40 * c, _Port(self, 'tx', c))
            dmac.attach_port(base + 0x220 + 0x40 * c, _Port(self, 'rx', c))

    # ---- register access ----------------------------------------------------------------------
    def read(self, off, size):
        if off < 0x400:
            kind = 'tx' if off < 0x200 else 'rx'
            c, r = ((off & 0x1ff) >> 6), off & 0x3f
            return self._chan_read(kind, c, r, size)
        if off == 0x400: return self.mode
        if off == 0x404: return self.mask
        if off == 0x408: return self.r408
        if off == 0x410: return self.r410
        if off == 0x500: return self.chan_en
        return 0

    def write(self, off, size, v):
        if off < 0x400:
            kind = 'tx' if off < 0x200 else 'rx'
            c, r = ((off & 0x1ff) >> 6), off & 0x3f
            self._chan_write(kind, c, r, size, v)
        elif off == 0x400: self.mode = v
        elif off == 0x404: self.mask = v
        elif off == 0x408: self.r408 = v
        elif off == 0x410: self.r410 = v
        elif off == 0x500: self.chan_en |= v & 0x7f7f
        elif off == 0x504:
            self.chan_en &= ~v & 0x7f7f
            if v & 0x100:
                self.kick = False
        self.link.settle()

    def _chan_read(self, kind, c, r, size):
        if kind == 'tx':
            t = self.tx[c]
            if r == 0x00: return t.ctrl
            if r == 0x04:
                n = len(t.fifo)
                return ((ST_EMPTY if n == 0 else 0) | (ST_SPACE_OR_DATA if n < FIFO_CAP else 0)
                        | (ST_FULL if n >= FIFO_CAP else 0) | (ST_DONE if t.done else 0))
            if r == 0x08: return len(t.fifo)
            if r == 0x0c: return t.irqen
            if r == 0x10: return 1 if t.cmd_pending else 0
            return 0
        x = self.rx[c]
        if r == 0x00: return x.ctrl
        if r == 0x04:
            lv = x.level()
            return ((ST_EMPTY if lv == 0 else 0) | (ST_SPACE_OR_DATA if lv else 0) | (ST_DONE if x.eom() else 0))
        if r == 0x08: return min(x.level(), 0x7f)
        if r == 0x0c: return x.irqen
        if r == 0x10: return x.cmd
        if r == 0x20:
            data = self._rx_pop(c, size)
            return int.from_bytes(data.ljust(size, b'\0'), 'little')
        return 0

    def _chan_write(self, kind, c, r, size, v):
        if kind == 'tx':
            t = self.tx[c]
            if r == 0x00:
                t.ctrl = v
                if c == 7 and v & 1:
                    self.stats['kicks_sent'] += 1
                    self.peer.kick = True
                    self._note(f'wake kick sent (ctrl7={v:#x})')
            elif r == 0x04:
                if v & ST_DONE: t.done = False
            elif r == 0x0c: t.irqen = v
            elif r == 0x10:
                if v & 1:
                    t.commits.append(t.pushed)
                    t.cmd_pending = True
                    self.link._pump_side(self)
            elif r == 0x20:
                self._tx_push(c, (v & ((1 << (8 * size)) - 1)).to_bytes(size, 'little'))
            return
        x = self.rx[c]
        if r == 0x00: x.ctrl = v
        elif r == 0x04:
            if v & ST_DONE and x.eom(): x.bnd.popleft()
        elif r == 0x0c: x.irqen = v
        elif r == 0x10: x.cmd = v

    # ---- data movement ------------------------------------------------------------------------
    def _tx_push(self, c, data):
        t = self.tx[c]
        if not (t.ctrl & 1):
            self.stats['overrun'] += len(data)
            return
        room = FIFO_CAP - len(t.fifo)
        if len(data) > room:
            self.stats['overrun'] += len(data) - room
            data = data[:room]
        t.fifo += data
        t.pushed += len(data)
        self.stats['tx_bytes'] += len(data)
        self._note(f'tx ch{c} +{bytes(data).hex()}')
        self.link._pump_side(self)

    def _rx_pop(self, c, n):
        x = self.rx[c]
        n = min(n, x.level())
        data = bytes(x.fifo[:n])
        del x.fifo[:n]
        x.total_out += n
        if n:
            self._note(f'rx ch{c} -{data.hex()}')
        if c == 0 and not x.fifo:
            self.kick = False
        self.link._pump_peer_of(self)
        return data

    def _note(self, s):
        self.link.trace.append((self.name, s))
        if self.log: self.log(f'[aaif {self.name}] {s}')

    # ---- interrupts ---------------------------------------------------------------------------
    def compute_lines(self):
        rx_pend = tx_pend = False
        for c in range(NCH):
            x = self.rx[c]
            if self.chan_en >> (8 + c) & 1:
                if (x.irqen & 8 and x.level() > 0) or (x.irqen & 0x40 and x.eom()):
                    rx_pend = True
            t = self.tx[c]
            if self.chan_en >> c & 1:
                if (t.irqen & 8 and len(t.fifo) < FIFO_CAP) or (t.irqen & 0x40 and t.done):
                    tx_pend = True
        # 0x404 bit0 is set by the link manager while the link is "asleep"; the wake line is the
        # peer's explicit kick or, while asleep, any data on rx0. The rx line does not depend on it (inferred).
        wake_line = self.kick or (bool(self.mask & 1) and self.rx[0].level() > 0)
        return [rx_pend, tx_pend, wake_line]

    def update_irq(self):
        new = self.compute_lines()
        for i in range(3):
            if new[i] != self.level[i]:
                self.level[i] = new[i]
                self.set_line(self.lines[i], new[i])


class AaifLink:
    def __init__(self, lines_a=(5, 6, 8), lines_b=(34, 35, 36), set_line_a=None, set_line_b=None):
        self.trace = []
        self.a = AaifSide(self, 0, lines_a, set_line_a, 'A')
        self.b = AaifSide(self, 1, lines_b, set_line_b, 'B')
        self.a.peer, self.b.peer = self.b, self.a
        self._busy = False
        self._again = False

    def _pump_side(self, s):
        self.settle()

    def _pump_peer_of(self, s):
        self.settle()

    def settle(self):
        """Move bytes TX -> peer RX until nothing changes, poke DMA controllers, refresh interrupt lines."""
        if self._busy:
            self._again = True
            return
        self._busy = True
        try:
            while True:
                self._again = False
                moved = self._pump(self.a, self.b) | self._pump(self.b, self.a)
                for s in (self.a, self.b):
                    if s.dmac is not None:
                        s.dmac.poke()
                if not (moved or self._again):
                    break
            self.a.update_irq()
            self.b.update_irq()
        finally:
            self._busy = False

    @staticmethod
    def _pump(src, dst):
        moved = False
        for c in range(NCH):
            t, r = src.tx[c], dst.rx[c]
            if not (r.ctrl & 1):
                continue
            while t.fifo and len(r.fifo) < FIFO_CAP:
                n = min(len(t.fifo), FIFO_CAP - len(r.fifo))
                if t.commits:
                    n = min(n, t.commits[0] - t.moved) if t.commits[0] > t.moved else n
                r.fifo += t.fifo[:n]
                r.total_in += n
                del t.fifo[:n]
                t.moved += n
                src.stats['rx_bytes'] += 0
                dst.stats['rx_bytes'] += n
                moved = True
                if t.commits and t.moved >= t.commits[0]:
                    t.commits.popleft()
                    r.bnd.append(r.total_in)
                    t.done = True
                    t.cmd_pending = bool(t.commits)
            # empty committed messages (commit with nothing in the FIFO)
            while t.commits and t.commits[0] <= t.moved and not t.fifo:
                t.commits.popleft()
                r.bnd.append(r.total_in)
                t.done = True
                t.cmd_pending = bool(t.commits)
                moved = True
        return moved
