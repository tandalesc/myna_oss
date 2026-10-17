"""Waveform sources for the APEX voice engine (apex.py). The chip's own instrument samples are not available (they are inside
the block), so every source here is a stand-in:
    silence     no waveform: voices are tracked (position, end of a one-shot) but add nothing
    tones       [MOCK: substitute waveforms] generated: one single-cycle harmonic waveform per waveform address for looped
                voices, a decaying noise / thump burst for one-shots; deterministic from the address
    sf2:PATH    [MOCK: substitute waveforms] samples of a SoundFont chosen by General MIDI program and key (drum kit: bank 128
                by key). The file stays where the user keeps it; nothing of it is copied. Missing / malformed -> tones.
An instrument table, if the device profile names one (WAVES: a JSON file of the waveform addresses), tells a source the pitch
a waveform has at phase step 1 and which program / key range uses it.
A source returns Wave objects: data (sequence of numbers, 16-bit scale), n, loop (start, end) or None, ratio = source samples
per unit of the engine's phase (the engine's phase counts samples of the chip's waveform).
"""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
RATE = 32000                     # the synthesiser's output rate
CYCLE = 512                      # samples in a generated single cycle
note_hz = lambda k: 440.0 * 2.0 ** ((k - 69) / 12.0)


def table_path():
    """The instrument table of the selected device (native/devices), or None if its profile names none."""
    try:
        import devices
        return getattr(devices.load(), 'WAVES', None)
    except ImportError:
        return None


def has_bank():
    """Whether the selected device's profile names an instrument bank to make the table from (WAVE_BANK)."""
    try:
        import devices
        return getattr(devices.load(), 'WAVE_BANK', None) is not None
    except ImportError:
        return False


class Wave:
    __slots__ = ('data', 'n', 'loop', 'ratio', 'name')

    def __init__(self, data, loop, ratio, name):
        self.data, self.n, self.loop, self.ratio, self.name = data, len(data), loop, ratio, name


class Table:
    """The instrument table of a device: regions by command key (address, loop start, end, last index) and by address.
    path: default the selected device profile's WAVES. No file, or no WAVES in the profile: an empty table."""

    def __init__(self, path=None):
        self.by_key, self.by_addr, self.regions = {}, {}, []
        self.path = path or table_path()
        try:
            self.regions = json.load(open(self.path))['regions']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        for r in sorted(self.regions, key=lambda r: (not 0 <= r['program'] < 128, r['program'] < 0, r['program'], r['region'])):
            self.by_key.setdefault((r['addr'], r['loop_start'], r['end'], r['last']), []).append(r)
            self.by_addr.setdefault(r['addr'], []).append(r)

    def candidates(self, addr, loop_start, end, last, looped):
        """Regions a command with these fields can come from, programs in ascending order, the drum kit and unreachable ones last."""
        c = self.by_key.get((addr, loop_start, end, last)) or self.by_addr.get(addr) or []
        return [r for r in c if bool(r['looped']) == bool(looped)] or list(c)

    def region(self, addr, loop_start, end, last, looped):
        c = self.candidates(addr, loop_start, end, last, looped)
        return c[0] if c else None


def _rng(seed):
    x = (seed * 2654435761 + 12345) & 0xFFFFFFFF
    while True:
        x = (x * 1664525 + 1013904223) & 0xFFFFFFFF
        yield x / 4294967296.0


class Silence:
    name = 'silence'
    def get(self, addr, loop_start, end, last, looped):
        return None


class Tones:
    name = 'tones'

    def __init__(self, table, log=None):
        self.table, self.cache = table, {}

    def get(self, addr, loop_start, end, last, looped):
        k = (addr, loop_start, end, last, looped)
        if k not in self.cache:
            self.cache[k] = self._make(*k)
        return self.cache[k]

    def _root_hz(self, addr, loop_start, end, last, looped):
        r = self.table.region(addr, loop_start, end, last, looped)
        if r: return note_hz(r['root_key'])
        n = end - loop_start
        return RATE / n if looped and n > 0 else RATE / 64.0       # unknown address: take the loop for one cycle

    def _make(self, addr, loop_start, end, last, looped):
        g = _rng(addr)
        if looped:
            # soft, slightly different per address: harmonics falling as 1 / k ** p, even ones weakened
            p, even, nh = 1.4 + 1.2 * next(g), 0.2 + 0.6 * next(g), 3 + int(6 * next(g))
            amp = [(1.0 / k ** p) * (even if k % 2 == 0 else 1.0) for k in range(1, nh + 1)]
            cyc = [sum(a * math.sin(2 * math.pi * (k + 1) * i / CYCLE) for k, a in enumerate(amp)) for i in range(CYCLE)]
            peak = max(abs(v) for v in cyc)
            data = [v * 20000.0 / peak for v in cyc]
            return Wave(data, (0, CYCLE), self._root_hz(addr, loop_start, end, last, looped) * CYCLE / RATE, 'tone %#x' % addr)
        # one-shot: a noise burst with a pitched thump, as long as the chip's waveform
        n = max(64, last)
        f0, noise, decay = 0.004 + 0.03 * next(g), 0.3 + 0.7 * next(g), 3.0 + 5.0 * next(g)
        data, lp, ph = [], 0.0, 0.0
        for i in range(n):
            e = math.exp(-decay * i / n)
            lp += 0.5 * ((next(g) * 2 - 1) - lp)
            ph += f0 * (0.5 + e)
            data.append(20000.0 * e * (noise * lp * 1.6 + (1 - noise) * math.sin(2 * math.pi * ph)))
        return Wave(data, None, 1.0, 'burst %#x' % addr)


class Sf2Waves:
    def __init__(self, path, table, log=None):
        from .sf2 import Sf2
        self.sf, self.table, self.log = Sf2(path), table, log or (lambda s: None)
        self.name = 'sf2:' + path
        self.tones, self.cache, self.used = Tones(table), {}, {}

    def get(self, addr, loop_start, end, last, looped):
        k = (addr, loop_start, end, last, looped)
        if k not in self.cache:
            w = None
            try:
                w = self._make(*k)
            except Exception as e:           # a damaged file must never stop the phone
                self.log('[apex] sound font: waveform %#x not usable (%s: %s), generated tone instead' % (addr, type(e).__name__, e))
            self.cache[k] = w or self.tones.get(*k)
        return self.cache[k]

    @staticmethod
    def _where(r):
        if r['program'] == 128: return 128, 0, r['lokey']                             # the drum kit: one key per region
        if 0 <= r['program'] < 128: return 0, r['program'], (max(r['lokey'], 21) + r['hikey']) // 2
        return None

    def _make(self, addr, loop_start, end, last, looped):
        """Several programs share most waveform addresses, and a layered program has several samples per key. The command names
        only the address, so: the sample that most of the programs using this address have for their key range wins (ties:
        the lowest program), and it is taken from the lowest program that has it."""
        cands = [r for r in self.table.candidates(addr, loop_start, end, last, looped) if self._where(r)]
        votes, first = {}, {}
        for r in cands:
            for si in dict.fromkeys(self.sf.layers(*self._where(r))):
                votes[si] = votes.get(si, 0) + 1
                first.setdefault(si, r)
        if not votes: return None
        si = max(votes, key=lambda k: (votes[k], -list(votes).index(k)))
        r = first[si]
        bank, prog, key = self._where(r)
        z = self.sf.find(bank, prog, key, sample=si)
        if z is None: return None
        data = self.sf.samples(z['offset'], z['length'])
        if len(data) < 2: return None
        ratio = note_hz(r['root_key']) / note_hz(z['root']) * 2.0 ** (z['cents'] / 1200.0) * z['rate'] / RATE
        self.used[addr] = '%s (bank %d program %d key %d)' % (z['name'], bank, prog, key)
        return Wave(data, (z['loop_start'], z['loop_end']) if z['looped'] else None, ratio, z['name'])


def make(spec, log=None):
    """EMU_APEX_WAVES value -> source. Never raises: anything unusable falls back to tones with one log line."""
    log = log or (lambda s: None)
    table = Table()
    if not table.regions and not table.path and not has_bank():
        log('[apex] the device has no instrument table: generated tones, pitch assumes one cycle per loop')
    elif not table.regions:
        log('[apex] instrument table %s not found (it is made from the firmware when the profile gives WAVE_BANK): generated tones, pitch assumes one cycle per loop'
            % (os.path.basename(table.path) if table.path else 'of this device'))
    spec = (spec or 'tones').strip()
    if spec == 'silence': return Silence()
    if spec.startswith('sf2:'):
        try:
            s = Sf2Waves(spec[4:], table, log)
            log('[apex] waveforms from sound font %s (%s; %d presets, %d samples) [MOCK: substitute waveforms]' % (
                spec[4:], s.sf.info.get('INAM', '?'), len(s.sf.phdr) - 1, len(s.sf.shdr) - 1))
            return s
        except Exception as e:
            log('[apex] sound font not usable (%s: %s): generated tones instead' % (type(e).__name__, e))
    elif spec != 'tones':
        log('[apex] EMU_APEX_WAVES=%r not understood (silence | tones | sf2:PATH): generated tones' % spec)
    return Tones(table)
