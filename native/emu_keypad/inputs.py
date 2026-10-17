"""The Inputs object: stable key names -> keypad matrix, switches -> whatever backend carries them, plus the control channel.

    inp.press('select'); inp.release('select'); inp.tap('5', ms=120); inp.set_switch('slide', 'open')

Control channel (`poll_file`): a JSON-lines file, one command per line, read incrementally (new lines only) once per `poll_ms` of EMULATED time.
    {"press":"select"}   {"release":"select"}   {"tap":"5","ms":120}   {"switch":"slide","state":"open"}   {"raw":27,"state":"down"}
Any line may carry "at_ms": the absolute emulated time to apply it (applied immediately when already in the past); lines without it are applied
at the poll that reads them. Every applied input is logged as `[sim] input t=<emulated ms> ...`.
"""
import importlib
import json
import os


def default_keymap():
    """The default key map module, emu_keypad/keymap.py (the stock key table), imported on first use only."""
    return importlib.import_module(__package__ + '.keymap')


class Inputs:
    def __init__(self, keypad, now_ns, log=print, poll_ms=20.0, ctl_path=None, pmic=None, keymap=None):
        self.km = keymap or default_keymap()    # a key map module: KEY_INDEX, KEY_CODE, ALIASES, SWITCHES (default: the stock map)
        self.kp = keypad
        self.now_ns = now_ns
        self.log = log
        self.poll_ms = poll_ms
        self.ctl_path = ctl_path
        self._pmic = pmic               # callable returning the Ab3100 model (or None); raise_event(a1=..) is used for the ON key / USB / charger
        self.switches = {n: s[0] for n, s in self.km.SWITCHES.items()}
        self.backends = {}              # switch name -> callable(state)  (extra backends, e.g. a GPIO model, can be registered here)
        self.sched = []                 # (time_ns, seq, fn, description)
        self._seq = 0
        self._ctl_pos = 0
        self._next_poll_ns = 0
        self.applied = []               # (time_ms, text) every applied input, for tests and the demo
        self.pmic_on_key = False        # also raise the PMIC ON-key event when 'end' goes down (AB3100 EVENTA1 bit0) [?]

    # ---- names ----
    def key_index(self, name):
        n = self.km.ALIASES.get(str(name).lower(), str(name).lower())
        if n not in self.km.KEY_INDEX:
            raise KeyError('unknown key %r (known: %s)' % (name, ' '.join(sorted(self.km.KEY_INDEX))))
        return n, self.km.KEY_INDEX[n]

    def is_down(self, name):
        return self.key_index(name)[1] in self.kp.down

    def _note(self, text):
        t = self.now_ns() / 1e6
        self.applied.append((t, text))
        self.log('[sim] input t=%.3f ms %s' % (t, text))

    # ---- immediate actions ----
    def press(self, name):
        n, i = self.key_index(name)
        if n == 'camera_full' and self.km.KEY_INDEX['camera_half'] not in self.kp.down:
            self.press('camera_half')   # two-stage shutter: the focus contact closes first
        self.kp.press(i)
        code = getattr(self.km, 'KEY_CODE', {}).get(n)          # a key map of a firmware of our own has no stock key codes
        self._note('press %s (key index %d, %srow %d col %d)' % (n, i, '' if code is None else 'HAL code %#x, ' % code, i // 6, i % 6))
        if n == 'end' and self.pmic_on_key:
            self._pmic_event(a1=0x01, why='ON key')

    def release(self, name):
        n, i = self.key_index(name)
        self.kp.release(i)
        self._note('release %s (key index %d)' % (n, i))

    def raw(self, index, down=True):
        (self.kp.press if down else self.kp.release)(index)
        self._note('raw index %d %s' % (index, 'down' if down else 'up'))

    def tap(self, name, ms=120.0):
        """Press now, release `ms` emulated milliseconds later."""
        self.press(name)
        self.schedule(self.now_ns() / 1e6 + ms, lambda: self.release(name), 'release ' + name)

    def set_switch(self, name, state):
        name = str(name).lower()
        switches = self.km.SWITCHES
        if name not in switches:
            raise KeyError('unknown switch %r (known: %s)' % (name, ' '.join(switches)))
        if state not in switches[name]:
            raise ValueError('switch %s: state %r not in %s' % (name, state, switches[name]))
        old, self.switches[name] = self.switches[name], state
        how = self._apply_switch(name, state)
        self._note('switch %s %s -> %s%s' % (name, old, state, ' [%s]' % how if how else ''))

    def _pmic_event(self, why, **bits):
        p = self._pmic() if self._pmic else None
        if p is None:
            return 'no PMIC model attached'
        p.raise_event(**bits)
        return 'PMIC event %s (%s)' % (', '.join('%s=%#x' % kv for kv in bits.items()), why)

    def _apply_switch(self, name, state):
        if name in self.backends:
            self.backends[name](state)
            return 'backend'
        if name == 'lens_cover':
            # [?] the key table has a camera on/off key on direct line 32; whether the lens cover drives it, and with which polarity, is not confirmed
            (self.kp.press if state == 'open' else self.kp.release)(self.km.KEY_INDEX['camera_onoff'])
            return 'drives key camera_onoff (index 32) down while open [?]'
        if name == 'usb' and state == 'in':
            return self._pmic_event('VBUS', a1=0x40)
        if name == 'charger' and state == 'in':
            return self._pmic_event('DCIO charger', a1=0x08)
        if name == 'slide':
            return 'no hardware path known: recorded only [?]'
        return 'recorded only [?]'

    # ---- timeline ----
    def schedule(self, at_ms, fn, desc=''):
        self._seq += 1
        self.sched.append((int(at_ms * 1e6), self._seq, fn, desc))
        self.sched.sort(key=lambda x: (x[0], x[1]))

    def next_event_ns(self):
        return self.sched[0][0] if self.sched else None

    def pending_events(self):
        return [(t, 'input: ' + d, 0) for t, _s, _f, d in self.sched]

    def advance(self):
        """Run due scheduled actions and poll the control file; called between slices."""
        now = self.now_ns()
        while self.sched and self.sched[0][0] <= now:
            _t, _s, fn, _d = self.sched.pop(0)
            fn()
        if self.ctl_path and now >= self._next_poll_ns:
            self._next_poll_ns = now + int(self.poll_ms * 1e6)
            self.poll_file()

    # ---- control channel ----
    def poll_file(self):
        try:
            size = os.stat(self.ctl_path).st_size
        except OSError:
            return 0
        if size < self._ctl_pos:
            self._ctl_pos = 0           # truncated: start over
        if size == self._ctl_pos:
            return 0
        with open(self.ctl_path, 'rb') as f:
            f.seek(self._ctl_pos)
            data = f.read()
        end = data.rfind(b'\n')
        if end < 0:
            return 0                    # no complete line yet
        self._ctl_pos += end + 1
        n = 0
        for line in data[:end].decode('utf-8', 'replace').splitlines():
            line = line.strip()
            if line:
                n += self.command(line)
        return n

    def command(self, line):
        """Apply one JSON command (str or dict). Returns 1 if accepted (immediately or scheduled), 0 on error (logged)."""
        try:
            c = json.loads(line) if isinstance(line, str) else dict(line)
            at = c.get('at_ms')
            if at is not None and float(at) * 1e6 > self.now_ns():
                c = {k: v for k, v in c.items() if k != 'at_ms'}
                self.schedule(float(at), lambda c=c: self.command(c), 'command ' + json.dumps(c))
                return 1
            if 'press' in c: self.press(c['press'])
            elif 'release' in c: self.release(c['release'])
            elif 'tap' in c: self.tap(c['tap'], float(c.get('ms', 120)))
            elif 'switch' in c: self.set_switch(c['switch'], c['state'])
            elif 'raw' in c: self.raw(int(c['raw']), c.get('state', 'down') == 'down')
            else: raise ValueError('no known verb in %r' % (c,))
            return 1
        except Exception as e:
            self.log('[sim] input t=%.3f ms REJECTED %r: %s' % (self.now_ns() / 1e6, line, e))
            return 0
