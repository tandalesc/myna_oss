"""DB3210 display model (the phone's 240x320 panel). Plain Python, no unicorn import.

Marks: [V] verified on bytes, [I] inferred.

Two classes plug into the rest of the emulator:

  XgamDisplay  the XGAM graphics block at 0xD0000000 (GAMCON, PDICON, GRAM banks, 2D accelerator FIFO, PDI
               program memory). Attach with machine.attach(0xD0000000, 0x200000, XgamDisplay(read_mem=...)).
               On a PDICON "start" write it reads the source layer from emulated RAM through the GRAM bank
               registers, builds a 240x320 image and writes a PNG.
  Panel        the Samsung S6D14A0 command/data interface (MIPI-DCS like). Used by the self-test and a window write, and available to anyone who models the PDI
               program engine at command level.

Also: parse_cmdseq() for command sequences written as text and a minimal PNG writer.
Run `native/.venv/bin/python -I native/emu_lcd/lcd_model.py` for the self-test (writes PNGs to run/selftest/).
"""
import os
import re
import struct
import sys
import zlib

try:
    import lcd_native                 # compiled pixel loops (same bytes); absent or unbuildable: the Python code below does it all
except ImportError:
    lcd_native = None

W, H = 240, 320

# ---------------------------------------------------------------- PNG

def png_bytes(w, h, rgb, level=6):
    """rgb: bytes/bytearray of w*h*3. Returns a PNG file as bytes (8-bit RGB, no interlace). level: zlib's, 1 = fastest."""
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(bytes(raw), level)) + chunk(b'IEND', b''))


def write_png(path, w, h, rgb):
    with open(path, 'wb') as f:
        f.write(png_bytes(w, h, rgb))


class FrameWriter:
    """Second thread for the frame files (XgamDisplay(async_out=True)): PNG compression is 2-7 ms per picture, a quarter of the host
    time of a Java game that repaints 60 times a second. Jobs run in the order given; put() waits when `depth` jobs are waiting, so
    the files can never fall far behind the run. zlib works without the interpreter lock, so the emulation thread is not held up."""

    def __init__(self, depth=16):
        import queue
        import threading
        self.q = queue.Queue(depth)
        self.errors = 0
        self.thread = threading.Thread(target=self._work, name='frame-writer', daemon=True)
        self.thread.start()

    def _work(self):
        while True:
            job = self.q.get()
            try:
                job()
            except Exception:
                self.errors += 1
            finally:
                self.q.task_done()

    def put(self, job):
        self.q.put(job)

    def drain(self):
        self.q.join()


def rgb565_to_rgb(lo, hi):
    v = lo | (hi << 8)
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


# whole-plane versions (video playback refreshes the panel 25 times a second: no per-pixel Python loop there)
_TR = bytes(((h >> 3) << 3) | (h >> 5) for h in range(256))                      # red from the high byte
_TB = bytes(((l & 31) << 3) | ((l & 31) >> 2) for l in range(256))               # blue from the low byte
_GH = bytes(((h & 7) << 5) | ((h & 7) >> 1) for h in range(256))                 # green: three bits from the high byte ...
_GL = bytes((l >> 5) << 2 for l in range(256))                                   # ... three from the low byte


_Q6 = bytes((v & 0xfc) | (v >> 6) for v in range(256))                            # six bits of a colour, widened to eight
_Q5 = bytes((v & 0xf8) | (v >> 5) for v in range(256))                            # five


def planes565(buf):
    """RGB565 little-endian bytes -> (R, G, B) byte planes, same expansion as rgb565_to_rgb."""
    lo, hi = buf[0::2], buf[1::2]
    g = (int.from_bytes(hi.translate(_GH), 'little') | int.from_bytes(lo.translate(_GL), 'little')).to_bytes(len(lo), 'little')
    return hi.translate(_TR), g, lo.translate(_TB)


def _clip(x):
    return 0 if x < 0 else 255 if x > 255 else int(x)


_T_R = bytes(_clip(1.164 * (y - 16) + 1.596 * (v - 128)) for v in range(256) for y in range(256))      # index = y | v << 8
_T_B = bytes(_clip(1.164 * (y - 16) + 2.018 * (u - 128)) for u in range(256) for y in range(256))      # index = y | u << 8
_T_GO = bytes(_clip(128 + (0.391 * (u - 128) + 0.813 * (v - 128)) / 2) for v in range(256) for u in range(256))    # index = u | v << 8
_T_G = bytes(_clip(1.164 * (y - 16) - 2 * (g - 128)) for g in range(256) for y in range(256))          # index = y | offset << 8


def _pairs(lo, hi):
    b = bytearray(2 * len(lo))
    b[0::2], b[1::2] = lo, hi
    return memoryview(bytes(b)).cast('H')


def _up(p, cw, ch, w):
    """Chroma plane cw x ch -> twice the size by repetition, cut to w per line."""
    rows = []
    for r in range(ch):
        row = p[r * cw:r * cw + cw]
        d = bytearray(2 * cw)
        d[0::2], d[1::2] = row, row
        d = bytes(d[:w])
        rows.append(d); rows.append(d)
    return b''.join(rows)


def yuv420_to_planes(y, u, v, w, h, cw):
    """Planar 4:2:0 (BT.601, limited range [I]) -> (R, G, B) byte planes of w x h; cw = chroma line length."""
    ch = (h + 1) // 2
    uu, vv = _up(u, cw, ch, w)[:w * h], _up(v, cw, ch, w)[:w * h]
    go = bytes(map(_T_GO.__getitem__, _pairs(uu, vv)))
    return (bytes(map(_T_R.__getitem__, _pairs(y, vv))), bytes(map(_T_G.__getitem__, _pairs(y, go))), bytes(map(_T_B.__getitem__, _pairs(y, uu))))



def parse_cmdseq(value):
    """Tokenise a command sequence such as `$ 11 $ %w78 $ 3A $ 06 $ 29 $`.
    `$ XX $` starts a command byte, bare hex bytes after it are its parameters, `%wNN` waits NN ms (hex: 0x78 = 120 ms),
    other `%` tokens are bus-control tokens kept verbatim [I: chip-select handling].  Returns a list of ('cmd', code,
    [params]) / ('wait', ms) / ('ctl', token)."""
    out = []
    cur = None
    toks = re.findall(r'\$\s*([0-9A-Fa-f]{2})\s*\$|(%\w+)|\b([0-9A-Fa-f]{2})\b', value)
    for c, ctl, d in toks:
        if c:
            cur = ('cmd', int(c, 16), [])
            out.append(cur)
        elif ctl:
            if ctl.startswith('%w') and not ctl.startswith('%wr'):
                out.append(('wait', int(ctl[2:], 16)))
            else:
                out.append(('ctl', ctl))
            cur = None if not ctl.startswith('%w') else cur
        elif d and cur is not None:
            cur[2].append(int(d, 16))
    return out

# ---------------------------------------------------------------- panel (S6D14A0, DCS-like)

class Panel:
    """Command/data model of the 240x320 panel. DCS commands modelled: 01 11 10 28 29 2A 2B 2C 3C 36 3A; the parameters of
    any other command are taken and dropped.
    Memory-write (2C) stores pixels at the current window position."""

    def __init__(self, w=W, h=H):
        self.w, self.h = w, h
        self.gram = bytearray(w * h * 3)
        self.sleep = True
        self.on = False
        self.madctl = 0
        self.colmod = 0x05           # 05 = 16 bit/pixel RGB565, 06 = 18 bit (3A parameter) [I from DCS]
        self.col = [0, w - 1]
        self.row = [0, h - 1]
        self.cx = self.cy = 0
        self.cmd = None
        self.params = []
        self.last_cmds = []
        self._pix = bytearray()
        self.frames = 0

    # one command byte with D/C low, then parameter/pixel bytes with D/C high
    def write_cmd(self, c):
        self._end_cmd()
        self.cmd = c
        self.params = []
        self.last_cmds.append(c)
        if c == 0x01:
            self.sleep, self.on = True, False
        elif c == 0x11:
            self.sleep = False
        elif c == 0x10:
            self.sleep = True
        elif c == 0x28:
            self.on = False
        elif c == 0x29:
            self.on = True
        elif c == 0x2C:
            self.cx, self.cy = self.col[0], self.row[0]
            self._pix = bytearray()

    def write_data(self, d):
        c = self.cmd
        if c in (0x2C, 0x3C):
            self._pix.append(d & 0xff)
            n = 2 if self.colmod == 0x05 else 3
            if len(self._pix) == n:
                self._put_pixel(bytes(self._pix))
                self._pix = bytearray()
        else:
            self.params.append(d & 0xff)
            if c in (0x36, 0x3A) or (c in (0x2A, 0x2B) and len(self.params) == 4):
                self._end_cmd()               # a complete parameter set takes effect at once

    def _end_cmd(self):
        c, p = self.cmd, self.params
        if c == 0x2A and len(p) >= 4:
            self.col = [(p[0] << 8) | p[1], (p[2] << 8) | p[3]]
        elif c == 0x2B and len(p) >= 4:
            self.row = [(p[0] << 8) | p[1], (p[2] << 8) | p[3]]
        elif c == 0x36 and p:
            self.madctl = p[0]
        elif c == 0x3A and p:
            self.colmod = p[0] & 7
        self.params = []

    def _put_pixel(self, b):
        if self.colmod == 0x05:
            r, g, bl = rgb565_to_rgb(b[1], b[0])  # high byte first on the bus
        else:
            r, g, bl = (b[0] & 0xfc) | (b[0] >> 6), (b[1] & 0xfc) | (b[1] >> 6), (b[2] & 0xfc) | (b[2] >> 6)
        if self.madctl & 0x08:       # BGR order bit
            r, bl = bl, r
        x, y = self.cx, self.cy
        if 0 <= x < self.w and 0 <= y < self.h:
            o = (y * self.w + x) * 3
            self.gram[o:o + 3] = bytes((r, g, bl))
        # advance inside the window (no MV/MX/MY handling needed for MADCTL 0x18, which sets ML|BGR only [I])
        self.cx += 1
        if self.cx > self.col[1]:
            self.cx = self.col[0]
            self.cy += 1
            if self.cy > self.row[1]:
                self.cy = self.row[0]
                self.frames += 1

    def read_reg(self, c):
        """Answer to a register read. 0A = power mode [I from MIPI DCS: bit7 booster on, bit4 sleep out, bit3 normal mode,
        bit2 display on]; an ESD check reads it and wants the display-on bit.
        Other registers: 0 [MOCK]."""
        if c == 0x0A:
            return 0x88 | (0 if self.sleep else 0x10) | (0x04 if self.on else 0)
        return 0

    def run_steps(self, steps):
        """Replay a parse_cmdseq() list (commands and parameters only)."""
        for s in steps:
            if s[0] == 'cmd':
                self.write_cmd(s[1])
                for d in s[2]:
                    self.write_data(d)
        self._end_cmd()

    def image(self):
        return self.w, self.h, bytes(self.gram)

# ---------------------------------------------------------------- XGAM block

class FrameStream:
    """The screen as a stream for a viewer (XgamDisplay(stream=FrameStream(path))). The viewer listens on the Unix socket `path`;
    each picture goes to it as one message. Only the newest picture matters: put() keeps it in one slot and returns at once, and
    a second thread sends it. A picture that comes while the one before is on its way replaces the one that waits. Thus a slow
    viewer makes pictures drop, nothing queues, and the run never waits. Without a listener the thread tries the connection
    again every RETRY seconds; the newest picture is the first to go after a connect.
    Message: HEADER (MAGIC, frame number, width, height, time.time() of the refresh, byte count), then the RGB bytes."""
    HEADER = struct.Struct('<4sIHHdI')
    MAGIC = b'SCR1'
    RETRY = 0.5

    def __init__(self, path):
        import threading
        self.path, self.slot, self.event = path, None, threading.Event()
        threading.Thread(target=self._work, name='frame-stream', daemon=True).start()

    def put(self, n, w, h, rgb):
        import time
        self.slot = (n, w, h, time.time(), rgb)
        self.event.set()

    def _work(self):
        import socket
        sock = sent = None
        while True:
            self.event.wait(None if sock else self.RETRY)
            self.event.clear()
            job = self.slot                       # read after clear(): a put() between the two is not missed
            if job is None or job is sent:
                continue
            try:
                if sock is None:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.connect(self.path)
                n, w, h, t, rgb = job
                sock.sendall(self.HEADER.pack(self.MAGIC, n, w, h, t, len(rgb)))
                sock.sendall(rgb)
                sent = job
            except OSError:                       # no viewer, or it went away: the picture waits for the next try
                if sock is not None:
                    sock.close()
                sock = None


class XgamDisplay:
    """XGAM register block at 0xD0000000 (offsets below are from that base).

    GAMCON  +0x000 ID/version, +0x004 control, +0x008 mask, +0x010, +0x014, +0x018, +0x01c status (write 1 = clear)
            +0x400+4*i  bank i base address >> 20 (i = 1..15), +0x444..+0x450 cache control (bit3 dirty, bit4 busy,
            writing bit2 starts a flush) [V]
    PDI     +0x1000..+0x10ff program memory (bytes) [V]; its top is the
            data area: command / parameter bytes ending at +0x10ff, +0x111c says which is which, +0x11dc = 2 sends them to the panel,
            +0x11dc = 3 reads a panel register (answer in +0x11f4 bits 15:8): see _pdi_run
            +0x10fc,+0x1100,+0x111c,+0x1120,+0x11dc..+0x11fc pad / timing configuration [V addresses, I meaning]
    PDICON  +0x1404 command (2 or 3 = start), +0x1408 status (bit0 busy), +0x1410 control, +0x1418 irq enable (bit0),
            +0x141c, +0x1420 irq status, +0x1424 irq clear, +0x1440 (w | h << 16), +0x1444 output depth (0x10 / 0x12),
            +0x1448 update origin (x | y << 16), +0x144c its size (w | h << 16), +0x1450 source GRAM offset, +0x1454 source width (px),
            +0x1458 source bits/pixel, +0x14e4..+0x14f8 data-line colour map, +0x14fc..+0x1528 overlay setup
            +0x1460 orientation of the source layer (5 = landscape surface shown turned a quarter), +0x145c the source
            place of the update's first pixel: see _layer
            +0x1410 bits 9:8 = video plane on; planes Y / U / V +0x1478 / +0x147c / +0x1480 (GRAM offsets), line lengths
            +0x1490 / +0x1494, size +0x149c (width | height << 16), origin +0x14a0 and scale +0x14a4: see _video_plane
    CDI     +0x804 control (bit0 enable), +0x808 bytes expected per frame, +0x80c bytes received, +0x824 interrupt status,
            +0x828 enable, +0x82c acknowledge (line 14)                                     [V]
    CDICON  +0xc04 control (bit4 enable, bit6 start), +0xc24 capture buffer (GRAM offset), +0xc48 pixels per line, +0xc4c lines,
            +0xc10 interrupt status (bit2 = frame stored, bit4 = error), +0xc0c enable, +0xc14 acknowledge (line 15), +0xc08 bit2
            and +0xc20: transfer in progress                                               [V]
            The camera port is fed by camera_frame(); in this phone the MP202 video chip is wired to it.
    GAMEACC +0x1804 command FIFO, +0x1808 status (bit2 busy, bit3 full)
    MCIDCT  +0x1c00..+0x1c74 motion compensation and inverse DCT for the software video decoders: handed to `idct`
            (native/emu_idct) when that model is attached; plain storage otherwise
    GRAM    +0x100000..+0x10ffff bank 0 (internal 64 KB, CPU address 0xD0100000) [V]

    GRAM offset -> CPU address: bank = off >> 20; bank 0 is the internal RAM, bank i >= 1 is the 1 MB block at
    (bank_reg[i] << 20) | (off & 0xfffff) [V].
    Constants marked [I] are guesses to be replaced when a trace shows the real firmware use.
    """
    ID_VALUE = 0x00004101        # block id 0x41 in bits 15:8 (a driver checks (v & 0xff00) == 0x4100); low byte (< 8) is a version [V]
    IRQ_LINE_PDICON = 18         # VIC lines [V]
    IRQ_LINE_GAMCON = 13
    IRQ_LINE_CDI, IRQ_LINE_CDICON = 14, 15
    panel = screen = None        # defaults for an object that did not go through __init__
    idct = None                  # the model of the MCIDCT sub-block (native/emu_idct), when one is attached: +0x1c00..+0x1cff

    panel_depth = False               # True: a 24 / 32 bit source is cut to the colour depth the panel gets (see _layer)

    def __init__(self, read_mem=None, irq_cb=None, out_dir=None, on_frame=None, name='XGAM', async_out=False, stream=None):
        self.name = name
        self.read_mem = read_mem          # read_mem(addr, n) -> bytes of emulated RAM
        self.irq_cb = irq_cb              # irq_cb(line, level)
        self.out_dir = out_dir
        self.on_frame = on_frame          # on_frame(w, h, rgb_bytes, n)
        self.regs = {}
        self.gram0 = bytearray(0x10000)
        self.accel_words = []
        self.accel_cmds = []
        self.frame_count = 0
        self.camera_frames = 0
        self.last_frame = None
        self.log = []
        self.panel = Panel()              # the panel behind the PDI engine: power state and register reads
        self.screen = None                # what the panel's own memory holds (an update may cover part of it)
        self.writer = FrameWriter() if async_out and out_dir else None    # frame files written by a second thread, in order
        self.stream = stream              # a FrameStream: every picture also goes to a viewer

    def after_write(self, fn):
        """Call fn() once every frame file asked for so far is complete: at once, or on the writer thread (async_out)."""
        if self.writer:
            self.writer.put(fn)
        else:
            fn()

    def drain(self):
        """Wait until the writer thread has nothing left (end of the run)."""
        if self.writer:
            self.writer.drain()

    # -- bus interface
    def read(self, offset, size):
        if 0x100000 <= offset < 0x110000:
            return int.from_bytes(self.gram0[offset - 0x100000:offset - 0x100000 + size], 'little')
        a = offset & ~3
        v = self._rd32(a)
        sh = (offset & 3) * 8
        return (v >> sh) & ((1 << (8 * size)) - 1)

    def write(self, offset, size, value):
        if 0x100000 <= offset < 0x110000:
            self.gram0[offset - 0x100000:offset - 0x100000 + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, 'little')
            return
        if size == 4 and not offset & 3:
            self._wr32(offset, value & 0xffffffff)
            return
        a = offset & ~3
        sh = (offset & 3) * 8
        m = ((1 << (8 * size)) - 1) << sh
        v = (self.regs.get(a, 0) & ~m) | ((value << sh) & m)
        self._wr32(a, v & 0xffffffff)

    # -- registers
    def _rd32(self, a):
        if a == 0x000:
            return self.ID_VALUE
        if 0x1c00 <= a < 0x1d00 and self.idct is not None:
            return self.idct.read(a - 0x1c00)
        if a == 0x1408:                      # PDICON status: operations complete instantly in this model
            return self.regs.get(a, 0) & ~1
        if a == 0x1808:                      # GAMEACC status: never busy, never full
            return 0
        return self.regs.get(a, 0)

    def _wr32(self, a, v):
        if 0x1c00 <= a < 0x1d00 and self.idct is not None:
            return self.idct.write(a - 0x1c00, v)
        if a in (0x1c, 0x1424):              # write-1-to-clear status registers [I]
            st = 0x1c if a == 0x1c else 0x1420
            self.regs[st] = self.regs.get(st, 0) & ~v
            self._irq_update()
            return
        if a == 0xc14:                       # CDICON interrupt acknowledge: the status read from +0xc10 is written here [V]
            self.regs[0xc10] = self.regs.get(0xc10, 0) & ~v
            self._cam_irq()
            return
        if a == 0x82c:                       # CDI interrupt acknowledge [V]
            self.regs[0x824] = self.regs.get(0x824, 0) & ~v
            self._cam_irq()
            return
        if a in (0x444, 0x448, 0x44c, 0x450):  # cache control: a flush request completes at once
            if v & 4:
                v &= ~0x1c
        if a == 0x1804:
            self._accel_word(v)
            return
        self.regs[a] = v
        if a == 0x1404 and v in (2, 3):
            self.start_update()
        elif a == 0x11dc:
            self._pdi_run(v)
        elif a in (0x1418, 0x141c):
            self._irq_update()
        elif a in (0xc0c, 0x828):
            self._cam_irq()

    # -- camera interface (CDI / CDICON)
    def _cam_irq(self):
        if self.irq_cb:
            r = self.regs
            self.irq_cb(self.IRQ_LINE_CDICON, bool(r.get(0xc10, 0) & r.get(0xc0c, 0) & 0xff))
            self.irq_cb(self.IRQ_LINE_CDI, bool(r.get(0x824, 0) & r.get(0x828, 0) & 0xff))

    def camera_state(self):
        """None while the capture is not armed, else (pixels per line, lines, bytes per frame) as the driver programmed them."""
        r = self.regs
        if not (r.get(0xc04, 0) & 0x10 and r.get(0x804, 0) & 1):
            return None
        return r.get(0xc48, 0) & 0x7ff, r.get(0xc4c, 0) & 0x7ff, r.get(0x808, 0)

    def camera_frame(self, data, write_mem):
        """One frame arriving on the camera port: stored at the capture buffer (+0xc24), byte count in +0x80c, 'frame stored'
        (bit 2) in +0xc10, interrupt line 15. write_mem(addr, bytes) stores into emulated RAM. False = capture not armed.
        [MOCK] the frame arrives at once; the CDI's own status (+0x824) stays clear."""
        st = self.camera_state()
        if st is None:
            return False
        r = self.regs
        n = min(len(data), st[2] or len(data))
        off = r.get(0xc24, 0)
        if off >> 20 == 0:
            self.gram0[off:off + n] = data[:n]
        else:
            write_mem(self.gram_to_cpu(off), bytes(data[:n]))
        r[0x80c] = n
        r[0xc20] = 0
        r[0xc08] = r.get(0xc08, 0) & ~4
        r[0xc10] = r.get(0xc10, 0) | 4
        self.camera_frames += 1
        self._cam_irq()
        return True

    # -- PDI engine: commands to the panel and register reads from it
    def _pdi_run(self, mode):
        """A write to +0x11dc runs a PDI program [V sequence of the driver]:
        2 = send the n bytes that end at +0x10ff (n = the count operand the driver patches into the write program, +0x100e;
            +0x111c has one bit per place of the data area, bit 31 for the byte at +0x10ff, bit 30 for +0x10fe and so on:
            set = a parameter, clear = a command [V `3a 06` is sent with 0x80000000]);
        3 = send the command at +0x10ff and read one byte back; the driver takes it from bits 15:8 of +0x11f4 [V].
        The program completes at once. [I] that the same byte answers both read programs."""
        r = self.regs
        pan = self.panel
        if pan is None:
            pan = self.panel = Panel()

        def byte(addr):
            return (r.get(addr & ~3, 0) >> (8 * (addr & 3))) & 0xff
        if mode == 2:
            n = (r.get(0x100c, 0) >> 16) & 0xffff
            if not 0 < n <= 32:
                return
            flags = r.get(0x111c, 0)
            for i in range(n):
                b = byte(0x1100 - n + i)
                if flags >> (32 - n + i) & 1:
                    if pan.cmd not in (0x2C, 0x3C):       # pixels do not come this way
                        pan.write_data(b)
                else:
                    pan.write_cmd(b)
        elif mode == 3:
            c = byte(0x10ff)
            pan.write_cmd(c)
            r[0x11f4] = (r.get(0x11f4, 0) & ~0xff00) | (pan.read_reg(c) << 8)

    def _irq_update(self):
        if self.irq_cb:
            lvl = bool(self.regs.get(0x1420, 0) and (self.regs.get(0x1418, 0) & 1))
            self.irq_cb(self.IRQ_LINE_PDICON, lvl)

    def _accel_word(self, v):
        """GAMEACC command words [V layout, I semantics]: 0x400, src GRAM offset, a1, dst GRAM offset,
        a3, (h << 16) | (w & 0xfff). Only recorded; the blitter is not executed (open item)."""
        self.accel_words.append(v)
        if len(self.accel_words) == 6 and self.accel_words[0] == 0x400:
            self.accel_cmds.append(tuple(self.accel_words))
            self.accel_words = []
        elif self.accel_words and self.accel_words[0] != 0x400 and len(self.accel_words) == 1:
            self.accel_words = []        # single-word commands (reset sequence 0x109, 1, 0x109, 0) [V]

    # -- GRAM translation and frame build
    def gram_to_cpu(self, off):
        bank = off >> 20
        if bank == 0:
            return 0xD0100000 + (off & 0xfffff)
        base = (self.regs.get(0x400 + 4 * bank, 0) & 0xfff) << 20
        return base + (off & 0xfffff)

    def _read_gram(self, off, n):
        out = bytearray()
        while n > 0:
            chunk = min(n, 0x100000 - (off & 0xfffff))
            if off >> 20 == 0:
                o = off & 0xfffff
                out += self.gram0[o:o + chunk] if o < len(self.gram0) else bytes(chunk)
            else:
                out += self.read_mem(self.gram_to_cpu(off), chunk) if self.read_mem else bytes(chunk)
            off += chunk
            n -= chunk
        return bytes(out)

    def frame(self):
        """The picture the panel receives: the RGB layer (upright or turned), then the video plane where it is on."""
        r = self.regs
        w, h, rgb = self._layer()
        if r.get(0x1410, 0) & 0x300 == 0x300:
            try:
                rgb = self._video_plane(w, h, rgb)
            except Exception:
                pass
        return w, h, rgb

    def _layer(self):
        """One update of the RGB layer: the rectangle +0x1448 (origin) / +0x144c (size) of the panel is sent, the panel keeps the
        rest. Each pixel of it is read from the source surface (+0x1450, +0x1454 pixels per line, +0x1458 bits per pixel):
          +0x1460 = 0  upright: panel (x, y) = source (x, y)
          +0x1460 = 5  the source is a landscape surface shown turned a quarter: pixel (i, j) of the rectangle = source
                       (sx + j, sy - i), sx / sy = low / high half of +0x145c, the source place of the rectangle's first pixel
                       (0x00ef0000 for a whole picture: the panel's first line is the surface's first column, read from the last
                       line up). [V register values of a media menu, a video and a picture viewer, with partial
                       updates (+0x145c = 0x00ef006c for a rectangle from panel line 0x6c); I mapping]
        Other values of +0x1460 were not seen and are taken as upright.
        Source pixel: 16 bits = RGB565; 24 bits = blue, green, red bytes [V the picture viewer's surfaces]; 32 = the same and an
        unused byte [I]. Of a 24 / 32 bit pixel the panel gets what the data-line map +0x14e4..+0x14f8 selects for the output
        depth +0x1444 [V both maps as the driver writes them]: 0x12 = the top six bits of each colour (panel in
        18 bits a pixel, command 3A 06), 0x10 = five, six and five. The picture holds them widened to eight the way the panel
        model does it. A 16-bit source is shown as RGB565 at either depth [I].
        The cut to the panel's depth is made only with panel_depth set; without it the picture keeps all eight bits of a
        24 / 32 bit source."""
        r = self.regs
        sz = r.get(0x1440, 0)
        w, h = (sz & 0x7ff) or W, ((sz >> 16) & 0x7ff) or H
        turned = r.get(0x1460, 0) == 5
        sw = r.get(0x1454, 0) or (h if turned else w)
        bpp = r.get(0x1458, 0) or r.get(0x1444, 0) or 16
        nb = 2 if bpp <= 16 else (3 if bpp == 24 else 4)
        bits = {0x12: 6, 0x10: 5}.get(r.get(0x1444, 0), 8) if self.panel_depth else 8
        pitch = sw * nb
        base = r.get(0x1450, 0)
        x0, y0 = r.get(0x1448, 0) & 0x7ff, (r.get(0x1448, 0) >> 16) & 0x7ff
        uw, uh = r.get(0x144c, 0) & 0x7ff, (r.get(0x144c, 0) >> 16) & 0x7ff      # size of the update, not its far corner
        if not (uw and uh):
            x0, y0, uw, uh = 0, 0, w, h
        n, rows = min(x0 + uw, w) - x0, min(y0 + uh, h) - y0
        old = self.screen
        img = bytearray(old[2]) if old and old[0] == w and old[1] == h else bytearray(w * h * 3)    # outside the update: what the panel had
        if turned:
            sx, sy = r.get(0x145c, 0) & 0x7ff, (r.get(0x145c, 0) >> 16) & 0x7ff
            n, rows = min(n, sy + 1), min(rows, sw - sx)          # the surface ends: nothing is sent for the rest [I]
            first = base + (sy - n + 1) * pitch + sx * nb         # the lines sy - n + 1 .. sy, from column sx
            size, off, di, dj = (n - 1) * pitch + rows * nb, (n - 1) * pitch, -pitch, nb
        else:
            first = base + y0 * pitch + x0 * nb
            size, off, di, dj = (rows - 1) * pitch + n * nb, 0, nb, pitch
        if n <= 0 or rows <= 0:
            return w, h, bytes(img)
        src = self._read_gram(first, size)                        # the whole update in one read
        if lcd_native and lcd_native.layer(src, off, di, dj, nb, bits, img, w, x0, y0, n, rows):
            return w, h, bytes(img)
        if nb == 2:
            planes = planes565(src)
        else:
            planes = (src[2::nb], src[1::nb], src[0::nb])
            if bits != 8:
                planes = (planes[0].translate(_Q6 if bits == 6 else _Q5), planes[1].translate(_Q6), planes[2].translate(_Q6 if bits == 6 else _Q5))
        off, di, dj = off // nb, di // nb, dj // nb               # in pixels now
        seg = bytearray(3 * n)
        for j in range(rows):
            s = off + j * dj
            e = s + n * di
            for k in range(3):
                seg[k::3] = planes[k][s:(e if e >= 0 else None):di]
            o = ((y0 + j) * w + x0) * 3
            img[o:o + 3 * n] = seg
        return w, h, bytes(img)

    def _video_plane(self, w, h, rgb):
        """Planar 4:2:0 picture of the video plane, shown where the RGB layer is black. [I] the real blend rule (+0x1470, +0x1474,
        +0x14fc) is not decoded: during playback the player's surface is all zero where the picture belongs.
        Place and size [V values of a full-screen video and of an upright player; I formula, it puts the player's picture in
        the middle of the panel between its time bar and its title]: panel pixel (X, Y) shows the plane sample
        ((X * sx >> 8) + px, (Y * sy >> 8) + py), sx / sy = low / high half of +0x14a4 (0x100 = 1:1), px / py = low / high half
        of +0x14a0 as signed numbers (0 or negative in the runs: the picture starts right of / below the panel's corner).
        [MOCK] nearest sample; the hardware has a bilinear mode that is not decoded."""
        r = self.regs
        sz = r.get(0x149c, 0)
        ow, oh = sz & 0x7ff, (sz >> 16) & 0x7ff
        ls, cs = r.get(0x1490, 0) & 0xfff, r.get(0x1494, 0) & 0xfff
        if not (ow and oh and ls >= ow and cs):
            return rgb
        pos, sc = r.get(0x14a0, 0), r.get(0x14a4, 0)
        px, py = ((pos & 0xffff) ^ 0x8000) - 0x8000, ((pos >> 16) ^ 0x8000) - 0x8000
        sx, sy = (sc & 0xffff) or 0x100, (sc >> 16) or 0x100
        xs = [v for v in (((X * sx) >> 8) + px for X in range(w)) if 0 <= v < ow]       # plane columns on the panel, left to right
        ys = [v for v in (((Y * sy) >> 8) + py for Y in range(h)) if 0 <= v < oh]
        if not xs or not ys:                                  # nothing of the plane is on the panel: do not convert it
            return rgb
        x0 = next(X for X in range(w) if 0 <= ((X * sx) >> 8) + px < ow)
        y0 = next(Y for Y in range(h) if 0 <= ((Y * sy) >> 8) + py < oh)
        if (sx, sy) != (0x100, 0x100) or xs[0] or ys[0]:     # scaled or cut: make the picture as the panel gets it, then go on 1:1
            ch = (oh + 1) // 2
            yp = self._read_gram(r.get(0x1478, 0), ls * oh)
            up, vp = self._read_gram(r.get(0x147c, 0), cs * ch), self._read_gram(r.get(0x1480, 0), cs * ch)
            vw, vh = len(xs), len(ys)
            cxs, cys = [xs[min(2 * i, vw - 1)] >> 1 for i in range((vw + 1) // 2)], [ys[min(2 * j, vh - 1)] >> 1 for j in range((vh + 1) // 2)]
            pick = lambda plane, pitch, rows, cols: b''.join(bytes(map(plane[v * pitch:v * pitch + pitch].__getitem__, cols)) for v in rows)
            planes = (pick(yp, ls, ys, xs), pick(up, cs, cys, cxs), pick(vp, cs, cys, cxs))
            ow, oh, ls, cs = vw, vh, vw, (vw + 1) // 2
        else:
            planes = None
        ch = (oh + 1) // 2
        if planes is None:
            planes = (self._read_gram(r.get(0x1478, 0), ls * oh), self._read_gram(r.get(0x147c, 0), cs * ch), self._read_gram(r.get(0x1480, 0), cs * ch))
        yp, up, vp = planes
        if lcd_native:
            out = bytearray(rgb)
            if lcd_native.yuv_plane(yp, up, vp, ow, oh, ls, cs,
                                    (_T_R, _T_B, _T_GO, _T_G), out, w, h, x0, y0, min(ow, w - x0), min(oh, h - y0)):
                return bytes(out)
        if ls != ow:
            yp = b''.join(yp[i * ls:i * ls + ow] for i in range(oh))
        R, G, B = yuv420_to_planes(yp, up, vp, ow, oh, cs)
        out = bytearray(rgb)
        vw, vh = min(ow, w - x0), min(oh, h - y0)
        zero = bytes(vw * 3)
        for row in range(vh):
            o = ((y0 + row) * w + x0) * 3
            seg = out[o:o + vw * 3]
            s = row * ow
            if seg == zero:
                seg[0::3], seg[1::3], seg[2::3] = R[s:s + vw], G[s:s + vw], B[s:s + vw]
            else:
                for i in range(vw):
                    if not (seg[3 * i] or seg[3 * i + 1] or seg[3 * i + 2]):
                        seg[3 * i], seg[3 * i + 1], seg[3 * i + 2] = R[s + i], G[s + i], B[s + i]
            out[o:o + vw * 3] = seg
        return bytes(out)

    def start_update(self):
        w, h, rgb = self.frame()
        self.last_frame = self.screen = (w, h, rgb)
        self.frame_count += 1
        self.regs[0x1420] = self.regs.get(0x1420, 0) | 1     # done flag [I]
        if self.out_dir:
            path = os.path.join(self.out_dir, 'frame_%04d.png' % self.frame_count)
            if self.writer:
                if self.frame_count == 1:
                    os.makedirs(self.out_dir, exist_ok=True)
                self.writer.put(lambda: write_png(path, w, h, rgb))
            else:
                os.makedirs(self.out_dir, exist_ok=True)
                write_png(path, w, h, rgb)
        if self.stream:
            self.stream.put(self.frame_count, w, h, rgb)
        if self.on_frame:
            self.on_frame(w, h, rgb, self.frame_count)
        self._irq_update()

# ---------------------------------------------------------------- self-test

_FONT = {  # 5x7 glyphs for the test text
    'C': ['01110', '10001', '10000', '10000', '10000', '10001', '01110'],
    'L': ['10000', '10000', '10000', '10000', '10000', '10000', '11111'],
    'D': ['11110', '10001', '10001', '10001', '10001', '10001', '11110'],
    'O': ['01110', '10001', '10001', '10001', '10001', '10001', '01110'],
    'K': ['10001', '10010', '10100', '11000', '10100', '10010', '10001'],
    ' ': ['00000'] * 7,
}


def _make_test_pattern():
    """240x320 RGB565 test card: vertical colour bars, a gradient strip, a frame and the text 'LCD OK'."""
    px = [[0] * W for _ in range(H)]

    def c565(r, g, b):
        return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    bars = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0)]
    for y in range(0, 120):
        for x in range(W):
            px[y][x] = c565(*bars[x * 8 // W])
    for y in range(120, 160):
        for x in range(W):
            v = x * 255 // (W - 1)
            px[y][x] = c565(v, v, v)
    for y in range(160, 200):
        for x in range(W):
            px[y][x] = c565(255 * x // (W - 1), 255 * (y - 160) // 39, 255 - 255 * x // (W - 1))
    for y in range(200, H):
        for x in range(W):
            px[y][x] = c565(0, 0, 96)
    text, scale, ox, oy = 'LCD OK', 3, 12, 230
    for i, ch in enumerate(text):
        for ry, row in enumerate(_FONT[ch]):
            for rx, bit in enumerate(row):
                if bit == '1':
                    for dy in range(scale):
                        for dx in range(scale):
                            px[oy + ry * scale + dy][ox + i * 6 * scale + rx * scale + dx] = c565(255, 255, 255)
    for x in range(W):
        px[0][x] = px[H - 1][x] = c565(255, 0, 0)
    for y in range(H):
        px[y][0] = px[y][W - 1] = c565(255, 0, 0)
    buf = bytearray()
    for row in px:
        for v in row:
            buf += struct.pack('<H', v)
    return bytes(buf)


def _selftest_turned(panel):
    """A 12 x 16 panel; an upright surface and a landscape one (16 x 12), 24 bits a pixel, every pixel different. `panel`: a Panel
    after the init sequence, used to check one turned picture byte by byte as the panel itself decodes it."""
    w, h = 12, 16
    ram_base = 0x4A100000
    ram = bytearray(0x10000)
    up, land = 0x1000, 0x2000
    def colour(x, y, k):                                   # (red, green, blue), all 8 bits in use
        return (x * 21 + k) & 0xff, (y * 15 + 3 * k + 1) & 0xff, (x * 16 + y + 2 + 5 * k) & 0xff
    def fill(at, sw, sh, k):
        for y in range(sh):
            for x in range(sw):
                red, green, blue = colour(x, y, k)
                ram[at + (y * sw + x) * 3:at + (y * sw + x) * 3 + 3] = bytes((blue, green, red))
    q6 = lambda v: (v & 0xfc) | (v >> 6)
    shown = lambda c: tuple(q6(v) for v in c)              # 18 bits a pixel
    dev = XgamDisplay(read_mem=lambda a, n: bytes(ram[a - ram_base:a - ram_base + n]))
    dev.panel_depth = True
    def update(**regs):
        for a, v in regs.items():
            dev.write(int(a[1:], 16), 4, v)
        dev.write(0x1404, 4, 2)
        rgb = dev.last_frame[2]
        return [[tuple(rgb[(y * w + x) * 3:(y * w + x) * 3 + 3]) for x in range(w)] for y in range(h)]
    dev.write(0x404, 4, ram_base >> 20)
    fill(up, w, h, 0)
    fill(land, h, w, 1)
    # upright, whole picture
    pic = update(r1440=w | h << 16, r1444=0x12, r1458=0x18, r1450=(1 << 20) + up, r1454=w, r1460=0, r145c=0, r1448=0, r144c=w | h << 16)
    ok = pic == [[shown(colour(x, y, 0)) for x in range(w)] for y in range(h)]
    # turned, whole picture: panel (x, y) = surface (y, 11 - x)
    pic = update(r1450=(1 << 20) + land, r1454=h, r1460=5, r145c=(w - 1) << 16)
    want = [[shown(colour(y, w - 1 - x, 1)) for x in range(w)] for y in range(h)]
    ok = ok and pic == want
    # the same picture as the panel decodes it: three bytes a pixel, the colour's top six bits in bits 7:2 (the 18-bit map)
    pan = Panel(w, h)
    pan.madctl = panel.madctl
    pan.run_steps(parse_cmdseq('$3a$ 06 $2a$ 00 00 00 %02x $2b$ 00 00 00 %02x $2c$' % (w - 1, h - 1)))
    for y in range(h):
        for x in range(w):
            for v in colour(y, w - 1 - x, 1):
                pan.write_data(v & 0xfc)
    got = pan.image()[2]
    ok = ok and all(tuple(got[(y * w + x) * 3:(y * w + x) * 3 + 3])[::-1] == want[y][x] for y in range(h) for x in range(w))
    # turned, partial: the surface changes everywhere, the update covers panel lines 5..11 only
    fill(land, h, w, 2)
    pic = update(r1448=5 << 16, r144c=w | 7 << 16, r145c=(w - 1) << 16 | 5)
    want = [[shown(colour(y, w - 1 - x, 2 if 5 <= y < 12 else 1)) for x in range(w)] for y in range(h)]
    ok = ok and pic == want
    # back upright with an update of the top lines: the lines below keep the turned picture until they are sent
    pic = update(r1450=(1 << 20) + up, r1454=w, r1460=0, r145c=0, r1448=0, r144c=w | 4 << 16)
    ok = ok and pic == [[shown(colour(x, y, 0)) for x in range(w)] for y in range(4)] + want[4:]
    pic = update(r144c=w | h << 16)
    ok = ok and pic == [[shown(colour(x, y, 0)) for x in range(w)] for y in range(h)]
    # a 16-bit landscape surface, turned, partial update with a left edge
    for y in range(w):
        for x in range(h):
            ram[land + (y * h + x) * 2:land + (y * h + x) * 2 + 2] = struct.pack('<H', (x * 4099 + y * 257 + 7) & 0xffff)
    px16 = lambda x, y: rgb565_to_rgb(*struct.pack('<H', (x * 4099 + y * 257 + 7) & 0xffff))
    before = pic
    pic = update(r1444=0x10, r1458=0x10, r1450=(1 << 20) + land, r1454=h, r1460=5, r1448=3 | 2 << 16, r144c=6 | 9 << 16, r145c=(w - 1 - 3) << 16 | 2)
    want = [[px16(y, w - 1 - x) if 3 <= x < 9 and 2 <= y < 11 else before[y][x] for x in range(w)] for y in range(h)]
    return ok and pic == want


def selftest(out_dir=None):
    global lcd_native
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    if lcd_native is None:                  # started with -I: this directory is not on the path
        try:
            sys.path.insert(0, here)
            import lcd_native
        except ImportError:
            lcd_native = None
    out_dir = out_dir or os.path.join(os.path.dirname(root), 'run', 'selftest')
    os.makedirs(out_dir, exist_ok=True)
    card = _make_test_pattern()
    ok = True

    # A. XGAM path: frame buffer in emulated RAM, 16 bpp, banks set up as a driver does it
    ram_base = 0x4A100000                   # 1 MB aligned block in SDRAM (any aligned block works)
    fb_off_in_bank = 0x2000
    ram = bytearray(0x100000)
    ram[fb_off_in_bank:fb_off_in_bank + len(card)] = card

    def read_mem(addr, n):
        assert ram_base <= addr and addr + n <= ram_base + len(ram), hex(addr)
        return bytes(ram[addr - ram_base:addr - ram_base + n])
    irqs = []
    dev = XgamDisplay(read_mem=read_mem, irq_cb=lambda line, lvl: irqs.append((line, lvl)),
                      out_dir=out_dir)
    assert (dev.read(0x000, 4) & 0xff00) == 0x4100                     # block id check
    dev.write(0x400 + 4 * 1, 4, ram_base >> 20)                         # bank 1 base
    dev.write(0x444, 4, 1)
    dev.write(0x444, 4, 0x1c)
    dev.write(0x444, 4, 4)                                              # flush request completes at once
    assert dev.read(0x444, 4) & 0x18 == 0
    dev.write(0x1440, 4, W | (H << 16))                                 # layer size
    dev.write(0x1444, 4, 16)                                            # bpp
    dev.write(0x1450, 4, (1 << 20) + fb_off_in_bank)                    # source = GRAM offset (bank 1)
    dev.write(0x1454, 4, W)
    dev.write(0x1458, 4, 16)
    dev.write(0x1448, 4, 0 | (0 << 16))
    dev.write(0x144c, 4, W | (H << 16))                                 # update size
    dev.write(0x1418, 4, 1)                                             # irq enable
    dev.write(0x1404, 4, 2)                                             # start
    assert dev.frame_count == 1 and dev.read(0x1408, 4) & 1 == 0
    assert irqs and irqs[-1] == (18, True)
    dev.write(0x1424, 4, 1)
    assert irqs[-1] == (18, False)
    wA, hA, rgbA = dev.last_frame
    assert (wA, hA) == (W, H)
    pa = os.path.join(out_dir, 'selftest_xgam.png')
    write_png(pa, wA, hA, rgbA)
    # spot checks: first bar white, second yellow, grey ramp, border red
    def px(rgb, x, y): return tuple(rgb[(y * W + x) * 3:(y * W + x) * 3 + 3])
    assert px(rgbA, 5, 50) == (255, 255, 255) and px(rgbA, 40, 50) == (255, 255, 0) and px(rgbA, 0, 0) == (255, 0, 0)

    panel = Panel()
    panel.madctl = 0x18                     # the panel's BGR bit, as an init sequence sets it (part C)

    # C. 24-bit surfaces at 18 bits a pixel, upright and turned, whole and partial updates; with and without the compiled loop
    for native in ((True, False) if lcd_native and lcd_native.load() else (False,)):
        saved = lcd_native._lib if lcd_native else None
        if lcd_native and not native:
            lcd_native._lib = None
        try:
            turned_ok = _selftest_turned(panel)
        finally:
            if lcd_native:
                lcd_native._lib = saved
        print('24-bit and turned updates (%s):' % ('compiled loop' if native else 'Python'), turned_ok)
        ok = ok and turned_ok

    # D. the data area's command / parameter flags: bit 31 belongs to the last byte
    dev = XgamDisplay()
    def send(data, params):                 # params: one character per byte, 'p' = parameter, 'c' = command
        n = len(data)
        area = bytes(32 - n) + bytes(data)
        for k in range(0, 32, 4):
            dev.write(0x10e0 + k, 4, int.from_bytes(area[k:k + 4], 'little'))
        dev.write(0x111c, 4, sum(1 << (32 - n + i) for i, c in enumerate(params) if c == 'p'))
        dev.write(0x100c, 4, 0x9837 | n << 16)
        dev.write(0x11dc, 4, 2)
    send([0x36, 0x18, 0x3a, 0x06], 'cpcp')
    send([0x2a, 0, 0x10, 0, 0x20, 0x2b, 0, 0x18, 1, 0x3f, 0x2c], 'cppppcppppc')
    flags_ok = (dev.regs[0x111c] == 0x7bc00000 and dev.panel.madctl == 0x18 and dev.panel.colmod == 6
                and dev.panel.col == [0x10, 0x20] and dev.panel.row == [0x18, 0x13f] and dev.panel.cmd == 0x2c)
    send([0x3a, 0x05], 'cp')
    flags_ok = flags_ok and dev.regs[0x111c] == 0x80000000 and dev.panel.colmod == 5 and dev.panel.madctl == 0x18
    print('command / parameter flags of the data area:', flags_ok)
    ok = ok and flags_ok
    print('SELFTEST', 'OK' if ok else 'FAILED')
    return ok


if __name__ == '__main__':
    sys.exit(0 if selftest() else 1)
