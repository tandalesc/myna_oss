"""Keep the phone's flash between power cycles: an attachment for native/sim/db3210.py (no harness change needed).

    SIM_FLASH_STATE=FILE  ... db3210.py ... --attach flash_state:attach

Without SIM_FLASH_STATE the attachment does nothing (every run is the first boot after flashing, as before).
With it, the pages the firmware programmed or erased (the NAND model's write overlay) are loaded from FILE at
start and written back to it
  - at intervals (SIM_FLASH_INTERVAL emulated seconds, default 10) while the flash is quiet,
  - on a stop request (SIGTERM, as the live viewer's power button sends; SIGINT), as soon as the flash is quiet,
  - at a normal end of the run, if the flash is quiet then.
"Quiet" = no program or erase command open in the chip model and none finished in the last SIM_FLASH_QUIET
emulated milliseconds (default 1500).  A state is only ever written at a quiet moment, so the file always is a
flash the firmware left between two of its own updates; a stop in the middle of a burst keeps the last quiet
state (and says so).  After SIGTERM the run goes on for at most SIM_FLASH_GRACE host seconds (default 3;
the viewer kills after 5) waiting for quiet.

File format: 'C905FLASH1\\n', one JSON line (base image SHA-1 and size, counts, emulated time), then per erase
block that differs from the base image: u32 block, u64 bitmap of its differing pages, u32 length, zlib of those
0x840-byte pages; then 'END\\n'.  Written to FILE.tmp, fsync, rename.  A state made on another base image is
refused (the run stops before the first instruction): it would be garbage on a different image.
A blank chip (a device with BOOT_ELF: no flash image, every page erased) is a base of its own: its "SHA-1" is that of the
text 'blank NAND <chip> <pages> pages' (blank_key()), and the header names it ("base"). A state of a firmware of our own is
thus refused on a stock flash image, a state of a stock image on a blank chip, and a state of one blank geometry on another.

A program that builds the phone itself can keep the state instead of a file: it sets machine.flash_state to the bytes of
a state (b'' = none yet) before the attachment is made and takes the new one from FlashState.state() whenever it wants.
Nothing is written then and no signal handler is installed.

SIM_FLASH_OPLOG=FILE additionally lists every program / erase (emulated ms, page) and flags programs that
try to set bits back to 1 (a page that was not erased), for diagnosis.
"""
import atexit
import hashlib
import json
import os
import signal
import struct
import sys
import time
import zlib

MAGIC = b'C905FLASH1\n'
PAGE_RAW = 0x840
BLOCK_PAGES = 64
FF_PAGE = b'\xff' * PAGE_RAW


def read_state(path, d=None):
    """(header dict, {page: bytes}) of a state file, or of its bytes `d`."""
    if d is None:
        with open(path, 'rb') as f:
            d = f.read()
    assert d.startswith(MAGIC) and d.endswith(b'END\n'), '%s: not a complete flash state file' % path
    nl = d.index(b'\n', len(MAGIC))
    hdr = json.loads(d[len(MAGIC):nl])
    pages, off = {}, nl + 1
    while off < len(d) - 4:
        blk, bitmap, n = struct.unpack_from('<IQI', d, off)
        raw = zlib.decompress(d[off + 16:off + 16 + n])
        off += 16 + n
        idx = [i for i in range(BLOCK_PAGES) if bitmap >> i & 1]
        assert len(raw) == len(idx) * PAGE_RAW
        for k, i in enumerate(idx):
            pages[blk * BLOCK_PAGES + i] = raw[k * PAGE_RAW:(k + 1) * PAGE_RAW]
    assert len(pages) == hdr['pages']
    return hdr, pages


def blank_key(chip):
    """(key, description) of the base of a blank chip (no image; nand_model.NandChip of b''), else None."""
    if len(chip.mm):
        return None
    what = 'blank NAND %s %d pages' % (chip.chip, chip.pages)
    return hashlib.sha1(what.encode()).hexdigest(), what


class FlashState:
    def __init__(self, m, irq, path, data=None):
        self.m, self.irq, self.path = m, irq, path
        self.data = data                # path None: the state is the caller's, these bytes (see state())
        self.nand = next((d.s for _, _, d, _ in m.bus.ranges if hasattr(getattr(d, 's', None), 'chip')), None)
        if self.nand is None:
            sys.exit('flash_state: the machine has no NAND model: there is no flash to keep')
        chip = self.chip = self.nand.chip
        blank = blank_key(chip)
        self.base_sha1, self.base = blank or (hashlib.sha1(chip.mm).hexdigest(), None)
        self.base_size = len(chip.mm)
        self.quiet_ns = int(float(os.environ.get('SIM_FLASH_QUIET', '1500')) * 1e6)
        self.interval_ns = int(float(os.environ.get('SIM_FLASH_INTERVAL', '10')) * 1e9)
        self.grace = float(os.environ.get('SIM_FLASH_GRACE', '3'))
        self.blobs = {}                 # block -> (bitmap, compressed pages), kept between saves
        self.dirty = set()              # blocks touched since their blob was made
        self.unsaved = False
        self.last_op_ns = None
        self.last_save_ns = 0
        self.stop_at = None             # host time of the stop request
        self.n_prog = self.n_erase = self.n_saves = self.n_unerased = 0
        self.loaded = 0
        self.note = ''
        self.oplog = open(os.environ['SIM_FLASH_OPLOG'], 'w') if os.environ.get('SIM_FLASH_OPLOG') else None
        if data if path is None else os.path.exists(path):
            hdr, pages = read_state(path, data)
            if hdr['base_sha1'] != self.base_sha1:
                name = lambda key, what: key[:12] + (' = ' + what if what else '')
                sys.exit('flash_state: %s was made on another flash image (base %s, this image %s): not loaded. '
                         'Remove it or point SIM_FLASH_STATE elsewhere.' % (path or 'the state given', name(hdr['base_sha1'], hdr.get('base')), name(self.base_sha1, self.base)))
            for p, data in pages.items():
                chip.overlay[p] = bytearray(data)
            self.dirty = {p // BLOCK_PAGES for p in pages}
            self.loaded = len(pages)
            self.pack()                 # now, before the phone runs: the first save then packs only what the run changed
        self.log('%s: %d pages loaded (base image %s)' % (path or 'state kept by the caller', self.loaded, self.base_sha1[:12] + (', ' + self.base if self.base else '')))

        prog, erase = chip._do_program, chip._do_erase

        def do_program(row):
            if self.oplog:
                old = chip.page_bytes(row)
                bad = any(b & ~o & 0xFF for o, b in zip(old, chip.buf))
                self.n_unerased += bad
                self.oplog.write('%.3f program %d %s%s\n' % (self.now() / 1e6, row, bytes(chip.buf[:12]).hex(), ' NOT-ERASED' if bad else ''))
            prog(row)
            self.n_prog += 1
            self.touch(row)

        def do_erase(row):
            erase(row)
            self.n_erase += 1
            if self.oplog:
                self.oplog.write('%.3f erase %d\n' % (self.now() / 1e6, row // BLOCK_PAGES * BLOCK_PAGES))
            self.touch(row)

        chip._do_program, chip._do_erase = do_program, do_erase

        def tick():
            if self.stop_at is not None or (self.unsaved and self.now() - self.last_save_ns >= self.interval_ns):
                self.tick()

        def due():
            """A stop was asked for: now. Unsaved flash: when the save interval has passed and the flash has been left alone
            for the quiet time (before that quiet() is false whatever the chip does, and tick() does nothing)."""
            if self.stop_at is not None: return 0
            if not self.unsaved: return None
            t = self.last_save_ns + self.interval_ns
            if self.last_op_ns is not None and not getattr(self.m, 'powered_off', False):
                t = max(t, self.last_op_ns + self.quiet_ns)
            return t

        if hasattr(irq, 'wrap_step'):
            irq.wrap_step(tick, due)
        else:
            step = irq.step
            def stepped():
                step()
                tick()
            irq.step = stepped
        if path is None:
            return
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self.on_signal)
        atexit.register(self.at_exit)

    def log(self, s):
        print('[flash_state] ' + s, flush=True)

    def now(self):
        self.irq.clock.sync(self.m.insns)
        return self.irq.clock.now_ns

    def touch(self, row):
        self.dirty.add(row // BLOCK_PAGES)
        self.unsaved = True
        self.last_op_ns = self.now()

    def quiet(self):
        c = self.chip
        if c.mode == 'prog' or c.cmd in (0x80, 0x85, 0x60) or c.prog_page is not None:
            return False
        if getattr(self.m, 'powered_off', False):     # the phone cut its own power: its last write is final
            return True
        return self.last_op_ns is None or self.now() - self.last_op_ns >= self.quiet_ns

    def on_signal(self, signum, frame):
        if self.stop_at is not None:            # second request: leave now, the last quiet state stays
            os._exit(1)
        self.stop_at = time.time()
        if hasattr(self.m, 'touched'): self.m.touched = True      # the scheduler looks at the steppers after the slice that runs now
        self.log('stop requested (signal %d): waiting for the flash to be quiet' % signum)

    def tick(self):
        if self.quiet():
            if self.unsaved:
                self.save()
            if self.stop_at is not None:
                self.leave('stopped at a quiet moment')
        elif self.stop_at is not None and time.time() - self.stop_at > self.grace:
            self.leave('flash still busy %.0f s after the stop request: the state of %.1f s (emulated) is kept, later writes are lost'
                       % (self.grace, self.last_save_ns / 1e9))

    def leave(self, why):
        """End the run from between two slices (not from inside a device callback): normal interpreter exit."""
        self.log(why)
        self.note = why
        self.log(self.summary())
        self.left = True
        sys.exit(0)

    def at_exit(self):
        if self.oplog:
            self.oplog.flush()
        if not self.unsaved or getattr(self, 'left', False):
            return
        if self.quiet():
            self.save()
            self.log('saved at the end of the run: ' + self.summary())
        else:
            self.log('run ended %.0f ms after a flash write: the state of %.1f s (emulated) is kept, later writes are lost'
                     % ((self.now() - self.last_op_ns) / 1e6, self.last_save_ns / 1e9))

    def pack(self):
        """Bring `blobs` up to date: every block touched since its blob was made is packed again."""
        chip = self.chip
        mm, img_pages, ov = chip.mm, chip.img_pages, chip.overlay
        for blk in self.dirty:
            bitmap, parts = 0, []
            for i in range(BLOCK_PAGES):
                p = blk * BLOCK_PAGES + i
                pg = ov.get(p)
                if pg is None:
                    continue
                base = mm[p * PAGE_RAW:(p + 1) * PAGE_RAW] if p < img_pages else FF_PAGE
                if pg != base:
                    bitmap |= 1 << i
                    parts.append(bytes(pg))
            if bitmap:
                self.blobs[blk] = (bitmap, zlib.compress(b''.join(parts), 1))
            else:
                self.blobs.pop(blk, None)
        self.dirty.clear()

    def save(self):
        self.nand.sync()
        self.pack()
        now = self.now()
        hdr = dict(base_sha1=self.base_sha1, base_size=self.base_size, blocks=len(self.blobs),
                   pages=sum(bin(b).count('1') for b, _ in self.blobs.values()), emu_ms=round(now / 1e6, 1))
        if self.base: hdr['base'] = self.base          # a blank chip: say which (a stock image's header stays as it was)
        data = [MAGIC + json.dumps(hdr).encode() + b'\n']
        for blk in sorted(self.blobs):
            bitmap, blob = self.blobs[blk]
            data.append(struct.pack('<IQI', blk, bitmap, len(blob)) + blob)
        data = b''.join(data) + b'END\n'
        if self.path is None:
            self.data = data
        else:
            tmp = self.path + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        self.unsaved = False
        self.last_save_ns = now
        self.n_saves += 1
        self.saved = hdr

    def state(self):
        """For the caller that keeps the state (path None): the flash as the bytes of a state file. It is the flash of this
        moment when the flash is quiet, else of the last quiet moment (b'' when there has been none and none was given)."""
        if self.unsaved and self.quiet():
            self.save()
        return self.data

    def summary(self):
        s = '%s: loaded %d pages; %d programs, %d erases; %d saves' % (self.path or 'state kept by the caller', self.loaded, self.n_prog, self.n_erase, self.n_saves)
        if self.n_saves:
            s += ', last at %.1f ms emulated (%d pages in %d blocks, %d bytes)' % (
                self.saved['emu_ms'], self.saved['pages'], self.saved['blocks'], len(self.data) if self.path is None else os.path.getsize(self.path))
        if self.oplog:
            s += '; programs onto pages that were not erased: %d' % self.n_unerased
        return s + ('; ' + self.note if self.note else '')


def attach(m, irq):
    data = getattr(m, 'flash_state', None)          # bytes: the program that built the machine keeps the state
    if data is not None:
        return FlashState(m, irq, None, bytes(data))
    path = os.environ.get('SIM_FLASH_STATE')
    return FlashState(m, irq, os.path.abspath(path)) if path else None
