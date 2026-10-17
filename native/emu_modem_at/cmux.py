"""3GPP TS 27.010 multiplexer, basic option: frames, the frame check sequence and the messages of the control channel (DLC 0).

Frame:  F9 | address | control | length (1 or 2 octets) | information | FCS | F9
  address  bit 0 EA = 1, bit 1 C/R, bits 7:2 DLCI
  control  SABM 0x2F, UA 0x63, DM 0x0F, DISC 0x43, UIH 0xEF, UI 0x03; bit 4 (0x10) is P/F
  length   bit 0 EA: 1 = one octet, length in bits 7:1; 0 = a second octet follows with bits 14:7
  FCS      27.010 5.2.1.6: CRC-8 (x^8 + x^2 + x + 1, reflected, initial 0xFF, sent complemented) over address, control and
           length; for UI frames also over the information field
Control-channel message (in the information field of a UIH frame on DLC 0): type octet (bit 0 EA = 1, bit 1 C/R: 1 command,
0 response, bits 7:2 type), length octet(s) as above, value.
No unicorn import, no state of the simulator: pure functions and one parser class.
"""
SABM, UA, DM, DISC, UIH, UI = 0x2F, 0x63, 0x0F, 0x43, 0xEF, 0x03
PF = 0x10
FLAG = 0xF9
NAMES = {SABM: 'SABM', UA: 'UA', DM: 'DM', DISC: 'DISC', UIH: 'UIH', UI: 'UI'}

# control-channel message types, the type octet of a COMMAND (C/R = 1); a response has bit 1 clear
PN, PSC, CLD, TEST, FCON, FCOFF, MSC, NSC, RPN, RLS, SNC = 0x83, 0x43, 0xC3, 0x23, 0xA3, 0x63, 0xE3, 0x13, 0x93, 0x53, 0xD3
MSG_NAMES = {PN: 'PN', PSC: 'PSC', CLD: 'CLD', TEST: 'Test', FCON: 'FCon', FCOFF: 'FCoff', MSC: 'MSC', NSC: 'NSC', RPN: 'RPN',
             RLS: 'RLS', SNC: 'SNC'}


def _table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xE0 if c & 1 else c >> 1
        t.append(c)
    return t


CRC = _table()


def fcs(data):
    """The FCS octet of `data` (the octets it covers)."""
    c = 0xFF
    for b in data:
        c = CRC[c ^ b]
    return 0xFF - c


def fcs_ok(data, value):
    c = 0xFF
    for b in bytes(data) + bytes([value]):
        c = CRC[c ^ b]
    return c == 0xCF


def length_field(n):
    return bytes([n << 1 | 1]) if n < 128 else bytes([(n & 0x7F) << 1, n >> 7])


def frame(dlci, control, info=b'', cr=0):
    """One frame. `cr` is the C/R bit of the address."""
    head = bytes([dlci << 2 | cr << 1 | 1, control]) + length_field(len(info))
    check = fcs(head + bytes(info)) if control & ~PF == UI else fcs(head)
    return bytes([FLAG]) + head + bytes(info) + bytes([check, FLAG])


def message(mtype, value=b'', command=True):
    """A control-channel message: `mtype` is the command form of the type octet."""
    return bytes([mtype if command else mtype & ~2]) + length_field(len(value)) + bytes(value)


def parse_messages(info):
    """[(type octet, value)] of the control-channel messages in `info`; ValueError when it is cut short."""
    out, i = [], 0
    while i < len(info):
        t = info[i]; i += 1
        while not t & 1:                                    # type octets with EA = 0: not used by 27.010, skip
            if i >= len(info): raise ValueError('type cut short')
            t = info[i]; i += 1
        if i >= len(info): raise ValueError('length missing')
        n = info[i] >> 1; ea = info[i] & 1; i += 1
        if not ea:
            if i >= len(info): raise ValueError('length cut short')
            n |= info[i] >> 1 << 7; i += 1
        if i + n > len(info): raise ValueError('value cut short')
        out.append((t, bytes(info[i:i + n]))); i += n
    return out


class Frame:
    __slots__ = ('dlci', 'cr', 'control', 'info')

    def __init__(self, dlci, cr, control, info):
        self.dlci, self.cr, self.control, self.info = dlci, cr, control, info

    @property
    def kind(self):
        return self.control & ~PF

    @property
    def pf(self):
        return bool(self.control & PF)

    def __repr__(self):
        return '%s%s dlci %d%s' % (NAMES.get(self.kind, '%#04x' % self.control), '(P/F)' if self.pf else '', self.dlci,
                                   ' %d octets' % len(self.info) if self.info else '')


class Parser:
    """Frames out of a byte stream. feed(data) -> [Frame]. A frame with a bad FCS, a missing closing flag or an information
    field longer than `max_info` is dropped and counted in `errors` (last reason in `last_error`); the parser then hunts
    for the next flag. Repeated flags between frames are allowed."""

    def __init__(self, max_info=32768):
        self.max_info = max_info
        self.buf = bytearray()
        self.errors = 0
        self.last_error = None

    def feed(self, data):
        self.buf += data
        out = []
        b = self.buf
        while True:
            start = b.find(FLAG)
            if start < 0:
                del b[:]
                break
            del b[:start]
            while len(b) > 1 and b[1] == FLAG:                  # a closing flag followed by an opening flag, or idle flags
                del b[:1]
            if len(b) < 4:
                break
            addr, ctrl, l0 = b[1], b[2], b[3]
            if not addr & 1:
                self._bad('address with EA = 0'); del b[:1]; continue
            hl = 3
            n = l0 >> 1
            if not l0 & 1:
                if len(b) < 5:
                    break
                n |= b[4] << 7
                hl = 4
            if n > self.max_info:
                self._bad('information field of %d octets is longer than N1 = %d' % (n, self.max_info)); del b[:1]; continue
            end = 1 + hl + n + 1                                # index of the closing flag
            if len(b) < end + 1:
                break
            head, info, check = bytes(b[1:1 + hl]), bytes(b[1 + hl:1 + hl + n]), b[end - 1]
            if b[end] != FLAG:
                self._bad('no closing flag'); del b[:1]; continue
            covered = head + info if ctrl & ~PF == UI else head
            if not fcs_ok(covered, check):
                self._bad('bad FCS %#04x on %s' % (check, (head + info).hex())); del b[:end]; continue
            out.append(Frame(addr >> 2, addr >> 1 & 1, ctrl, info))
            del b[:end]                                         # keep the closing flag: it may open the next frame
        return out

    def _bad(self, why):
        self.errors += 1
        self.last_error = why
