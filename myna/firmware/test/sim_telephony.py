#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Myna's telephony through the simulator, driven by keys on Myna's own screens: the AT modem stand-in with the "host"
cell network, which this script plays (it takes what the phone sends, answers it, and hands in messages for the
phone).

    make -C myna/firmware clean all            (a build with -DMYNA_TEST_HOOKS=1 adds the full-store steps)
    native/.venv/bin/python -I myna/firmware/test/sim_telephony.py [--core own|unicorn] [--verbose] [--frames DIR]

--core: the engine. Default: the compiled core (native/core, built by native/core/build.sh; DBCORE_OUT names another build
folder), else Unicorn when the compiled core is not built and Unicorn is installed. Myna needs no Unicorn.

The script uses only the launcher's program interface (native/sim/db3210.py: build, run, Phone, on_frame) and the
documented interface of the host network (emu_cell/cell.py: Host.take, result, incoming, set_service). The
phone is driven with keys as a person would (multi-tap text included), and checked by its console and its frames.

Steps: start without service ("Searching"), service on; Messages: New message, a number typed, a text written and
sent to the own number and received back (marked read where it arrives); a 3-part text (the count shows the parts);
a refusal shown with its reason, Retry in Options; a passing refusal retried after 10 s; a text written without
service (sent when it is back); a text arriving on standby (toast, envelope, "1 new message"), read in Messages;
Contacts: a new contact with two numbers and a note, edited, another deleted after the question, the conversation
then named after the contact; the dialer offers a message (calls are not available); a power cycle with the flash
state (messages and contacts still there). With --frames every state is saved as a PNG, in Pebble and Pebble night.
With a MYNA_TEST_HOOKS build: a full store (RP cause 22, then room again). PDUs are built and decoded here (3GPP TS
23.040, 23.038), independently of Myna's code.
"""
import argparse, os, re, struct, sys, time, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'native', 'sim'))
import db3210  # noqa: E402

MS = 1_000_000
OWN = '+15550123'
FRIEND = '+4915551234567'
REFUSER = '+15559999'
DRAFTEE = '+15550177'
SC = bytes([0x81, 0x55, 0x05, 0x01, 0xF0])      # the service centre 5550100: type, swapped digits

# ---- 3GPP TS 23.038 default alphabet and extension table ----
BASIC = ('@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !"#¤%&\'()*+,-./0123456789:;<=>?'
         '¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà')
EXT = {0x0A: '\f', 0x14: '^', 0x28: '{', 0x29: '}', 0x2F: '\\', 0x3C: '[', 0x3D: '~', 0x3E: ']', 0x40: '|', 0x65: '€'}
assert len(BASIC) == 128


def gsm_unpack(data, n, fill):
    bits = int.from_bytes(data, 'little')
    return [(bits >> (fill + 7 * i)) & 0x7F for i in range(n)]


def gsm_text(septets):
    out, esc = [], False
    for s in septets:
        if esc:
            out.append(EXT.get(s, BASIC[s]))
            esc = False
        elif s == 0x1B:
            esc = True
        else:
            out.append(BASIC[s])
    return ''.join(out)


def swapped(digits):
    d = digits + ('F' if len(digits) % 2 else '')
    return bytes(int(d[i + 1] + d[i], 16) for i in range(0, len(d), 2))


def address(number):
    intl = number.startswith('+')
    digits = number.lstrip('+')
    return bytes([len(digits), 0x91 if intl else 0x81]) + swapped(digits)


def read_address(t, i):
    n, typ = t[i], t[i + 1]
    octets = (n + 1) // 2
    digits = ''.join('%X' % (b & 15) + '%X' % (b >> 4) for b in t[i + 2:i + 2 + octets])[:n]
    return ('+' if typ & 0x70 == 0x10 else '') + digits, i + 2 + octets


def decode_submit(t):
    """An SMS-SUBMIT (TS 23.040 9.2.2.2): (to, dcs, (ref, total, seq) or None, text)."""
    fo = t[0]
    assert fo & 3 == 1, 'not an SMS-SUBMIT'
    to, i = read_address(t, 2)
    pid, dcs = t[i], t[i + 1]
    i += 2
    vpf = (fo >> 3) & 3
    i += {0: 0, 2: 1}.get(vpf, 7)
    udl, ud = t[i], t[i + 1:]
    concat, hl = None, 0
    if fo & 0x40:
        hl = ud[0] + 1
        j = 1
        while j < hl:
            iei, l = ud[j], ud[j + 1]
            v = ud[j + 2:j + 2 + l]
            if iei == 0:
                concat = (v[0], v[1], v[2])
            elif iei == 8:
                concat = (v[0] << 8 | v[1], v[2], v[3])
            j += 2 + l
    if dcs & 0x0C == 0x08:
        text = bytes(ud[hl:udl]).decode('utf-16-be')
    else:
        hs = (hl * 8 + 6) // 7
        text = gsm_text(gsm_unpack(ud[hl:], udl - hs, hs * 7 - hl * 8))
    return to, dcs, concat, text


def deliver(sender, text, concat=None):
    """An SMS-DELIVER (TS 23.040 9.2.2.1) in UCS-2 (or the default alphabet when every character has a septet)."""
    try:
        septets = []
        for ch in text:
            if ch in BASIC and ch != '\x1b':
                septets.append(BASIC.index(ch))
            else:
                septets += [0x1B, next(k for k, v in EXT.items() if v == ch)]
        gsm = True
    except StopIteration:
        gsm = False
    udh = b''
    if concat:
        ref, total, seq = concat
        udh = bytes([5, 0, 3, ref, total, seq])
    fo = 0x04 | (0x40 if udh else 0)
    scts = bytes([0x80, 0x01, 0x02, 0x21, 0x00, 0x00, 0x00])
    if gsm:
        fill = (7 - len(udh) * 8 % 7) % 7 if udh else 0
        hs = (len(udh) * 8 + fill) // 7
        bits = sum(s << (fill + 7 * i) for i, s in enumerate(septets))
        body = bits.to_bytes((fill + 7 * len(septets) + 7) // 8, 'little') if septets else b''
        return bytes([fo]) + address(sender) + bytes([0, 0]) + scts + bytes([hs + len(septets)]) + udh + body
    data = text.encode('utf-16-be')
    return bytes([fo]) + address(sender) + bytes([0, 8]) + scts + bytes([len(udh) + len(data)]) + udh + data


def ucs2_parts(text, units):
    """cut a text into parts of at most `units` UTF-16 units, never inside a surrogate pair"""
    parts, cur, n = [], '', 0
    for ch in text:
        u = 2 if ord(ch) > 0xFFFF else 1
        if n + u > units:
            parts.append(cur)
            cur, n = '', 0
        cur += ch
        n += u
    return parts + [cur]


# ---- typing on the twelve keys, as Myna's text box takes it (ui/textentry.c) ----

PAD = {'0': '0+', '1': '.,?!\'"-()@/:;_1', '2': 'abc2', '3': 'def3', '4': 'ghi4', '5': 'jkl5', '6': 'mno6',
       '7': 'pqrs7', '8': 'tuv8', '9': 'wxyz9'}
KEY_OF = {c: (k, i) for k, s in PAD.items() for i, c in enumerate(s)}


def as_typed(text):
    """what the box makes of lower-case taps: a capital at the start of each sentence (mode Abc)"""
    out, start = [], True
    for ch in text:
        out.append(ch.upper() if start and ch.isalpha() else ch)
        if ch.isalpha() or ch.isdigit():
            start = False
        elif ch in '.!?':
            start = True
    return ''.join(out)


def png_rgb(path, w, h, rgb):
    raw = b''.join(b'\0' + bytes(rgb[y * w * 3:(y + 1) * w * 3]) for y in range(h))

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF)

    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


# ---- the phone ----

class Run:
    def __init__(self, core, verbose, flash=b'', frames=None, network='host', slice_=True, device='myna'):
        self.lines, self.verbose, self.core = [], verbose, core
        opts = ['--standard', '--display']
        if slice_:
            opts += ['--slice', '100']
        if core == 'own':
            opts += ['--core', 'own']
        cfg = {'sim.present': True, 'cell.network': network, 'phone.number': OWN}
        self.frame = None
        self.frames = frames
        self.phone = db3210.build(device, flash=flash, peer_config=cfg, options=opts, out=self.out,
                                  on_frame=self.on_frame)
        self.net = self.phone.attached['emu_modem_at:attach_peer'].cell if network == 'host' else None
        self.mark = 0
        self.ended = None

    def on_frame(self, w, h, rgb, number):
        self.frame = (w, h, bytes(rgb))

    def save(self, name):
        """the screen as it is now, as DIR/<name>.png"""
        if self.frames and self.frame:
            os.makedirs(self.frames, exist_ok=True)
            png_rgb(os.path.join(self.frames, name + '.png'), *self.frame)

    def out(self, line):
        self.lines.append(line)
        if self.verbose:
            print('   |', line)

    def console(self):
        """the firmware's console lines; the launcher gives the UART's bytes as Latin-1 characters: Myna writes UTF-8"""
        out = []
        for l in self.lines:
            if l.startswith('APP uart| '):
                l = l[len('APP uart| '):]
                try:
                    l = l.encode('latin-1').decode('utf-8')
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
                out.append(l)
        return out

    def run(self, ms):
        r = db3210.run(self.phone, int(ms * MS), hold=True)
        if r['ended']:
            self.ended = r['why']
        return r

    def wait(self, pattern, ms=5000, since=None):
        """run until a console line from `since` (default: the mark) matches; returns the match or None"""
        start = self.mark if since is None else since
        rx = re.compile(pattern)
        t = 0
        while True:
            for l in self.console()[start:]:
                m = rx.search(l)
                if m:
                    return m
            if t >= ms or self.ended:
                return None
            self.run(20)
            t += 20

    def take(self, ms=5000):
        t = 0
        while t <= ms:
            got = self.net.take()
            if got:
                return got
            self.run(20)
            t += 20
        return []

    def set_mark(self):
        self.mark = len(self.console())

    def key(self, name, ms=60, after=140):
        self.phone.inputs.tap(name, ms)
        self.run(ms + after)

    def keys(self, *names, after=140):
        for n in names:
            self.key(n, after=after)

    def settle(self, ms=400):
        self.run(ms)

    def type(self, text):
        """lower-case text, digits and punctuation with multi-tap, # for a space; 'right' takes a letter before the same key
        again"""
        last = None
        for ch in text.lower():
            if ch == ' ':
                self.key('hash', ms=40, after=40)      # the space (# is the space key)
                last = None
                continue
            k, i = KEY_OF[ch]
            if k == last:
                self.key('right', after=40)
            for _ in range(i + 1):
                self.key(k, ms=40, after=40)
            last = k
        self.key('right', after=60)

    def dial(self, number):
        """a number in a phone-number box: digits, * gives '+'"""
        for ch in number:
            self.key('star' if ch == '+' else ch, ms=40, after=40)

    def now_ms(self):
        return self.phone.now / 1e6


class Check:
    def __init__(self):
        self.passed, self.failed = 0, 0

    def __call__(self, ok, what):
        print(('PASS ' if ok else 'FAIL ') + what)
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        return ok


def answer_parts(r, n_parts, ok=True, cause=0):
    """take n SMS-SUBMITs and answer each; returns [(to, dcs, concat, text)]"""
    got = []
    for _ in range(n_parts):
        s = r.take()
        if not s:
            break
        n, sc, tpdu = s[0]
        got.append(decode_submit(bytes(tpdu)))
        r.net.result(n, ok, cause) if not ok else r.net.result(n, True)
    return got


def predictive_off(r, check):
    """Settings, Text input, Predictive text: off (this script types with multi-tap; sim_ui.py tests predictive text)"""
    r.set_mark()
    r.keys('select', 'hash', '4', '1', 'end')
    check(r.wait(r'ui: setting predictive = 0', 500) is not None, 'Settings: predictive text off (multi-tap here)')
    r.settle()


def to_messages_of(r, number):
    """from standby: Messages, New message, Enter number, the number, Save: the conversation"""
    r.key('soft_left')                  # "New message" is selected when nothing is unread
    r.key('select')                     # the recipient picker
    r.key('select')                     # "Enter number"
    r.dial(number)
    r.key('select')
    r.settle()


def scenario(core, verbose, frames, hooks):
    check = Check()
    measures = {}
    fdir = os.path.join(frames, 'unicorn' if core != 'own' else 'own') if frames else None
    print('== engine: %s' % ('compiled core' if core == 'own' else 'Unicorn'))
    r = Run(core, verbose, frames=fdir)
    check(r.wait(r'modem: ready in (\d+) ms', 10000) is not None, 'modem bring-up (CMUX, DLC 1)')
    check(r.wait(r'network: registration 2', 100) is not None, 'no service at power-on: searching')
    r.set_mark()
    r.net.set_service(True)
    check(r.wait(r'network: registration 1', 10000) is not None, 'service on: registered')
    check(r.wait(r'network: time .*', 2000) is not None, 'network time read at registration')
    r.wait(r'display: first frame', 10000, since=0)    # a BENCH build draws its benchmarks first
    r.phone.inputs.set_switch('slide', 'open')
    r.run(400)
    r.save('01-standby')
    predictive_off(r, check)

    # Messages: empty, then a text to the own number, sent and received back
    r.key('soft_left')
    r.settle()
    r.save('02-messages-empty')
    r.key('select')                      # New message: the recipient
    r.settle()
    r.save('03-new-message')
    r.key('select')                      # Enter number
    r.dial(OWN)
    r.settle()
    r.save('04-enter-number')
    r.key('select')
    r.settle()
    r.save('05-conversation-new')
    text = 'hi from myna. see you at six?'
    r.type(text)
    r.settle(1200)
    r.save('06-compose')
    r.set_mark()
    r.key('select')                      # Send
    m = r.wait(r'ui: send to \+15550123: (\d+)', 1000)
    check(m is not None, 'Send queues the text (%s)' % (m.group(0) if m else None))
    r.save('07-sending')
    got = answer_parts(r, 1)
    check(len(got) == 1 and got[0][0] == OWN and got[0][3] == as_typed(text),
          'the network gets the typed text: %r' % (got[0][3] if got else None))
    m = r.wait(r'sent \(1 part, reference \d+\), (\d+) instructions', 3000)
    check(m is not None, '"sent" after the network took it')
    if m:
        measures['send 1 part (service)'] = int(m.group(1))
    r.set_mark()
    r.net.incoming(SC, deliver(OWN, as_typed(text)), lambda a, c: None)
    m = r.wait(r'message (\d+) from \+15550123 received: "(.*)"', 5000)
    check(m is not None and m.group(2) == as_typed(text), 'received back from the own number')
    r.settle(600)
    check(r.wait(r'ui: new message', 10) is None, 'received in the open conversation: no toast')
    r.save('08-conversation-sent-received')

    # a 3-part text: the count shows the parts
    long_text = ('the quick brown fox jumps over the lazy dog. ' * 8)[:330]
    r.type(long_text)
    r.settle(1200)
    r.save('09-compose-3-parts')
    r.set_mark()
    r.key('select')
    got = answer_parts(r, 3)
    texts = ''.join(g[3] for g in got)
    check(len(got) == 3 and [g[2][1:] for g in got] == [(3, 1), (3, 2), (3, 3)] and texts == as_typed(long_text),
          '3-part text out: three SUBMITs in order, one reference, the whole text')
    m = r.wait(r'sent \(3 parts, reference \d+\), (\d+) instructions', 3000)
    check(m is not None, '3-part text: "sent"')
    if m:
        measures['send 3 parts (service)'] = int(m.group(1))
    r.settle()
    r.save('10-conversation-3-parts')
    r.key('up')
    r.key('up')
    r.settle()
    r.save('11-conversation-scrolled')

    # a 3-part UCS-2 text in, put together
    long_in = ('Привет κόσμε 你好 😀 ok ' * 9)[:180]
    r.set_mark()
    for i, p in enumerate(ucs2_parts(long_in, 67)):
        r.net.incoming(SC, deliver(OWN, p, (0x42, 3, i + 1)), lambda a, c: None)
        r.run(300)
    m = r.wait(r'message (\d+) from \+15550123 received: "(.*)"', 5000)
    check(m is not None and m.group(2) == long_in, '3-part UCS-2 text in: put together in order')
    r.key('end')                         # standby

    # a refusal: the reason in the block, Retry in Options
    to_messages_of(r, REFUSER)
    r.type('are you there?')
    r.set_mark()
    r.key('select')
    s = r.take()
    if s:
        r.net.result(s[0][0], False, 21)
    m = r.wait(r'message (\d+) to \+15559999 failed: (.*) \((\d+)\)', 3000)
    check(m is not None and m.group(3) == '21', 'permanent refusal (RP cause 21): failed')
    r.settle()
    r.save('12-conversation-failed')
    r.key('soft_left')
    r.settle()
    r.save('13-options-retry')
    r.set_mark()
    r.key('select')                      # Retry
    s = r.take()
    check(bool(s) and r.wait(r'ui: retry of message \d+: \d+', 100) is not None, 'Retry sends it again')
    if s:
        r.net.result(s[0][0], False, 41)
    check(r.wait(r'Temporary failure \(41\), trying again in 10 s', 3000) is not None, 'passing refusal (41)')
    r.settle()
    r.save('14-conversation-trying-again')
    t0 = r.now_ms()
    s = r.take(15000)
    check(bool(s) and 9500 <= r.now_ms() - t0 <= 11000, 'sent again after 10 s (%.0f ms)' % (r.now_ms() - t0))
    if s:
        r.net.result(s[0][0], True)
    check(r.wait(r'to \+15559999 sent', 3000) is not None, 'then "sent"')
    r.key('end')

    # a 3-part text whose second part is refused: Retry sends only the parts the network did not take, under the
    # reference of the first, so the recipient can still join them
    to_messages_of(r, REFUSER)
    r.type(long_text)
    r.set_mark()
    r.key('select')
    first = []
    for ok in (True, False):
        s = r.take()
        if not s:
            break
        first.append(decode_submit(bytes(s[0][2])))
        r.net.result(s[0][0], ok, 0 if ok else 21)
    m = r.wait(r'message (\d+) to \+15559999 failed: .* \(21\)', 3000)
    check(m is not None and [g[2][1:] for g in first] == [(3, 1), (3, 2)],
          '3-part text: part 1 taken, part 2 refused (RP cause 21): failed')
    r.settle()
    r.save('14b-conversation-part-refused')
    r.key('soft_left')                   # Options: Retry first
    r.set_mark()
    r.key('select')
    check(r.wait(r'queued again from part 2 of 3', 1000) is not None, 'Retry: queued again from part 2')
    r.run(100)
    r.save('14c-conversation-sending-part-2')
    again = answer_parts(r, 2)
    ref = first[0][2][0] if first and first[0][2] else None
    check(len(again) == 2 and [g[2] for g in again] == [(ref, 3, 2), (ref, 3, 3)]
          and first[0][3] + ''.join(g[3] for g in again) == as_typed(long_text),
          'Retry: only parts 2 and 3 go, under the first part\'s reference %s (%s)' % (ref, [g[2] for g in again]))
    check(not r.take(1500), 'Retry: nothing more is sent')
    check(r.wait(r'to \+15559999 sent \(3 parts', 3000) is not None, 'Retry: the 3-part text is "sent"')
    r.settle()
    r.save('14d-conversation-part-retry-sent')
    r.key('end')

    # no service: the message waits, and goes when the service is back
    r.set_mark()
    r.net.set_service(False)
    check(r.wait(r'network: registration 2', 3000) is not None, 'service gone: searching')
    to_messages_of(r, REFUSER)
    r.type('later')
    r.key('select')
    r.settle()
    r.save('15-waiting-for-network')
    check(not r.take(2000), 'no service: nothing is sent')
    r.set_mark()
    r.net.set_service(True)
    s = r.take(5000)
    if s:
        r.net.result(s[0][0], True)
    check(bool(s) and r.wait(r'sent \(1 part', 3000) is not None, 'service back: the waiting message is sent')
    r.key('end')
    r.settle()

    # a draft: text left in a conversation (END) stays with its number, a row of its own in the list
    to_messages_of(r, DRAFTEE)
    r.type('pick up the keys')
    r.set_mark()
    r.key('end')
    check(r.wait(r'ui: draft for \+15550177 kept \(16 bytes\): 0', 1000) is not None,
          'END in a conversation: its text is kept as the draft')
    r.key('soft_left')
    r.settle()
    r.save('15b-messages-draft')
    r.key('down')                        # the draft's row: the newest
    r.set_mark()
    r.key('select')
    r.settle()
    check(r.wait(r'ui: draft for \+15550177 restored \(16 characters\)', 1000) is not None,
          'the draft is in the box again when the conversation opens')
    r.save('15c-conversation-draft')
    r.set_mark()
    r.key('soft_right')
    check(r.wait(r'ui: draft for', 300) is None, 'Back with the draft unchanged: nothing written')
    r.key('end')

    # a text on standby: toast, envelope, "1 new message"
    r.set_mark()
    r.net.incoming(SC, deliver(FRIEND, 'Two please. And bread if they have the dark one.'), lambda a, c: None)
    m = r.wait(r'ui: new message \d+ from \+4915551234567: toast', 5000)
    check(m is not None, 'a text on standby: a toast with the sender and its first words')
    r.run(250)
    r.save('16-standby-toast')
    r.run(3200)
    r.save('17-standby-new-message')
    r.key('soft_left')
    r.settle()
    r.save('18-messages-unread')
    r.set_mark()
    r.key('select')                      # the newest conversation (selected because it is unread)
    r.settle()
    r.save('19-conversation-incoming')
    r.key('soft_left')
    r.settle()
    r.save('20-options')
    r.key('soft_right')
    r.key('soft_right')
    r.settle()
    r.save('21-messages-read')
    r.key('end')

    # Contacts: a new one with two numbers and a note
    r.key('soft_right')
    r.settle()
    r.save('22-contacts-empty')
    r.key('select')                      # New contact
    r.settle()
    r.save('23-contact-new')
    r.key('1')                           # First name
    r.type('juno')
    r.settle()
    r.save('24-editor-name')
    r.key('select')
    r.key('2')                           # Last name
    r.type('park')
    r.key('select')
    r.key('3')                           # Add number
    r.dial(FRIEND)
    r.settle()
    r.save('25-editor-number')
    r.key('select')
    r.key('4')                           # Add number (a second)
    r.dial('+15550111')
    r.key('soft_left')                   # Label: the next one
    r.settle()
    r.save('26-editor-number-label')
    r.key('select')
    r.key('6')                           # Note
    r.type('met at the market.')
    r.key('select')
    r.settle()
    r.save('27-contact-filled')
    r.set_mark()
    r.key('soft_left')                   # Save
    m = r.wait(r'ui: contact 0 saved: (\d+) \("Juno" "Park", 2 numbers, note "Met at the market."\)', 2000)
    check(m is not None, 'new contact saved: name, two numbers, note')
    juno = int(m.group(1)) if m else 0
    r.settle()
    r.save('28-contact-view')
    r.key('soft_left')
    r.settle()
    r.save('29-contact-options')
    r.key('3')                           # Edit (Send message, Call, Edit, Delete)
    r.key('1')
    r.key('clear')
    r.key('clear')
    r.key('clear')
    r.key('clear')
    r.type('juno')
    r.key('select')
    r.set_mark()
    r.key('soft_left')                   # Save
    check(r.wait(r'ui: contact %d saved: 0 \("Juno"' % juno, 2000) is not None, 'contact edited and saved')
    r.key('soft_right')                  # the list
    r.settle()
    # another one, deleted after the question
    r.key('up')
    r.key('select')
    r.key('1')
    r.type('ada')
    r.key('select')
    r.key('soft_left')
    r.settle()
    r.key('soft_left')                   # Options: Edit, Delete (no number: no Send message, no Call)
    r.key('2')                           # Delete
    r.settle()
    r.save('30-contact-delete-question')
    r.set_mark()
    r.key('select')
    check(r.wait(r'ui: contact \d+ deleted: 0', 2000) is not None, 'a contact deleted after the question')
    r.settle()
    r.save('31-contacts-list')
    r.key('end')

    # the conversation is named after the contact now
    r.key('soft_left')
    r.settle()
    r.save('32-messages-named')
    r.key('end')

    # the dialer: no calls, a message instead
    r.keys('5', '5', '5', '0', '1', '2', '3')
    r.settle()
    r.save('33-dialer')
    r.key('call')
    r.run(200)
    r.save('34-dialer-call-key')
    r.key('soft_right')
    r.key('end')

    # Notes still writes into message blocks
    r.key('select')
    r.key('star')
    r.type('buy pears and the dark bread.')
    r.key('select')
    r.run(1700)
    r.save('35-notes')
    r.key('end')

    if hooks:
        r.keys('star', 'hash', '3', '6', '7', '8', 'star', '1', 'hash')
        check(r.wait(r'test: storage full on', 1000) is not None, 'test hook: the store answers "full"')
        r.key('end')
        reports = []
        r.set_mark()
        r.net.incoming(SC, deliver(FRIEND, 'Kein Platz'), lambda a, c: reports.append((a, c)))
        r.wait(r'message refused \(memory full\)', 3000)
        r.run(500)
        check(reports == [(False, 22)], 'full store: refused, the network hears RP cause 22 (%s)' % reports)
        r.keys('star', 'hash', '3', '6', '7', '8', 'star', '0', 'hash')
        check(r.wait(r'room for messages again', 2000) is not None, 'room again: +CNMI tells the network (RP-SMMA)')
        r.key('end')

    # night: the same screens in Pebble night
    r.key('select')                      # the menu
    r.key('hash')                        # Settings
    r.key('2')                           # Display
    r.key('1')                           # Theme
    r.key('end')
    r.settle()
    night_tour(r)                        # leaves one text unread

    # power off and on with the flash state, from inside the draft's conversation with more text in its box
    r.key('soft_left')                   # Messages: the unread conversation is selected
    r.key('up')                          # New message
    r.key('select')
    r.key('select')                      # Enter number
    r.dial(DRAFTEE)
    r.set_mark()
    r.key('select')
    check(r.wait(r'ui: draft for \+15550177 restored \(16 characters\)', 1000) is not None,
          'New message to the same number: the draft is in the box')
    r.type(' today')
    r.set_mark()
    r.key('end', 3600)
    r.run(3000)
    check(r.ended is not None or any('pmic: power off' in l for l in r.console()),
          'held END: the phone switched itself off (%s)' % r.ended)
    flash = r.phone.flash_state()
    r2 = Run(core, verbose, flash, frames=fdir)
    m = r2.wait(r'sms store: (\d+) messages \((\d+) unread\)', 10000)
    check(m is not None and int(m.group(1)) >= 8 and int(m.group(2)) == 1,
          'power cycle: the messages come back (%s)' % (m.group(0) if m else None))
    check(m is not None and ', 2 drafts;' in m.string,
          'power cycle: the drafts come back (this one, and the night tour\'s left in a conversation)')
    check(r2.wait(r'contacts: 1 read', 1000) is not None, 'power cycle: the contact comes back')
    check(r2.wait(r'modem: ready in (\d+) ms', 10000) is not None, 'power cycle: modem ready again')
    r2.net.set_service(True)
    r2.phone.inputs.set_switch('slide', 'open')
    r2.run(600)
    r2.key('soft_left')
    r2.settle()
    r2.save('60-after-power-cycle-messages')
    r2.key('end')
    r2.key('soft_right')
    r2.settle()
    r2.save('61-after-power-cycle-contacts')
    r2.key('end')
    r2.key('soft_left')                  # the unread conversation is selected, the newer draft's row above it
    r2.key('up')
    r2.set_mark()
    r2.key('select')
    r2.settle()
    check(r2.wait(r'ui: draft for \+15550177 restored \(22 characters\)', 1000) is not None,
          'power cycle: the draft (left at power off) is in the box again')
    r2.save('62-after-power-cycle-draft')
    print('measures (instructions):', measures)
    return check


def night_tour(r):
    """the screens again, in Pebble night (the theme was switched)"""
    r.save('40-night-standby')
    r.key('soft_left')
    r.settle()
    r.save('41-night-messages')
    r.key('down')
    r.key('select')
    r.settle()
    r.save('42-night-conversation')
    r.type('ok. see you.')
    r.settle(1200)
    r.save('43-night-compose')
    r.key('soft_left')
    r.settle()
    r.save('44-night-options')
    r.key('soft_right')
    r.key('soft_right')
    r.key('up')
    r.key('select')
    r.settle()
    r.save('45-night-new-message')
    r.key('soft_right')
    r.key('end')
    r.key('soft_right')
    r.settle()
    r.save('46-night-contacts')
    r.key('select')
    r.settle()
    r.save('47-night-contact-view')
    r.key('soft_left')
    r.key('3')
    r.settle()
    r.save('48-night-contact-edit')
    r.key('6')
    r.settle()
    r.save('52-night-editor')
    r.key('soft_right')
    r.key('soft_right')
    r.key('end')
    to_messages_of(r, REFUSER)
    r.type('hello?')
    r.key('select')
    s = r.take()
    if s:
        r.net.result(s[0][0], False, 21)
    r.wait(r'to \+15559999 failed', 3000, since=len(r.console()) - 1)
    r.settle()
    r.save('53-night-conversation-failed')
    r.key('soft_left')
    r.key('2')                           # Delete message (Retry, Delete message, ...)
    r.settle()
    r.save('54-night-delete-question')
    r.key('soft_right')                  # Keep
    r.key('end')
    r.keys('5', '5', '5', '0', '1')
    r.settle()
    r.save('49-night-dialer')
    r.key('soft_right')
    r.key('end')
    r.net.incoming(SC, deliver(FRIEND, 'Got it. Home by six.'), lambda a, c: None)
    r.wait(r'ui: new message \d+ from \+4915551234567: toast', 5000, since=len(r.console()) - 1)
    r.run(250)
    r.save('50-night-standby-toast')
    r.run(3200)
    r.save('51-night-standby-new-message')


def loopback(core, verbose, frames, check):
    """the loopback network of the stand-in: a text comes back from the number it was sent to"""
    fdir = os.path.join(frames, 'loopback-' + ('unicorn' if core != 'own' else 'own')) if frames else None
    print('== loopback network, engine: %s' % ('compiled core' if core == 'own' else 'Unicorn'))
    r = Run(core, verbose, frames=fdir, network='loopback')
    check(r.wait(r'network: registration 1', 10000) is not None, 'loopback: registered')
    r.wait(r'display: first frame', 10000, since=0)    # a BENCH build draws its benchmarks first
    r.phone.inputs.set_switch('slide', 'open')
    r.run(400)
    predictive_off(r, check)
    to_messages_of(r, OWN)
    text = 'loop test, one part.'
    r.type(text)
    r.set_mark()
    r.key('select')
    m = r.wait(r'message \d+ from \+15550123 received: "(.*)"', 10000)
    check(m is not None and m.group(1) == as_typed(text), 'loopback: a text to the own number comes back')
    r.settle()
    r.save('70-loopback-one-part')
    long_text = ('pack my box with five dozen liquor jugs. ' * 9)[:340]
    r.type(long_text)
    r.settle(1200)
    r.save('71-loopback-compose-3-parts')
    r.set_mark()
    r.key('select')
    check(r.wait(r'sent \(3 parts', 10000) is not None, 'loopback: a 3-part text sent')
    m = r.wait(r'message \d+ from \+15550123 received: "(.*)"', 10000)
    check(m is not None and m.group(1) == as_typed(long_text), 'loopback: the 3-part text comes back whole')
    r.settle()
    r.save('72-loopback-3-parts')


def default_core():
    """The compiled core when its library is built; else Unicorn when it is installed; else stop with what to do."""
    sys.path.insert(0, os.path.join(ROOT, 'native', 'core', 'python'))
    try:
        import dbcore
        dbcore.find_library()
        return 'own'
    except (ImportError, OSError) as e:
        why = e
    try:
        import unicorn  # noqa: F401
        print('== the compiled core is not built (%s): running on Unicorn' % why)
        return 'unicorn'
    except ImportError:
        sys.exit('sim_telephony: no engine. Build the compiled core: sh native/core/build.sh (%s)' % why)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--core', choices=('unicorn', 'own'), default=None, help='default: own when it is built, else unicorn')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--frames', help='save the screens as PNG files under DIR/unicorn or DIR/own')
    ap.add_argument('--hooks', action='store_true', help='the build has MYNA_TEST_HOOKS: test the full store too')
    ap.add_argument('--network', choices=('host', 'loopback', 'both'), default='both')
    a = ap.parse_args()
    a.core = a.core or default_core()
    t = time.time()
    c = Check()
    if a.network != 'loopback':
        c = scenario(a.core, a.verbose, a.frames, a.hooks)
    if a.network != 'host':
        loopback(a.core, a.verbose, a.frames, c)
    print('%d passed, %d failed (%.1f s host time)' % (c.passed, c.failed, time.time() - t))
    sys.exit(1 if c.failed else 0)


if __name__ == '__main__':
    main()
