"""APP 0xC0002000 (I2S0) and 0xC0003000 (I2S1): the application CPU's I2S / PCM blocks, as far as audio playback needs them.
    --attach emu_i2s:attach
 No unicorn import; emu_link.Dmac is used through
attach_port() only.

Hardware [V]:
    I2S0  base 0xC0002000  VIC line 10  DMA channels tx 21 / rx 22
    I2S1  base 0xC0003000  VIC line 12  DMA channels tx 23 / rx 24
What a driver does with the block [V code + register trace]:
    +0x00 +0x04 +0x2c +0x30 = 0, +0x28 = 0xffffffff at start; later +0x00 = 0x27, +0x2c / +0x28 = 0x20
          around each transmit start (enable and interrupt mask / clear by the look of it: [I], stored only)
    +0x08 read: bits 4:0 = transmit FIFO fill level; 0 with an idle DMA chain = under-run, the driver then restarts the
          chain [V]
    +0x14 transmit data: the destination of the tx DMA channel [V run: ch23 dst 0xC0003014]
    +0x18 control; bits 31:28 = hardware version, read once: >= 3 selects a 16-word FIFO, else 8 words [V]
    +0x1c +0x20 +0x24 clock dividers, written for 8000 / 16000 / 48000 Hz [V]
Playback stream seen: 1920-byte DMA buffers on channel 23, stereo s16. Rate: **44100 Hz** [V; EMU_I2S_RATE overrides].
The dividers stay at their 8000 Hz start-up values during playback, so the bit clock comes from outside (the codec chip),
which runs the output at 44100 Hz D_SetSampleRate: D:1 SampleRate:44100`)]. Drained at 48000 Hz
(the first assumption of this model) every note of a tune came out 48 / 44.1 too high and the tune 8 % too short.

Model:
  [V need] the tx data register is a DMA port that takes RATE * 4 bytes per second of emulated time; the DMA controller's own
      terminal-count interrupt (line 2) then paces the driver. Without it every buffer is copied at once.
  [I] +0x08 bits 4:0 = words accepted and not yet clocked out, at most the FIFO depth (8)
  [MOCK] burst allowance BURST bytes (EMU_I2S_BURST_US, default 8 ms): the hardware FIFO is 8 or 16 words; the model lets a
      transfer run ahead to absorb what the harness adds to the firmware's reaction time: an interrupt is taken at the next
      scheduler slice (200 us). 2 ms (the first value) was enough for the decoder paths; a MIDI synthesiser that makes each
      30 ms block with 15 APEX batches, one interrupt each = 3 ms, under-ran on every block (90 under-runs in 4 s; none with
      8 ms). The long-term rate is unchanged.
  [MOCK] version nibble 0; every other register is storage; the block's own interrupt (line 10 / 12) is never raised
  [MOCK] receive side (microphone, DMA 22 / 24): not modelled, never started by the firmware in any run so far; the rx data
      register offset is unknown, so an rx transfer would still be an immediate copy of zeros
Recording (off unless EMU_AUDIO_DIR or MOCK_AUDIO_DIR is set; the run is identical either way), per unit N with traffic:
    DIR/i2sN_tx.pcm    raw interleaved stereo s16le at RATE, append-only, only what the phone clocked out (idle time not padded)
    DIR/i2sN_tx.jsonl  line 1 {"rate", "channels", "format", "file"}; then one line per chunk, written AFTER its bytes are
                       flushed: {"t_ms": emulated time of the chunk's first byte, "offset": byte offset in the .pcm, "bytes"}.
                       A chunk ends after CHUNK bytes (100 ms) or when the stream pauses; gaps are the differences of t_ms.
"""
import atexit
import json
import os

DMA_BASE = 0xC0020000
RATE = int(os.environ.get('EMU_I2S_RATE', '44100'))
CHUNK = RATE * 4 // 10
BYTES_PER_S = RATE * 4
BURST = int(os.environ.get('EMU_I2S_BURST_US', '8000')) * BYTES_PER_S // 1_000_000 & ~3   # [MOCK] 8 ms = 1408 bytes, see the module text
GAP_NS = 30_000_000              # a pause longer than this closes a recorded burst


class I2s:
    def __init__(self, unit, base, now_ns, log, rec_dir=None):
        self.unit, self.base, self.now_ns, self.log = unit, base, now_ns, log
        self.name = 'I2S%d' % unit
        self.r = {}
        self.credit = BURST          # bytes the port may take now
        self.t = 0                   # time of the last credit update
        self.total = 0
        self.last_rx = None
        self.bursts = []             # [start_ns, end_ns, bytes, wav offset]
        self.rec_dir, self.pcm, self.side, self.chunk = rec_dir, None, None, None
        self.depth = 8
        self.dmac = None
        self.underruns = 0

    # ---- registers ------------------------------------------------------------------------------------
    def read(self, off, size):
        a = off & ~3
        v = self.r.get(a, 0)
        if a == 0x08:
            self._refill()
            v = (v & ~0x1f) | min(self.depth, (BURST - self.credit + 3) // 4)
        elif a == 0x18:
            v &= 0x0fffffff
        return (v >> (8 * (off & 3))) & ((1 << (8 * size)) - 1)

    def write(self, off, size, v):
        a = off & ~3
        if size != 4:
            sh = 8 * (off & 3); mask = ((1 << (8 * size)) - 1) << sh
            v = (self.r.get(a, 0) & ~mask) | ((v << sh) & mask)
        self.r[a] = v & 0xFFFFFFFF

    # ---- DMA port (emu_link.Dmac.attach_port) ------------------------------------------------------------
    def _refill(self):
        now = self.now_ns()
        add = (now - self.t) * BYTES_PER_S // 1_000_000_000
        if self.credit + add >= BURST:
            self.credit, self.t = BURST, now
        elif add > 0:
            self.credit += add
            self.t += add * 1_000_000_000 // BYTES_PER_S          # the fraction of a byte stays in the time base

    def dma_space(self):
        """Whole stereo frames only: the block shifts out complete samples. A transfer of 1..3 bytes would leave the DMA count,
        the driver's restart point and the record's chunk boundaries in the middle of a frame (a reader that decodes a chunk
        from its own offset then hears full-scale noise: seen with a stream that stops and restarts often)."""
        self._refill()
        return self.credit & ~3 if self.credit > 0 else 0

    def write_bytes(self, data):
        n = len(data)
        now = self.now_ns()
        self.credit -= n
        self.total += n
        if self.last_rx is None or now - self.last_rx > GAP_NS:
            if self.bursts and self.last_rx is not None:
                self.log('[i2s] %s tx burst ended: %.1f ms .. %.1f ms, %d bytes = %.3f s at %d Hz' % (
                    self.name, self.bursts[-1][0] / 1e6, self.bursts[-1][1] / 1e6, self.bursts[-1][2], self.bursts[-1][2] / BYTES_PER_S, RATE))
            self.bursts.append([now, now, 0, self.total - n])
            self.log('[i2s] %s tx burst starts at %.1f ms' % (self.name, now / 1e6))
        b = self.bursts[-1]
        b[1] = now; b[2] += n
        self.last_rx = now
        if self.rec_dir:
            if self.pcm is None:
                os.makedirs(self.rec_dir, exist_ok=True)
                self.pcm = open(os.path.join(self.rec_dir, 'i2s%d_tx.pcm' % self.unit), 'wb')
                self.side = open(os.path.join(self.rec_dir, 'i2s%d_tx.jsonl' % self.unit), 'w')
                self.side.write(json.dumps({'rate': RATE, 'channels': 2, 'format': 's16le', 'file': 'i2s%d_tx.pcm' % self.unit}) + '\n')
            if self.chunk is None:
                self.chunk = [now, self.total - n, 0]
            self.pcm.write(data)
            self.chunk[2] += n
            if self.chunk[2] >= CHUNK and not (self.chunk[1] + self.chunk[2]) & 3:      # chunks begin and end on a frame
                self.flush()

    def flush(self):
        """Close the open chunk: PCM bytes to disk first, then the side-car line that describes them."""
        if self.chunk is not None:
            self.pcm.flush()
            self.side.write(json.dumps({'t_ms': round(self.chunk[0] / 1e6, 3), 'offset': self.chunk[1], 'bytes': self.chunk[2]}) + '\n')
            self.side.flush()
            self.chunk = None

    def idle_check(self):
        if self.chunk is not None and self.now_ns() - self.last_rx > GAP_NS:
            self.flush()

    def waiting(self):
        """(channel, bytes left) of an active DMA transfer into this port, or None."""
        if self.dmac is None:
            return None
        for n, c in enumerate(self.dmac.ch):
            if c.active and c.dst == self.base + 0x14 and (c.ctrl & 0xFFF):
                return n, c.ctrl & 0xFFF
        return None

    def close(self):
        if self.pcm is not None:
            self.flush()
            self.pcm.close(); self.side.close()
            self.pcm = None

    def summary(self):
        return '%s: %d bytes transmitted (%.3f s at %d Hz stereo s16) in %d burst(s)%s' % (
            self.name, self.total, self.total / BYTES_PER_S, RATE, len(self.bursts),
            ''.join('\n    %.1f .. %.1f ms: %d bytes = %.3f s' % (s / 1e6, e / 1e6, n, n / BYTES_PER_S) for s, e, n, _ in self.bursts[:40]))


class I2sSystem:
    """Both blocks + the glue to the scheduler: pokes the DMA controller when a port can take more, and wakes an idle CPU."""

    def __init__(self, m, irq, log):
        self.m, self.irq = m, irq
        rec = os.environ.get('EMU_AUDIO_DIR') or os.environ.get('MOCK_AUDIO_DIR') or None
        now = lambda: irq.clock.now_ns
        self.units = [I2s(0, 0xC0002000, now, log, rec), I2s(1, 0xC0003000, now, log, rec)]
        for u in self.units:
            m.attach(u.base, 0x1000, u, u.name)
        self.dmac = None
        atexit.register(self.close)

    def _find(self):
        hit = self.m.bus.find(DMA_BASE)          # db3210 attaches the DMA controller after the --attach modules
        if hit is not None:
            self.dmac = hit[1]
            for u in self.units:
                u.dmac = self.dmac
                self.dmac.attach_port(u.base + 0x14, u)

    def tick(self):
        if self.dmac is None:
            self._find()
            return
        for u in self.units:
            u.idle_check()
        for u in self.units:
            if u.waiting() and u.dma_space() >= 4:
                self.dmac.poke()
                self.m.irq_pending = self.irq.vic.irq_out
                break

    # timer look-alike for IrqTimerSystem.timers
    def next_event_ns(self):
        t = None
        for u in self.units:
            w = u.waiting()
            if w:
                u._refill()
                need = min(w[1], BURST) - u.credit
                due = u.now_ns() + max(0, need) * 1_000_000_000 // BYTES_PER_S + 1
                t = due if t is None else min(t, due)
        return t

    def pending_events(self):
        t = self.next_event_ns()
        return [] if t is None else [(t, 'i2s: tx FIFO space', -1)]

    def advance(self):
        pass

    def close(self):
        for u in self.units:
            u.close()

    def summary(self):
        return '\n'.join(u.summary() for u in self.units)


def attach(m, irq):
    """db3210 --attach emu_i2s:attach"""
    s = I2sSystem(m, irq, lambda t: print(t, flush=True))
    irq.timers.append(s)
    def due():
        """After every slice while the DMA controller is not found or a transfer into a port is under way (the port's credit
        grows with time); else the moment a recorded chunk is closed. Nothing is changed here (no credit refill)."""
        if s.dmac is None: return 0
        t = None
        for u in s.units:
            if u.waiting(): return 0
            if u.chunk is not None:
                c = u.last_rx + GAP_NS + 1
                if t is None or c < t: t = c
        return t
    if hasattr(irq, 'wrap_step'):
        irq.wrap_step(s.tick, due)
    else:
        orig = irq.step
        def step():
            orig()
            s.tick()
        irq.step = step
    return s
