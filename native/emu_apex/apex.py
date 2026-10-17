"""APP 0xC0038000 (work memory) / 0xC003A000 (command port, registers, output FIFO): the "APEX" block.
    --attach emu_apex:attach
 No unicorn import; emu_link.Dmac is used
through attach_port() / attach_mem() only.

What the block is [V code + run, I where marked]: the hardware half of a MIDI synthesiser. The software half parses the MIDI file and, every 2 ms tick, computes one
0x30-byte command per sounding voice (envelope, LFO, pitch, filter, and the address / loop points of the instrument's
waveform); the block plays the waveforms and mixes. The default instrument set is addressed inside
the block (command words 1 / 4) and is never uploaded: no DMA or CPU access to the block happens before the first voice
command, so the samples are in the chip's own ROM [I]. They are not in the software, which is why this model cannot
produce the sound.

Transport, all through the DMA controller [V]:
    channel 20, memory -> 0xC003A000   command blocks of 0x30 bytes: the clients' voice commands (word 0 = 0x4004xxxx), then one
                                       of the driver's closing commands
    channel 36, memory -> memory       8 bytes -> +0x2034 (2, 0); the clients' loads into the work memory (0x480 bytes at
                                       0xC0038000 seen); 4 bytes -> +0x2030 (0xc); 8 bytes -> +0x203c (1, 0): written last = start [I]
    channel 19, 0xC003A7FC -> memory   the result stream; its terminal count is the driver's only completion event. Layout the driver expects: the
                                       clients' result bytes (2 per voice command, total rounded up to 4), 0 / 4 / 8 filler
                                       bytes, then, if a client reads work memory back, 0x480 bytes of it from 0xC0038000.
    The block's interrupt (line 21) is not used by the driver.

Model:
  [V need] command port, work memory (0x2000 bytes), registers as storage, result FIFO; a batch completes DELAY after the start
      write, with exactly as many result bytes as the driver programmed on channel 19.
  [V need] one 16-bit status word per voice command: bits 6:0 the voice number of the command (word 0 bits 25:19), bits 14:7
      non-zero while the voice sounds (the client frees a voice on zero). Zero is returned when an
      unlooped (one-shot) waveform has been played to its last sample; looped voices are ended by the software's envelope.
  [V fields, I arithmetic] the signal path of a voice command (_voice): phase step w1 / 2^21 chip samples per output sample,
      start index w2 >> 16, loop [w3 >> 16, w3 & 0xffff), last index w2 & 0xffff, flags w0 bit0 looped / bit1 note start /
      bit2 filter; filter y = 4 b x - 2 c1 y1 - 2 c2 y2 with b = w6 low, c1 = w7 high, c2 = w7 low (Q15:
      unity gain at 0 Hz); gains Q15: w5, then w10 high / low for the two mix buffers at word addresses w8 >> 12 / w8 & 0xfff
      and w11 high / low for the effect buffers w9 >> 12 / w9 & 0xfff; w6 bits 22.. = this voice is the first into that buffer
      in this tick: overwrite instead of add (nothing else clears the buffers). 64 samples s16 per buffer and tick.
  [MOCK: substitute waveforms] what the voices play: EMU_APEX_WAVES = tones (default; generated per waveform address) |
      sf2:PATH (a SoundFont, mapped by General MIDI program and key) | silence. See waves.py. Linear interpolation; effect
      buffers are filled but no effect command has been seen or modelled; EMU_APEX_GAIN scales the output (default 1).
  [MOCK] DELAY_NS (EMU_APEX_DELAY_US, default 0): execution time of a batch. Not known; 64 samples of a few voices are far
      below the 2 ms tick on clocked hardware. With 0 the results are in the FIFO when the start write returns, so channel 19
      completes inside that DMA register write. A non-zero value is rounded up to the scheduler slice (200 us) by the harness:
      100 us made every 30 ms block of 15 ticks arrive about 3 ms late and the I2S driver under-run on each block.
"""
import os
import struct

from .waves import make as make_waves

BASE, SIZE = 0xC0038000, 0x3000
MEM_SIZE = 0x2000
CMD_PORT, FIFO_PORT = 0xC003A000, 0xC003A7FC
REG_START = 0x203c
DUMP = 0x480
FRAME = 64                       # samples per voice command (word 0 bits 18:12; one 2 ms tick at 32 kHz)
DELAY_NS = int(os.environ.get('EMU_APEX_DELAY_US', '0')) * 1000      # [MOCK] execution time of a batch; 0 = done within the start write
DMA_BASE = 0xC0020000


class _Cmd:
    """DMA destination 0xC003A000: command blocks."""
    def __init__(self, apex): self.apex = apex
    def dma_space(self): return 0x1000
    def write_bytes(self, data): self.apex._commands(bytes(data))


class _Voice:
    __slots__ = ('rom', 'pos', 'wave', 'y1', 'y2', 'done')


class Apex:
    def __init__(self, now_ns, log=None, waves=None):
        self.now_ns, self.log = now_ns, log or (lambda s: None)
        self.mem = bytearray(MEM_SIZE)
        self.r = {}                      # register offset (from 0xC003A000) -> value
        self.cmd_port = _Cmd(self)
        self.dmac = None
        self._part = b''
        self.queued = []                 # command blocks (12 words each) since the last start
        self.ready_at = None             # emulated time at which the running batch has its results
        self.out = None
        self.batches = self.commands = self.result_bytes = 0
        self.opcodes = {}                # word 0 >> 16 -> count
        self.last = None
        self.delay_ns = DELAY_NS
        self.waves = waves if waves is not None else make_waves(os.environ.get('EMU_APEX_WAVES'), self.log)
        self.voices = {}                 # voice number -> _Voice
        self.gain = float(os.environ.get('EMU_APEX_GAIN', '1.0'))
        self.notes = self.finished = 0
        self.peak = 0
        t = os.environ.get('EMU_APEX_TRACE')     # debugging aid: every command of every batch, one line each (time ms, batch, 12 words)
        self.trace = open(t, 'w') if t else None

    # ---- bus (CPU accesses; the driver makes none, everything goes through the DMA controller) ----
    def read(self, off, size):
        if off < MEM_SIZE:
            return int.from_bytes(self.mem[off:off + size], 'little')
        return (self.r.get((off - MEM_SIZE) & ~3, 0) >> (8 * (off & 3))) & ((1 << (8 * size)) - 1)

    def write(self, off, size, v):
        self.dma_write(off, (v & ((1 << (8 * size)) - 1)).to_bytes(size, 'little'))

    # ---- memory-to-memory DMA items (Dmac.attach_mem) ----
    def dma_read(self, off, n):
        if off < MEM_SIZE:
            return bytes(self.mem[off:off + n]).ljust(n, b'\0')
        return b''.join(((self.r.get((off + i - MEM_SIZE) & ~3, 0) >> (8 * ((off + i) & 3))) & 0xff).to_bytes(1, 'little') for i in range(n))

    def dma_write(self, off, data):
        if off < MEM_SIZE:
            self.mem[off:off + len(data)] = data[:MEM_SIZE - off]
            return
        start = False
        for i, b in enumerate(data):
            a = (off + i - MEM_SIZE) & ~3; sh = 8 * ((off + i) & 3)
            self.r[a] = (self.r.get(a, 0) & ~(0xff << sh)) | (b << sh)
            if a == REG_START - MEM_SIZE: start = True
        if start and self.r.get(REG_START - MEM_SIZE, 0) & 1:
            self._start()

    # ---- command port ----
    def _commands(self, data):
        data = self._part + data
        n = len(data) // 0x30
        for i in range(n):
            w = struct.unpack_from('<12I', data, 0x30 * i)
            self.queued.append(w)
            op = w[0] >> 16
            if op not in self.opcodes:
                self.log('[apex] first command with word 0 = %#06x....: %s' % (op, ' '.join('%08x' % x for x in w)))
            self.opcodes[op] = self.opcodes.get(op, 0) + 1
        self.commands += n
        self._part = data[0x30 * n:]

    def _start(self):
        if not self.queued:
            return                       # loads only: nothing to execute, the DMA chain's own terminal count ends the batch
        self.last = self.queued
        self.queued = []
        self.batches += 1
        if self.trace:
            for w in self.last:
                self.trace.write('%.3f %d %s\n' % (self.now_ns() / 1e6, self.batches, ' '.join('%08x' % x for x in w)))
        self.ready_at = self.now_ns() + self.delay_ns
        self.out = None
        self.status = [self._voice(w) for w in self.last if w[0] & 0x40000000]

    def _voice(self, w):
        """One voice command = FRAME samples of one voice, mixed into the buffers in the work memory. Returns its status word.
        Fields as a builder writes them [V]; the arithmetic is the plain reading of those fields [I]:
        linear interpolation instead of the block's interpolator (word 0 bits 7:4 = 11, its order by the look of it)."""
        vn = (w[0] >> 19) & 0x7f
        looped, start, filt = w[0] & 1, w[0] & 2, w[0] & 4
        n = (w[0] >> 12) & 0x7f or FRAME
        step = w[1] / 2097152.0                                   # 16.16 phase step << 5: chip samples per output sample
        first, loop_start, end, last = w[2] >> 16, w[3] >> 16, w[3] & 0xffff, w[2] & 0xffff
        v = self.voices.get(vn)
        if start or v is None:
            v = self.voices[vn] = _Voice()
            v.rom, v.pos, v.y1, v.y2, v.done = float(first), 0.0, 0.0, 0.0, False
            v.wave = self.waves.get(w[4], loop_start, end, last, bool(looped))
            self.notes += 1
        s16 = lambda x: x - 0x10000 if x & 0x8000 else x
        dests = []                                               # (byte offset in the work memory, gain, overwrite)
        clear = w[6] >> 22
        pre = s16(w[5] & 0xffff) / 32768.0 * self.gain
        for addr, g, clr in (((w[8] >> 12) & 0xfff, w[10] >> 16, clear & 1), (w[8] & 0xfff, w[10] & 0xffff, clear & 2),
                             ((w[9] >> 12) & 0xfff, w[11] >> 16, clear & 4), (w[9] & 0xfff, w[11] & 0xffff, clear & 8)):
            if (g or clr) and 2 * addr + 2 * n <= MEM_SIZE:
                dests.append((2 * addr, s16(g) / 32768.0 * pre, clr))
        wave, out = v.wave, None
        if wave is not None and not v.done:
            data, wn, wloop = wave.data, wave.n, wave.loop if looped else None
            adv, pos, rom = step * wave.ratio, v.pos, v.rom
            b0, c1, c2 = 4.0 * s16(w[6] & 0xffff) / 32768.0, 2.0 * s16(w[7] >> 16) / 32768.0, 2.0 * s16(w[7] & 0xffff) / 32768.0
            y1, y2 = v.y1, v.y2
            out = [0.0] * n
            for i in range(n):
                if not looped and rom >= last:                    # the chip's one-shot waveform is over
                    v.done = True
                    break
                k = int(pos)
                if k + 1 < wn:
                    x = data[k]; x += (data[k + 1] - x) * (pos - k)
                elif k < wn:
                    x = data[k] if wloop is None else data[k] + (data[wloop[0]] - data[k]) * (pos - k)
                else:
                    x = 0.0                                       # the stand-in is shorter than the chip's waveform
                if filt:                                          # y = 4 b x - 2 c1 y1 - 2 c2 y2
                    x = b0 * x - c1 * y1 - c2 * y2
                    y2, y1 = y1, x
                out[i] = x
                pos += adv; rom += step
                if wloop is not None and pos >= wloop[1]:
                    pos -= wloop[1] - wloop[0]
                if looped and end > loop_start and rom >= end:
                    rom -= end - loop_start
            v.pos, v.rom, v.y1, v.y2 = pos, rom, y1, y2
        else:
            rom = v.rom + step * n                                # no waveform: only the position moves
            if looped and end > loop_start:
                while rom >= end: rom -= end - loop_start
            elif not looped and rom >= last:
                v.done = True
            v.rom = rom
        mem = self.mem
        for off, g, clr in dests:
            cur = [0] * n if clr else list(struct.unpack_from('<%dh' % n, mem, off))
            if out is not None and g:
                for i in range(n):
                    y = cur[i] + int(out[i] * g)
                    cur[i] = 32767 if y > 32767 else -32768 if y < -32768 else y
                pk = max(max(cur), -min(cur))
                if pk > self.peak: self.peak = pk
            struct.pack_into('<%dh' % n, mem, off, *cur)
        if v.done:
            self.finished += 1
            del self.voices[vn]
            return vn                                             # status 0: the client frees the voice
        return vn | 0x80

    # ---- result FIFO (DMA source 0xC003A7FC) ----
    def waiting(self):
        """Bytes the DMA controller still wants from the FIFO, or 0."""
        if self.dmac is not None:
            for c in self.dmac.ch:
                if c.active and c.src == FIFO_PORT:
                    return c.ctrl & 0xFFF
        return 0

    def dma_avail(self):
        if self.out is None:
            if self.ready_at is None or self.now_ns() < self.ready_at:
                return 0
            total = self.waiting()
            if not total:
                return 0
            # One status word per voice command, in command order: bits 6:0 = the command's voice number (word 0 bits 25:19),
            # bits 14:7 non-zero = the voice still sounds (the reader: zero frees the voice, a number outside
            # the client's range aborts its bookkeeping). The total length is the driver's own (module text).
            res = b''.join(struct.pack('<H', x) for x in self.status)
            body = total - DUMP if total >= DUMP else total
            self.out = res[:body].ljust(body, b'\0') + (bytes(self.mem[:DUMP]) if total >= DUMP else b'')
            self.result_bytes += total
            self.ready_at = None
        return len(self.out)

    def read_bytes(self, n):
        d, self.out = self.out[:n], self.out[n:]
        if not self.out:
            self.out = None
        return d

    def summary(self):
        used = getattr(self.waves, 'used', None)
        return 'APEX: %d batches, %d commands (%d voice numbers), %d notes started, %d one-shot waveforms ended, %d result bytes; waveforms: %s%s; peak of the mix buffers %d%s' % (
            self.batches, self.commands, sum(1 for op in self.opcodes if op & 0x4000), self.notes, self.finished, self.result_bytes, self.waves.name,
            '' if self.waves.name == 'silence' else ' [MOCK: substitute waveforms]', self.peak,
            ''.join('\n    waveform %#06x <- %s' % kv for kv in sorted(used.items())) if used else '')


class ApexSystem:
    """The block + glue: finds the DMA controller, lets it run when a batch is done, wakes an idle CPU for that moment."""

    def __init__(self, m, irq, log):
        self.m, self.irq = m, irq
        self.apex = Apex(lambda: irq.clock.now_ns, log)
        m.attach(BASE, SIZE, self.apex, 'APEX')
        self.dmac = None

    def _find(self):
        hit = self.m.bus.find(DMA_BASE)          # db3210 attaches the DMA controller after the --attach modules
        if hit is not None and hasattr(hit[1], 'attach_mem'):
            self.dmac = self.apex.dmac = hit[1]
            self.dmac.attach_port(CMD_PORT, self.apex.cmd_port)
            self.dmac.attach_port(FIFO_PORT, self.apex)
            self.dmac.attach_mem(BASE, SIZE, self.apex)

    def tick(self):
        if self.dmac is None:
            self._find()
            return
        a = self.apex
        if a.ready_at is not None and self.irq.clock.now_ns >= a.ready_at and a.waiting():
            self.dmac.poke()
            self.m.irq_pending = self.irq.vic.irq_out

    # timer look-alike for IrqTimerSystem.timers
    def next_event_ns(self):
        a = self.apex
        return a.ready_at if a.ready_at is not None and a.waiting() else None

    def pending_events(self):
        t = self.next_event_ns()
        return [] if t is None else [(t, 'apex: batch done', -1)]

    def advance(self):
        pass

    def summary(self):
        return self.apex.summary()


def attach(m, irq):
    """db3210 --attach emu_apex:attach"""
    s = ApexSystem(m, irq, lambda t: print(t, flush=True))
    irq.timers.append(s)
    def due():                          # still looking for the DMA controller; else the batch that the DMA controller waits for
        if s.dmac is None: return 0
        a = s.apex
        return a.ready_at if a.ready_at is not None and a.waiting() else None
    if hasattr(irq, 'wrap_step'):
        irq.wrap_step(s.tick, due)
    else:
        orig = irq.step
        def step():
            orig()
            s.tick()
        irq.step = step
    return s
