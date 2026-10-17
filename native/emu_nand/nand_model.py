"""NAND flash controller + chip model for the DB3210 phones (U300-style NAND interface).

Plain Python register state machine, no Unicorn import.  Two bus windows, each a class with
read(offset, size) -> int and write(offset, size, value):

    NandBus   base 0x80000000, size 0x30000
              +0x00000  data port   (any address below 0x10000 reads/writes the next byte(s) of the data stream)
              +0x10000  CLE         (write a command byte)
              +0x20000  ALE         (write an address byte)
    NandCtrl  base 0x9F800000, size 0x1000
              +0x40 control (bit6 = ECC engine enable, bits7:6 cleared then bit6 set = ECC reset)
              +0x44 status  (bit6 = ECC/FIFO done, always set here)
              +0x48,+0x4C timing (stored only)
              +0x54 hardware ECC accumulator (24 bit, see below)
              +0xC8 bit1 = chip ready (R/B# line)

Every item was read in driver code.

The chip is a 2 Gbit x8 large page device (2048+64 byte pages, 64 pages/block, 131072 pages, 3 row address
cycles; ID EC AA 10 15 44 = Samsung K9K2G08R0A / ST NAND02GR3B).
A driver may read two ID bytes and take the size from the device byte, or read five: page, block and spare size from the
4th, and the size as planes (5th bits 3:2) x plane size (5th bits 6:4, code 4 = 128 MB). With 0x44 = 2 planes of 1 Gbit
both get the same 256 MB; a 5th byte of 0 gives a 64 KB device.  Backing store is a flat whole-chip image (0x840 bytes per page) opened
read-only (an empty image, bytes(), is a blank chip: every page reads as erased); programs and erases go to an in-memory copy-on-write overlay (optionally persisted with
save_overlay()/load_overlay()).
"""
import functools
import mmap
import operator
import os
import struct

PAGE_DATA = 0x800
PAGE_SPARE = 0x40
PAGE_RAW = PAGE_DATA + PAGE_SPARE
PAGES_PER_BLOCK = 64

BUS_BASE, BUS_SIZE = 0x80000000, 0x30000
CTRL_BASE, CTRL_SIZE = 0x9F800000, 0x1000
OFF_CLE, OFF_ALE = 0x10000, 0x20000

R_CTRL, R_STATUS, R_TIM0, R_TIM1, R_ECC, R_READY = 0x40, 0x44, 0x48, 0x4C, 0x54, 0xC8

# Chip personalities: (manufacturer id, device id, 3rd, 4th and, where known, 5th id byte; pages; has ST unique-id command)
CHIPS = {
    'samsung_k9k2g08r0a': dict(ids=(0xEC, 0xAA, 0x10, 0x15, 0x44), pages=131072, st_uid=False),   # 2 Gbit, 1.8 V (default)
    'st_nand02gr3b':      dict(ids=(0x20, 0xAA, 0x10, 0x15, 0x44), pages=131072, st_uid=False),
    'samsung_k9k2g08u0a': dict(ids=(0xEC, 0xDA, 0x10, 0x95, 0x44), pages=131072, st_uid=False),   # 3.3 V
    'samsung_k9f1g08r0a': dict(ids=(0xEC, 0xA1, 0x00, 0x15), pages=65536, st_uid=False),
    'st_nand01gr3b':      dict(ids=(0x20, 0xA1, 0x00, 0x15), pages=65536, st_uid=True),
    'samsung_k9f1g08u0a': dict(ids=(0xEC, 0xF1, 0x00, 0x95), pages=65536, st_uid=False),
}
DEFAULT_CHIP = 'samsung_k9k2g08r0a'     # the chip of the stock flash images; a device with BOOT_ELF names its own in NAND_CHIP
ST_UNIQUE_ID = bytes(range(0xA0, 0xB0))


def _par(x):
    return bin(x).count('1') & 1


# Per-byte parity helpers for the 512-byte Hamming ECC (see EccEngine).
_PAR = [_par(i) for i in range(256)]
_CP_MASK1 = [sum(1 << j for j in range(8) if (j >> k) & 1) for k in range(3)]
_PARTBL = bytes(_PAR)
_ROWMASK = [sum(1 << 8 * i for i in range(512) if (i >> k) & 1) for k in range(9)]      # bit 0 of lane i set when index bit k is set


class EccEngine:
    """24-bit Hamming ECC over 512 bytes, as computed by the hardware and as stored in the spare area.

    fn[0..17] row parities: fn[2k] = parity of all bytes whose index bit k is 0, fn[2k+1] = bit k is 1
    (k = 0..8); fn[18..23] column parities: fn[18+2k] = parity of the bits of each byte whose bit-index
    bit k is 0, fn[19+2k] = bit k is 1 (k = 0..2).  Register 0x54 = (~fn) & 0xFFFFFF, bit i = fn[i].
    The software side turns that into stored = 0xC0000000 | fn (little-endian u32 in the spare area).
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._idx = 0
        self._rp = [0] * 18
        self._cp = [0] * 6
        self._pend = bytearray()      # bytes fed but not yet folded in: the parities are only needed when register 0x54 is read

    def feed(self, b):
        self._pend.append(b)

    def feed_bytes(self, data):
        self._pend += data

    def _flush(self):
        pend = self._pend
        if not pend:
            return
        data, self._pend = bytes(pend), bytearray()
        pos = 0
        while pos < len(data):                       # one window per 512 bytes: row parities depend on the index within the sector
            o = self._idx & 511
            chunk = data[pos:pos + 512 - o]; n = len(chunk)
            P = int.from_bytes(chunk.translate(_PARTBL), 'little')
            T = P.bit_count() & 1
            lanes = (1 << 8 * n) - 1
            for k in range(9):
                odd = ((_ROWMASK[k] >> 8 * o) & lanes & P).bit_count() & 1
                self._rp[2 * k + 1] ^= odd
                self._rp[2 * k] ^= T ^ odd
            X = functools.reduce(operator.xor, chunk)
            for k in range(3):
                m1 = _CP_MASK1[k]
                self._cp[2 * k + 1] ^= _PAR[X & m1]
                self._cp[2 * k] ^= _PAR[X & (0xFF ^ m1)]
            self._idx += n; pos += n

    @property
    def idx(self):
        self._flush(); return self._idx

    @property
    def rp(self):
        self._flush(); return self._rp

    @property
    def cp(self):
        self._flush(); return self._cp

    def fn_bits(self):
        v = 0
        for i, b in enumerate(self.rp + self.cp):
            v |= b << i
        return v

    def reg(self):
        return (~self.fn_bits()) & 0xFFFFFF

    @staticmethod
    def stored_word(sector512):
        e = EccEngine()
        for b in sector512:
            e.feed(b)
        return 0xC0000000 | e.fn_bits()


class NandChip:
    """Command/address/data state machine of the NAND device itself."""

    def __init__(self, image_path, chip=DEFAULT_CHIP, overlay=None):
        cfg = CHIPS[chip]
        self.chip = chip
        self.ids = cfg['ids']
        self.pages = cfg['pages']
        self.st_uid = cfg['st_uid']
        if isinstance(image_path, (bytes, bytearray, memoryview)):      # the image itself, in memory, instead of a file
            self.f, self.mm = None, image_path
        else:
            self.f = open(image_path, 'rb')
            self.mm = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        self.img_pages = len(self.mm) // PAGE_RAW      # pages beyond the file read as erased (0xFF)
        self.overlay = overlay if overlay is not None else {}   # page -> bytearray(0x840)
        self.cmd_log = []          # (cmd, addr bytes) of completed commands, for tests
        self._c = None             # port structure that holds `busy` and queued address cycles (NandSystem.use_port_state)
        self._busy = 0
        self._addr = []
        self.reset_state()

    # `busy` and `addr` live in the native port structure while one is attached, so that its compiled callbacks can serve ready
    # polls and address cycles (emu/native_port.py reg_ctrl_r, reg_ale_w); the model reads and writes them through these.
    @property
    def busy(self):
        c = self._c
        return self._busy if c is None else c.busy

    @busy.setter
    def busy(self, n):
        if self._c is None: self._busy = n
        else: self._c.busy = n

    @property
    def addr(self):
        c = self._c
        if c is not None and c.npend:              # address cycles taken by the compiled callback, in order
            self._addr.extend(c.pend[:c.npend]); c.npend = 0
        return self._addr

    @addr.setter
    def addr(self, v):
        if self._c is not None: self._c.npend = 0
        self._addr = v

    def _ale_state(self):
        """Address cycles may be queued natively unless they do more than append (write_addr during a program set-up)."""
        if self._c is not None:
            self._c.ale_ok = self.cmd not in (0x80, 0x85)

    # --- backing store ------------------------------------------------------------------------
    def page_bytes(self, page):
        ov = self.overlay.get(page)
        if ov is not None:
            return ov
        if page >= self.img_pages:
            return bytearray(b'\xff' * PAGE_RAW)
        return bytearray(self.mm[page * PAGE_RAW:(page + 1) * PAGE_RAW])

    def save_overlay(self, path):
        with open(path, 'wb') as f:
            for p in sorted(self.overlay):
                f.write(struct.pack('<I', p) + bytes(self.overlay[p]))

    def load_overlay(self, path):
        with open(path, 'rb') as f:
            while True:
                h = f.read(4)
                if not h:
                    break
                self.overlay[struct.unpack('<I', h)[0]] = bytearray(f.read(PAGE_RAW))

    # --- state --------------------------------------------------------------------------------
    def reset_state(self):
        self.mode = 'idle'         # idle | id | read | status | uid | prog
        self.cmd = None
        self.addr = []
        self.buf = bytearray(PAGE_RAW)     # page register
        self.pos = 0
        self.prog_page = None
        self.prog_pos = 0
        self.status = 0xC0         # bit7 not write protected, bit6 ready, bit0 pass
        self.busy = 0              # number of R/B# polls that still read busy
        self.cb_page = None        # copy-back source page register valid
        self.buf_valid = False
        self.last_row = None
        self.st_seq = []
        self.fail_next = False     # test hook: make the next program/erase report failure

    def ready(self):
        """Value of the R/B# line for one poll (consumes busy time)."""
        if self.busy:
            self.busy -= 1
            return False
        return True

    def start_busy(self, n=3):
        self.busy = n

    def _parse_addr(self):
        a = self.addr
        col = (a[0] | (a[1] << 8)) & 0xFFF if len(a) >= 2 else 0
        row = 0
        for i, b in enumerate(a[2:]):
            row |= b << (8 * i)
        return col, row

    # --- bus cycles ---------------------------------------------------------------------------
    def write_cmd(self, c):
        self.addr                          # queued address cycles belong before this command
        self._write_cmd(c)
        self._ale_state()

    def _write_cmd(self, c):
        c &= 0xFF
        if c == 0xFF:                      # reset
            self.mode = 'status'
            self.cmd = c
            self.addr = []
            self.start_busy(3)
            self.cmd_log.append(('reset',))
            return
        if self.st_uid and c in (0x29, 0x16, 0x02, 0x19):
            self.st_seq.append(c)          # ST "read unique ID" prefix 29 16 02 19 00
            self.cmd = c
            self.addr = []
            return
        if c == 0x90:
            self.mode, self.cmd, self.addr = 'id', c, []
            self.pos = 0
        elif c == 0x00:
            self.cmd, self.addr = c, []
            self.mode = 'addr'
        elif c == 0x30:
            if self.st_seq == [0x29, 0x16, 0x02, 0x19]:
                self.mode, self.pos = 'uid', 0
                self.st_seq = []
                self.cmd_log.append(('uid',))
            elif self.cmd == 0x00:
                col, row = self._parse_addr()
                self.buf = self.page_bytes(row % self.pages) if row < self.pages else bytearray(b'\xff' * PAGE_RAW)
                self.buf = bytearray(self.buf)
                self.pos = col
                self.mode = 'read'
                self.buf_valid = True
                self.cb_page = None
                self.start_busy(3)
                self.last_row = row
                self.cmd_log.append(('read', row, col))
            self.cmd = c
            self.st_seq = []
        elif c == 0x35:                    # copy-back read: load page register, no data output
            col, row = self._parse_addr()
            self.buf = bytearray(self.page_bytes(row) if row < self.pages else b'\xff' * PAGE_RAW)
            self.cb_page = row
            self.mode = 'idle'
            self.cmd = c
            self.start_busy(3)
            self.cmd_log.append(('cbread', row))
        elif c == 0x05:                    # random data output setup
            self.cmd, self.addr = c, []
            self.mode = 'addr'
        elif c == 0xE0:
            if self.cmd == 0x05:
                col, _ = self._parse_addr()
                self.pos = col
                self.mode = 'read'
            self.cmd = c
        elif c == 0x70:
            self.mode, self.cmd = 'status', c
        elif c == 0x80:                    # page program
            self.cmd, self.addr = c, []
            self.mode = 'addr'
            self.buf = bytearray(b'\xff' * PAGE_RAW)
            self.cb_page = None
        elif c == 0x85:                    # random data input / copy-back program
            if self.mode == 'addr' and self.cmd in (0x80, 0x85) and len(self.addr) > 2:
                # a destination row with no data after it, then 85h again (copy-back program that replaces part of the page:
                # 35h, 85h + column + row, 85h + column + data ..., 10h): keep the row
                self._prog_begin()
            self.cmd, self.addr = c, []
            self.mode = 'addr'
        elif c in (0x10, 0x15):            # program confirm / cache program confirm
            if self.mode == 'addr' and self.cmd in (0x80, 0x85):
                self._prog_begin()
            if self.cmd in (0x80, 0x85) and self.prog_page is not None:
                self._do_program(self.prog_page)
            self.mode = 'status'
            self.cmd = c
            self.start_busy(3)
            self.prog_page = None
        elif c == 0x60:                    # block erase setup
            self.cmd, self.addr = c, []
            self.mode = 'addr'
        elif c == 0xD0:
            if self.cmd == 0x60:
                row = 0
                for i, b in enumerate(self.addr):
                    row |= b << (8 * i)
                self._do_erase(row)
            self.mode = 'status'
            self.cmd = c
            self.start_busy(3)
        else:
            self.cmd = c
            self.cmd_log.append(('unknown cmd', c))

    def write_addr(self, b):
        b &= 0xFF
        self.addr.append(b)
        if self.cmd in (0x80, 0x85):
            # address phase of a program: 2 column bytes then row bytes (row only for 0x80 / copy-back 0x85)
            # the page is known once the cycle count is reached; we resolve lazily at data-in time
            self.mode = 'addr'

    def _prog_begin(self):
        col, row = self._parse_addr()
        if self.cmd == 0x80:
            self.prog_page = row
            self.buf = bytearray(b'\xff' * PAGE_RAW)
        elif len(self.addr) > 2:           # 0x85 with a row: copy-back program, page register holds the source
            self.prog_page = row
        # 0x85 with only a column: random data input into the open program
        self.pos = col
        self.mode = 'prog'

    def _do_program(self, row):
        old, buf = self.page_bytes(row), self.buf
        if len(old) < PAGE_RAW or len(buf) < PAGE_RAW:
            raise IndexError('NAND program of page %d: %d bytes there, %d in the page register' % (row, len(old), len(buf)))
        # NAND programs bits 1 -> 0 only: the AND of the two pages, taken as two numbers
        new = bytearray((int.from_bytes(old[:PAGE_RAW], 'little') & int.from_bytes(buf[:PAGE_RAW], 'little')).to_bytes(PAGE_RAW, 'little'))
        if self.fail_next:
            self.status |= 1
            self.fail_next = False
        else:
            self.status &= ~1
            self.overlay[row] = new
        self.cmd_log.append(('program', row))

    def _do_erase(self, row):
        blk = (row // PAGES_PER_BLOCK) * PAGES_PER_BLOCK
        if self.fail_next:
            self.status |= 1
            self.fail_next = False
        else:
            self.status &= ~1
            for p in range(blk, blk + PAGES_PER_BLOCK):
                self.overlay[p] = bytearray(b'\xff' * PAGE_RAW)
        self.cmd_log.append(('erase', blk))

    def read_byte(self):
        m = self.mode
        if m == 'addr' and self.cmd == 0x00 and not self.addr and self.buf_valid:
            # CMD 00h with no address cycles after it: "back to read mode" (a driver does this after waiting
            # for ready); keeps streaming the page register
            self.mode = m = 'read'
        if m == 'read':
            b = self.buf[self.pos] if self.pos < PAGE_RAW else 0xFF
            self.pos += 1
            return b
        if m == 'status':
            return self.status
        if m == 'id':
            b = self.ids[self.pos] if self.pos < len(self.ids) else 0
            self.pos += 1
            return b
        if m == 'uid':
            b = ST_UNIQUE_ID[self.pos] if self.pos < 16 else 0xFF
            self.pos += 1
            return b
        return 0xFF

    def write_byte(self, b):
        if self.mode == 'addr' and self.cmd in (0x80, 0x85):
            self._prog_begin()
        if self.mode == 'prog':
            if self.pos < PAGE_RAW:
                self.buf[self.pos] = b & 0xFF
            self.pos += 1

    def addr_done_for_prog(self):
        pass


class NandSystem:
    """Chip + controller registers + ECC engine behind two bus windows."""

    def __init__(self, image_path, chip=DEFAULT_CHIP, platform_version=0, overlay=None):
        self.chip = NandChip(image_path, chip, overlay)
        self.ecc = EccEngine()
        self.regs = {}
        self.ctrl_val = 0
        self.platform_version = platform_version      # informational: only the driver's own check uses it
        self.bus = NandBus(self)
        self.ctrl = NandCtrl(self)
        self._c = None; self._regs_native = False
        self.access_log = None                        # set to a list to trace bus accesses
        self.port = None                              # optional emu.native_port.StreamPort over the data port (see NandBus.read)
        self._leased = False                          # the port is handing out (or filling) the page register: chip.pos and the ECC lag behind
        self._lease_ecc = False
        self.ecc_log = []                             # (page, bytes fed, register value) for each read of reg 0x54

    def use_port_state(self, registers=False):
        """Keep the bookkeeping state that the native port's register callbacks serve (chip.busy, queued address cycles, the two
        timing registers) in the port structure. registers=True: the callbacks are installed (emu.native_port.attach_nand_regs)
        and may serve; they are switched off while access_log is set."""
        c = self.port.c; chip = self.chip
        c.busy = chip.busy; c.npend = 0
        c.tim[0], c.tim[1] = self.regs.pop(R_TIM0, 0), self.regs.pop(R_TIM1, 0)
        chip._c = self._c = c
        chip._ale_state()
        self._regs_native = registers
        c.reg_on = bool(registers and self.access_log is None)

    @property
    def access_log(self):
        return self._access_log

    @access_log.setter
    def access_log(self, v):
        self._access_log = v
        if self._c is not None:
            self._c.reg_on = bool(self._regs_native and v is None)

    def windows(self):
        """[(base, size, device)] for the emulator core."""
        return [(BUS_BASE, BUS_SIZE, self.bus), (CTRL_BASE, CTRL_SIZE, self.ctrl)]

    def sync(self):
        """Bring chip.pos and the ECC engine up to date with what the native port handed out. Every bus access does this first;
        call it before looking at the model from outside while a port is attached."""
        if self._leased:
            n = self.port.take(); c = self.chip; self._leased = False
            if n:
                if self._lease_ecc:
                    self.ecc.feed_bytes(c.buf[c.pos:c.pos + n])
                c.pos += n


class NandBus:
    def __init__(self, sysm):
        self.s = sysm

    def read(self, offset, size):
        s = self.s
        if s._leased: s.sync()
        if offset >= OFF_CLE:
            return 0
        c = s.chip
        if c.mode == 'read' and c.pos + size <= PAGE_RAW:          # streaming a page: take the bytes in one go
            raw = c.buf[c.pos:c.pos + size]; c.pos += size
            v = int.from_bytes(raw, 'little')
            if s.ctrl_val & 0x40:
                s.ecc.feed_bytes(raw)
            if s.port is not None and c.pos < PAGE_RAW and s.access_log is None:
                # The following reads are this same branch until the page register runs out or something else touches the model:
                # the port serves them (same bytes, pos advancing) and sync() feeds the ECC with what it handed out.
                s._lease_ecc = bool(s.ctrl_val & 0x40); s._leased = True
                s.port.grant(c.buf, c.pos, PAGE_RAW)
        else:
            v = 0
            for i in range(size):
                b = c.read_byte()
                if s.ctrl_val & 0x40:
                    s.ecc.feed(b)
                v |= b << (8 * i)
        if s.access_log is not None:
            s.access_log.append(('r', offset, size, v))
        return v

    def write(self, offset, size, value):
        s = self.s
        if s._leased: s.sync()
        if s.access_log is not None:
            s.access_log.append(('w', offset, size, value))
        if offset >= OFF_ALE:
            s.chip.write_addr(value & 0xFF)
        elif offset >= OFF_CLE:
            s.chip.write_cmd(value & 0xFF)
        else:
            for i in range(size):
                b = (value >> (8 * i)) & 0xFF
                s.chip.write_byte(b)
                if s.ctrl_val & 0x40:
                    s.ecc.feed(b)
            c = s.chip
            if s.port is not None and c.mode == 'prog' and c.pos < PAGE_RAW and s.access_log is None:
                # data-in of a program: further writes that fit the page register store their bytes at pos, as write_byte does;
                # the port takes them and sync() feeds the ECC from the register
                s._lease_ecc = bool(s.ctrl_val & 0x40); s._leased = True
                s.port.grant(c.buf, c.pos, PAGE_RAW, write=True)


class NandCtrl:
    def __init__(self, sysm):
        self.s = sysm

    def read(self, offset, size):
        s = self.s
        if s._leased: s.sync()
        if offset == R_READY:
            return 0x2 if s.chip.ready() else 0x0
        if offset == R_STATUS:
            return 0x40
        if offset == R_ECC:
            s.ecc_log.append((s.chip.last_row, s.ecc.idx, s.ecc.reg()))
            return s.ecc.reg()
        if offset == R_CTRL:
            return s.ctrl_val
        if s._c is not None and offset in (R_TIM0, R_TIM1):
            return s._c.tim[offset == R_TIM1]
        return s.regs.get(offset, 0)

    def write(self, offset, size, value):
        s = self.s
        if s._leased: s.sync()
        if offset == R_CTRL:
            old = s.ctrl_val
            s.ctrl_val = value & 0xFFFFFFFF
            # the driver clears bits 7:6 and then sets bit 6 to restart the accumulator
            if (value & 0x40) and not (old & 0x40):
                s.ecc.reset()
        elif s._c is not None and offset in (R_TIM0, R_TIM1):
            s._c.tim[offset == R_TIM1] = value & 0xFFFFFFFF
        else:
            s.regs[offset] = value & 0xFFFFFFFF
