"""Keypad matrix controller of the DB3210 application CPU: block 0xC0015000, VIC lines 30 (key pressed) and 31 (all released).

Plain Python, no unicorn import. All registers are accessed as 16-bit halfwords by the driver. Marks:
[V] read in driver code, [I] inferred, [?] unknown.

    +0x00 CTRL  [V] written once at init: (CTRL & 0xfff8) | (a setting & 7), the setting 0. Stored.
    +0x04 COL   [V] read: the driver takes the low 8 bits of (COL | 0xff80), so bits 6:0 are the column inputs,
                ACTIVE LOW (0xff = nothing pressed). Bits 5:0 are decoded into keys, bit 6 only
                takes part in "any key".
    +0x08 ROW   [V] written: (ROW & 0xffe0) | (v & 0x1f): five row outputs, active low (a row is driven when its
                bit is 0). A scan drives rows 0..4 one at a time, then 0x1f = no row driven.
    +0x14       [V] only |= 3 at enable time. [?] meaning (debounce / edge select?). Stored.
    +0x18 IEN   [V] |= 3 at enable time; the press ISR leaves (x & ~3) | 2, the release ISR leaves (x & ~3) | 1.
                [I] bit0 = enable the press interrupt (line 30), bit1 = enable the release interrupt (line 31).

Electrical model [I, consistent with the scan code]: COL bit c reads 0 when a pressed matrix key (r, c) sits on a row that is driven low, or
when a direct key sits on column c (it pulls the column low whatever the rows do; the driver reads COL once with no row driven, ANDs that
into the five row readings as a ghost mask and keeps it as a sixth row: key indexes 30..35). Interrupts, level type: line 30 while
(IEN bit0 and any key is down), line 31 while (IEN bit1 and no key is down). The ISRs only signal a task and move the
enable bit, which is what makes the two lines alternate; the scan itself is in process context.
"""

CTRL, COL, ROW, REG14, IEN = 0x00, 0x04, 0x08, 0x14, 0x18
LINE_BF, LINE_BR = 30, 31
ROWS, COLS = 5, 6                       # matrix 5 x 6, plus the direct row (index 30..35)
NKEYS = 36


class KeypadController:
    name = 'KEYPAD'

    def __init__(self, set_line=None, log=None, ctx=None):
        self.set_line = set_line or (lambda n, level: None)
        self.log = log or (lambda s: None)
        self.ctx = ctx or (lambda: '')
        self.down = set()               # key indexes 0..35 currently held
        self.regs = {CTRL: 0, ROW: 0, REG14: 0, IEN: 0}
        self.levels = {LINE_BF: False, LINE_BR: False}
        self.scans = 0                  # COL reads
        self.irq_edges = {LINE_BF: 0, LINE_BR: 0}
        self.trace = None               # optional list of (kind, offset, value)
        self.on_edge = None             # optional callback(line, level)

    # ---- electrical state ----
    def columns(self):
        """The 7 column inputs for the current ROW output, active low."""
        row = self.regs[ROW] & 0x1F
        v = 0x7F
        for k in self.down:
            r, c = divmod(k, COLS)
            if r >= ROWS or not row & (1 << r):         # direct key, or a matrix row that is driven low
                v &= ~(1 << c)
        return v

    def any_down(self):
        return bool(self.down)

    def press(self, index):
        self.down.add(index); self._update()

    def release(self, index):
        self.down.discard(index); self._update()

    def _update(self):
        ien = self.regs[IEN]
        want = {LINE_BF: bool(ien & 1) and self.any_down(), LINE_BR: bool(ien & 2) and not self.any_down()}
        for line, level in want.items():
            if level != self.levels[line]:
                self.levels[line] = level
                if level:
                    self.irq_edges[line] += 1
                self.set_line(line, level)
                if self.on_edge:
                    self.on_edge(line, level)

    # ---- bus ----
    def read(self, off, size):
        if off == COL:
            self.scans += 1
            v = self.columns()
        else:
            v = self.regs.get(off, 0)
        if self.trace is not None:
            self.trace.append(('R', off, v))
        return v

    def write(self, off, size, v):
        if self.trace is not None:
            self.trace.append(('W', off, v))
        v &= 0xFFFF
        if off in (CTRL, ROW, REG14, IEN):
            self.regs[off] = v
        if off == IEN:
            self._update()

    def summary(self):
        return ('[keypad] down %s, COL reads %d, IEN %#x, ROW %#x, IRQ rises BF %d BR %d'
                % (sorted(self.down) or '-', self.scans, self.regs[IEN], self.regs[ROW], self.irq_edges[LINE_BF], self.irq_edges[LINE_BR]))
