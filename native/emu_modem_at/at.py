"""The AT command interpreter of the stand-in: ITU-T V.250 command lines, 3GPP TS 27.007 (identity, card, registration,
signal, clock, radio) and 3GPP TS 27.005 (text messages in PDU mode). The interface for firmware writers is
myna/spec/14-modem-at.md; this module follows it and the selftest checks it.

The interpreter does not know the transport. It gets the bytes of one AT channel with feed() and gives its answers to
modem.at_write(). What it needs of the modem (modem.py, AtModem):
    at_write(bytes)        the bytes towards the firmware on the AT channel
    at_open()              the AT channel can carry bytes now (the raw channel, or DLC 1 open)
    say(text)              a log line
    schedule(delay_ns, fn) run fn later, from the stand-in's tick (emulated time)
    now_ns()               emulated time
    cfg                    the configuration (config.py)
    cell                   the cell network (emu_cell/cell.py) or None (cell.network "off")
    start_mux(params)      AT+CMUX: switch the channel to the multiplexer once the OK has gone out
Every value marked [MOCK] is the simulator's own choice.
"""
from emu_cell import cell as CELL

ASYNC = object()                # a command that finishes later (its final result code comes from a callback)

# [MOCK] identification of the stand-in
MANUFACTURER = 'Simulator'
MODEL = 'DB3210 AT modem stand-in'
REVISION = 'emu_modem_at 1'
IMEI_BODY = '00101000000001'    # [MOCK] 14 digits; the 15th is the Luhn check digit

CSQ_IN_SERVICE = (31, 99)       # [MOCK] signal while the network has service: the bars mean "connected", not radio
SIGNAL_BARS_IN_SERVICE = 5      # [MOCK] +CIEV "signal" (0-5) in service
LAC, CI = '0001', '00000001'    # [MOCK] location area code and cell identity for +CREG=2
ACT_GSM = 0
SEND_LIMIT_NS = 60_000_000_000  # [MOCK] +CMGS gives +CMS ERROR: 332 when the network has not answered in 60 s
CAUSE_PROTOCOL_ERROR = 111       # RP cause "protocol error, unspecified" (3GPP TS 24.011 table 8.4)
TR2M_NS = 30_000_000_000        # the wait for +CNMA (3GPP TS 24.011 TR2M)
LINE_MAX = 560                  # a longer command line is cut: the characters beyond it are dropped
PDU_MAX = 2 * 200               # hexadecimal characters of a PDU after the prompt

CME_TEXT = {3: 'operation not allowed', 4: 'operation not supported', 10: 'SIM not inserted', 30: 'no network service',
            50: 'incorrect parameters', 100: 'unknown'}
INDICATORS = (('signal', '(0-5)'), ('service', '(0,1)'), ('roam', '(0,1)'))


def luhn(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return str(-total % 10)


IMEI = IMEI_BODY + luhn(IMEI_BODY)


class Error(Exception):
    """A final result code other than OK: kind 'cme' (+CME ERROR, after AT+CMEE), 'cms' (+CMS ERROR) or 'plain' (ERROR)."""

    def __init__(self, kind, code=0):
        self.kind, self.code = kind, code


def _args(text):
    """The parameters of a set command: [str or None]; a quoted one keeps its text, an empty one is None."""
    out, cur, quoted, inq, any_ = [], '', False, False, False
    for ch in text:
        if inq:
            if ch == '"': inq = False
            else: cur += ch
        elif ch == '"':
            inq = quoted = True
        elif ch == ',':
            out.append(cur if quoted else (cur.strip() or None)); cur, quoted = '', False
        elif ch != ' ':
            cur += ch
        any_ = True
    if inq: raise Error('plain')
    if any_: out.append(cur if quoted else (cur.strip() or None))
    return out


def _int(args, i, default, allowed):
    v = args[i] if i < len(args) else None
    if v is None:
        if default is None: raise Error('cme', 50)
        return default
    if not v.isdigit() or int(v) not in allowed: raise Error('cme', 50)
    return int(v)


def split(body):
    """The commands of a command line after "AT": [(name, op, args)]; name '+CSQ', 'E', '&F'; op '', '?', '=?' or '='."""
    out, i, s = [], 0, body
    while i < len(s):
        c = s[i]
        if c in ' ;':
            i += 1
        elif c == '+':
            j = i + 1
            while j < len(s) and (s[j].isalnum() or s[j] in '_'): j += 1
            name = '+' + s[i + 1:j].upper()
            k, inq = j, False                              # the rest of this command: to a ';' outside quotes
            while k < len(s) and (inq or s[k] != ';'):
                if s[k] == '"': inq = not inq
                k += 1
            rest = s[j:k].strip()
            if rest == '': op, args = '', []
            elif rest == '?': op, args = '?', []
            elif rest.replace(' ', '') == '=?': op, args = '=?', []
            elif rest.startswith('='): op, args = '=', _args(rest[1:])
            else: raise Error('plain')
            out.append((name, op, args)); i = k
        elif c.isalpha() or c == '&':
            j = i + 1 if c.isalpha() else i + 2
            if c == '&' and (i + 1 >= len(s) or not s[i + 1].isalpha()): raise Error('plain')
            name = s[i:j].upper()
            k = j
            while k < len(s) and s[k].isdigit(): k += 1
            out.append((name, '=', [s[j:k]] if k > j else [])); i = k
        else:
            raise Error('plain')
    return out


class AtEngine:
    def __init__(self, modem):
        self.m = modem
        self.inbuf = bytearray()          # bytes from the firmware not yet taken (kept while a command runs)
        self.line = bytearray()
        self.collect = None               # (function, hex characters so far) after a "> " prompt
        self.busy = False                 # a command line is executing: its final result code has not gone out
        self.cmds, self.done_lines = [], []
        self.held = []                    # unsolicited result codes held while busy: (text, function called when sent)
        self.mr = 0                       # TP-Message-Reference of the last message sent
        self.sending = None               # the +CMGS waiting for the network
        self.mt_queue, self.mt_wait = [], None    # messages for the phone; the one waiting for +CNMA
        self.full_refused = False         # the firmware refused a message with "memory capacity exceeded"
        self.cfun, self.cops = 1, 0       # [MOCK] the radio is on at power-on; automatic network selection
        self.csca = CELL.SERVICE_CENTRE
        self.csca_type = 145 if self.csca.startswith('+') else 129
        self.stats = {'lines': 0, 'errors': 0, 'sent': 0, 'received': 0, 'urcs': 0}
        self.defaults()
        self.shown = self.net_state()     # what the last unsolicited codes reported (none are sent at power-on)

    def defaults(self):
        """ATZ / AT&F: the settings of the channel (not the radio, the network selection or the service centre)."""
        self.echo, self.cmee, self.creg, self.cmer_mode, self.cmer_ind = True, 0, 0, 0, 0
        self.cnmi, self.csms, self.cops_format = [0, 0, 0, 0, 0], 0, 0
        self.mux_params = [0, 0, 5, 31, 10, 3, 30, 10, 2]

    # ---- state of the card and the network -------------------------------------------------------------
    def sim(self):
        return bool(self.m.cfg['sim.present'])

    def service(self):
        c = self.m.cell
        return c is not None and bool(getattr(c, 'service', True))

    def registered(self):
        return self.sim() and self.cfun == 1 and self.cops != 2 and self.service()

    def creg_stat(self):
        if not self.sim() or self.cfun != 1 or self.cops == 2:
            return 0                      # not registered, not searching
        return 1 if self.service() else 2  # registered (home network) / searching

    def net_state(self):
        reg = self.registered()
        return (self.creg_stat(), SIGNAL_BARS_IN_SERVICE if reg else 0, int(reg))

    def operator(self, fmt):
        imsi = self.m.cfg['sim.imsi']
        name = self.m.cfg['sim.spn'] or 'Simulator'        # [MOCK] the network's name is the card's service provider name
        return '"%s"' % (name, name, imsi[:5])[fmt]

    # ---- bytes in ----------------------------------------------------------------------------------------
    def feed(self, data):
        self.inbuf += data
        self._run()

    def reset_channel(self):
        """The AT channel was closed: a half-typed line and a prompt are dropped."""
        self.line.clear(); self.inbuf.clear()
        if self.collect is not None:
            self.collect = None
            self._end(None, quiet=True)

    def _run(self):
        while self.inbuf and not (self.busy and self.collect is None):
            b = self.inbuf.pop(0)
            if self.collect is not None:
                self._pdu_char(b)
            elif b == 13:
                if self.echo: self.m.at_write(b'\r')
                line, self.line = bytes(self.line), bytearray()
                self._line(line.decode('latin-1').strip())
            elif b == 10:
                if self.echo: self.m.at_write(b'\n')
            elif b in (8, 127):
                if self.line: self.line.pop()
                if self.echo: self.m.at_write(bytes([b]))
            else:
                if len(self.line) < LINE_MAX: self.line.append(b)
                if self.echo: self.m.at_write(bytes([b]))

    def _pdu_char(self, b):
        fn, text = self.collect
        if self.echo and b not in (0x1a, 0x1b): self.m.at_write(bytes([b]))
        if b == 0x1b:                                       # ESC: the message is not sent
            self.collect = None
            self._end(None)
        elif b == 0x1a:                                     # Ctrl-Z: the PDU is complete
            self.collect = None
            try:
                r = fn(text)
            except Error as e:
                return self._end(e)
            if r is not ASYNC:
                self._lines(r or ())
                self._next()
        elif chr(b) in '0123456789abcdefABCDEF' and len(text) < PDU_MAX:
            self.collect = (fn, text + chr(b))

    def _line(self, text):
        if text[:2].upper() != 'AT':
            return                                          # V.250: a line without the prefix is ignored
        self.stats['lines'] += 1
        self.text, self.done_lines = text, []
        self.busy = True
        try:
            self.cmds = split(text[2:])
        except Error as e:
            return self._end(e)
        self._next()

    def _next(self):
        while self.cmds:
            name, op, args = self.cmds.pop(0)
            fn = getattr(self, 'c_' + name.replace('+', 'p_').replace('&', 'amp_'), None)
            if fn is None:
                return self._end(Error('plain'))
            try:
                r = fn(op, args)
            except Error as e:
                return self._end(e)
            if r is ASYNC:
                return
            self._lines(r or ())
        self._end(None)

    # ---- bytes out ---------------------------------------------------------------------------------------
    def _lines(self, lines):
        for l in lines:
            self.done_lines.append(l)
            self.m.at_write(b'\r\n' + l.encode('latin-1') + b'\r\n')

    def _end(self, err, quiet=False):
        """The final result code of the command line; then the held unsolicited codes and the input that waited."""
        if err is None: code = 'OK'
        elif err.kind == 'cme' and self.cmee == 1: code = '+CME ERROR: %d' % err.code
        elif err.kind == 'cme' and self.cmee == 2: code = '+CME ERROR: %s' % CME_TEXT.get(err.code, 'unknown')
        elif err.kind == 'cms': code = '+CMS ERROR: %d' % err.code
        else: code = 'ERROR'
        if err is not None: self.stats['errors'] += 1
        if not quiet:
            self.m.at_write(b'\r\n' + code.encode() + b'\r\n')
            self.m.say('AT  %s -> %s' % (getattr(self, 'text', '?'), ' | '.join(self.done_lines + [code])))
        self.busy, self.cmds = False, []
        mux, self.m.mux_request = self.m.mux_request, None
        if mux is not None and err is None:                 # AT+CMUX: what follows the command line belongs to the multiplexer
            rest, self.inbuf = bytes(self.inbuf), bytearray()
            self.m.start_mux(mux, rest)
        held, self.held = self.held, []
        for text, sent, lost in held:
            self.urc(text, sent, lost)
        self._run()

    def urc(self, text, sent=None, lost=None):
        """An unsolicited result code: out at once, or after the final result code of the command line that runs.
        sent() is called when it went out; lost() when the AT channel is closed and it cannot (the return value is then False)."""
        if not self.m.at_open():
            if lost: lost()
            return False
        if self.busy:
            self.held.append((text, sent, lost))
            return True
        self.stats['urcs'] += 1
        self.m.at_write(b'\r\n' + text.encode('latin-1') + b'\r\n')
        self.m.say('URC %s' % text.split('\r\n')[0])
        if sent: sent()
        return True

    # ---- network events ----------------------------------------------------------------------------------
    def update_network(self):
        """The registration, the signal or the service changed (or may have): the unsolicited codes the firmware asked for."""
        now = self.net_state()
        old, self.shown = self.shown, now
        if now[0] != old[0] and self.creg:
            self.urc(self._creg_text(now[0], False))
        if self.cmer_mode == 3 and self.cmer_ind:
            for i in (1, 2):
                if now[i] != old[i]:
                    self.urc('+CIEV: %d,%d' % (i, now[i]))
        if not self.registered():
            self._refuse_queue()

    def _creg_text(self, stat, read):
        head = '+CREG: %d,%d' % (self.creg, stat) if read else '+CREG: %d' % stat
        if self.creg == 2 and stat in (1, 5):
            head += ',"%s","%s",%d' % (LAC, CI, ACT_GSM)
        return head

    def deliver(self, centre, tpdu, report):
        """A message of the network for the phone (cell.CellPort.deliver). False: the phone cannot take it now."""
        if not self.registered() or not self.m.at_open() or self.cnmi[1] != 2 or not centre or len(tpdu) > 255:
            return False
        self.mt_queue.append((bytes(centre), bytes(tpdu), report or (lambda ok, cause: None)))
        self._mt_next()
        return True

    def _refuse_queue(self):
        q, self.mt_queue = self.mt_queue, []
        for _, _, report in q:
            report(False, 0)

    def _mt_next(self):
        """The next message for the phone as +CMT, one at a time: the next only when the one before was acknowledged."""
        while self.mt_wait is None and self.mt_queue:
            centre, tpdu, report = self.mt_queue.pop(0)
            if self.cnmi[1] != 2:
                report(False, 0); continue
            pdu = bytes([len(centre)]) + centre + tpdu
            text = '+CMT: ,%d\r\n%s' % (len(tpdu), pdu.hex().upper())
            self.stats['received'] += 1
            if self.csms == 0:                              # phase 2: the stand-in acknowledges when the code went out
                self.urc(text, lambda r=report: r(True, 0), lambda r=report: r(False, 0))
                continue
            entry = self.mt_wait = [report]
            def lost(entry=entry):
                if self.mt_wait is entry:
                    self.mt_wait = None
                    entry[0](False, 0)
                    self._mt_next()
            self.urc(text, lambda entry=entry: self.m.schedule(TR2M_NS, lambda: self._mt_timeout(entry)), lost)

    def _mt_timeout(self, entry):
        if self.mt_wait is not entry:
            return
        self.m.say('no +CNMA in %d s: the network hears RP-ERROR %d; +CNMI <mt> and <ds> set to 0 (3GPP TS 27.005)' % (
            TR2M_NS // 10**9, CAUSE_PROTOCOL_ERROR))
        self.cnmi[1] = self.cnmi[3] = 0
        self._mt_done(False, CAUSE_PROTOCOL_ERROR)
        self._refuse_queue()

    def _mt_done(self, ok, cause):
        report, self.mt_wait = self.mt_wait[0], None
        if not ok and cause == CELL.CAUSE_MEMORY_EXCEEDED:
            self.full_refused = True
        report(ok, cause)
        self._mt_next()

    # ---- V.250 basic commands ----------------------------------------------------------------------------
    def _flag(self, args, allowed=(0, 1)):
        v = args[0] if args else '0'
        if not v.isdigit() or int(v) not in allowed: raise Error('plain')
        return int(v)

    def c_E(self, op, args): self.echo = bool(self._flag(args))
    def c_V(self, op, args): self._flag(args, (1,))
    def c_Q(self, op, args): self._flag(args, (0,))
    def c_Z(self, op, args): self._flag(args, (0,)); self.defaults()
    def c_amp_F(self, op, args): self._flag(args, (0,)); self.defaults()
    def c_I(self, op, args): self._flag(args, (0,)); return [MANUFACTURER, MODEL, REVISION]

    # ---- 3GPP TS 27.007 ------------------------------------------------------------------------------------
    def _plain_query(self, op, value):
        if op == '=?': return []
        if op != '': raise Error('cme', 4)
        return [value]

    def c_p_CGMI(self, op, args): return self._plain_query(op, MANUFACTURER)
    def c_p_CGMM(self, op, args): return self._plain_query(op, MODEL)
    def c_p_CGMR(self, op, args): return self._plain_query(op, REVISION)
    def c_p_CGSN(self, op, args): return self._plain_query(op, IMEI)

    def c_p_CMEE(self, op, args):
        if op == '=?': return ['+CMEE: (0-2)']
        if op == '?': return ['+CMEE: %d' % self.cmee]
        if op == '=': self.cmee = _int(args, 0, 0, range(3)); return
        raise Error('cme', 4)

    def c_p_CPIN(self, op, args):
        if op == '=?': return []
        if not self.sim(): raise Error('cme', 10)
        if op == '?': return ['+CPIN: READY']
        raise Error('cme', 3)               # the card is READY and asks for nothing: entering a code is not allowed

    def c_p_CIMI(self, op, args):
        if op == '=?': return []
        if not self.sim(): raise Error('cme', 10)
        return self._plain_query(op, self.m.cfg['sim.imsi'])

    def c_p_CNUM(self, op, args):
        if op == '=?': return []
        if op != '': raise Error('cme', 4)
        if not self.sim(): raise Error('cme', 10)
        n = self.m.number()
        return ['+CNUM: ,"%s",%d' % (n, 145 if n.startswith('+') else 129)] if n else []

    def c_p_CFUN(self, op, args):
        if op == '=?': return ['+CFUN: (0,1,4),(0)']
        if op == '?': return ['+CFUN: %d' % self.cfun]
        if op != '=': raise Error('cme', 4)
        fun = _int(args, 0, None, (0, 1, 4)); _int(args, 1, 0, (0,))
        self.cfun = fun
        self.m.say('radio %s (+CFUN=%d)' % ('on' if fun == 1 else 'off', fun))
        self.update_network()

    def c_p_COPS(self, op, args):
        if op == '=?':
            have = '(2,"%s","%s","%s",%d),' % (*(self.operator(f).strip('"') for f in range(3)), ACT_GSM) if self.registered() else ''
            return ['+COPS: %s,(0,2,3),(0-2)' % (have or ',')]
        if op == '?':
            if self.registered():
                return ['+COPS: %d,%d,%s,%d' % (self.cops, self.cops_format, self.operator(self.cops_format), ACT_GSM)]
            return ['+COPS: %d' % self.cops]
        if op != '=': raise Error('cme', 4)
        mode = _int(args, 0, None, (0, 2, 3))
        if mode == 3:
            self.cops_format = _int(args, 1, 0, range(3)); return
        if len(args) > 1: raise Error('cme', 50)
        if mode == 0 and not self.sim(): raise Error('cme', 10)
        self.cops = mode
        self.update_network()

    def c_p_CREG(self, op, args):
        if op == '=?': return ['+CREG: (0-2)']
        if op == '?': return [self._creg_text(self.creg_stat(), True)]
        if op != '=': raise Error('cme', 4)
        self.creg = _int(args, 0, 0, range(3))

    def c_p_CSQ(self, op, args):
        if op == '=?': return ['+CSQ: (0-31,99),(0-7,99)']
        if op != '': raise Error('cme', 4)
        return ['+CSQ: %d,%d' % (CSQ_IN_SERVICE if self.registered() else (99, 99))]

    def c_p_CIND(self, op, args):
        if op == '=?': return ['+CIND: ' + ','.join('("%s",%s)' % i for i in INDICATORS)]
        if op == '?': s = self.net_state(); return ['+CIND: %d,%d,0' % (s[1], s[2])]
        raise Error('cme', 4)

    def c_p_CMER(self, op, args):
        if op == '=?': return ['+CMER: (0,3),(0),(0),(0,1),(0)']
        if op == '?': return ['+CMER: %d,0,0,%d,0' % (self.cmer_mode, self.cmer_ind)]
        if op != '=': raise Error('cme', 4)
        mode = _int(args, 0, 0, (0, 3))
        for i in (1, 2, 4): _int(args, i, 0, (0,))
        self.cmer_mode, self.cmer_ind = mode, _int(args, 3, 0, (0, 1))

    def c_p_CCLK(self, op, args):
        if op == '=?': return []
        if op == '=': raise Error('cme', 3)        # the clock is the network's
        if op != '?': raise Error('cme', 4)
        t = CELL.time_stamp(CELL.EPOCH + self.m.now_ns() // 1_000_000_000)
        d = [(b & 15) * 10 + (b >> 4) for b in t[:6]]
        return ['+CCLK: "%02d/%02d/%02d,%02d:%02d:%02d+00"' % tuple(d)]

    def c_p_CMUX(self, op, args):
        if op == '=?': return ['+CMUX: (0),(0),(1-6),(1-1024),(1-255),(0-100),(2-255),(1-255),(1-7)']
        if op == '?': return ['+CMUX: ' + ','.join(str(v) for v in self.mux_params)]
        if op != '=': raise Error('cme', 4)
        if not self.m.raw_mode(): raise Error('cme', 3)       # already multiplexed
        ranges = (range(1), range(1), range(1, 7), range(1, 1025), range(1, 256), range(101), range(2, 256), range(1, 256), range(1, 8))
        if len(args) > len(ranges): raise Error('cme', 50)
        p = [_int(args, i, self.mux_params[i], ranges[i]) for i in range(len(ranges))]
        self.mux_params = p
        self.m.mux_request = p

    # ---- 3GPP TS 27.005 ------------------------------------------------------------------------------------
    def c_p_CSMS(self, op, args):
        if op == '=?': return ['+CSMS: (0,1)']
        if op == '?': return ['+CSMS: %d,1,1,0' % self.csms]
        if op != '=': raise Error('cms', 302)
        v = args[0] if args else None
        if v not in ('0', '1'): raise Error('plain')
        self.csms = int(v)
        return ['+CSMS: 1,1,0']

    def c_p_CMGF(self, op, args):
        if op == '=?': return ['+CMGF: (0)']
        if op == '?': return ['+CMGF: 0']
        if op != '=': raise Error('cms', 302)
        if (args[0] if args else '0') != '0': raise Error('cms', 303)     # text mode is not supported

    def c_p_CSCA(self, op, args):
        if op == '=?': return []
        if op == '?': return ['+CSCA: "%s",%d' % (self.csca, self.csca_type)]
        if op != '=': raise Error('cms', 302)
        if not args or args[0] is None: raise Error('plain')
        try: CELL.address_field(args[0])
        except ValueError: raise Error('plain')
        self.csca = args[0]
        self.csca_type = int(args[1]) if len(args) > 1 and args[1] and args[1].isdigit() else (145 if args[0].startswith('+') else 129)

    def c_p_CNMI(self, op, args):
        if op == '=?': return ['+CNMI: (0-2),(0,2),(0),(0),(0,1)']
        if op == '?': return ['+CNMI: %d,%d,%d,%d,%d' % tuple(self.cnmi)]
        if op != '=': raise Error('cms', 302)
        ranges = ((0, 1, 2), (0, 2), (0,), (0,), (0, 1))
        new = []
        for i, r in enumerate(ranges):
            v = args[i] if i < len(args) else None
            if v is None: new.append(0 if i else self.cnmi[0]); continue
            if not v.isdigit(): raise Error('plain')
            if int(v) not in r: raise Error('cms', 303)
            new.append(int(v))
        self.cnmi = new
        if new[1] == 2 and self.full_refused and self.m.cell is not None and self.registered():
            self.full_refused = False                       # [MOCK] room again: the network hears RP-SMMA
            self.m.say('RP-SMMA: the firmware takes messages again after a refusal for lack of room')
            self.m.cell.memory_available(lambda ok, cause=0, report=b'': None)

    def c_p_CMGS(self, op, args):
        if op == '=?': return []
        if op != '=': raise Error('cms', 302)
        length = args[0] if args else None
        if length is None or not length.isdigit() or not 7 <= int(length) <= 175: raise Error('cms', 304)
        self.collect = (lambda text: self._send(int(length), text), '')
        self.m.at_write(b'\r\n> ')
        return ASYNC

    def _send(self, length, text):
        try:
            pdu = bytes.fromhex(text)
        except ValueError:
            raise Error('cms', 304)
        if not pdu or len(pdu) != 1 + pdu[0] + length or pdu[0] > 11:
            raise Error('cms', 304)
        centre, tpdu = pdu[1:1 + pdu[0]], bytearray(pdu[1 + pdu[0]:])
        if tpdu[0] & 3 != 1:
            raise Error('cms', 304)                          # only SMS-SUBMIT
        if not centre:
            centre = CELL.address_field(self.csca)[1:] if self.csca else b''
            if self.csca_type in (129, 145): centre = bytes([self.csca_type]) + centre[1:]
        if not centre: raise Error('cms', 330)
        if not self.sim(): raise Error('cms', 310)
        if not self.registered(): raise Error('cms', 331)
        self.mr = (self.mr + 1) & 0xff
        tpdu[1] = self.mr                                   # the modem gives the message its reference (3GPP TS 23.040)
        mine = self.sending = [self.mr]
        net = self.m.cell
        self.m.say('CELL  +CMGS reference %d, %d octets, through service centre %s: given to the network "%s"' % (
            self.mr, len(tpdu), CELL.digits(centre), net.name))
        def done(ok, cause=0, report=b''):
            self.m.schedule(0, lambda: self._sent(mine, ok, cause, report))
        self.m.schedule(SEND_LIMIT_NS, lambda: self._sent(mine, None, 0, b''))
        net.submit(bytes(centre), bytes(tpdu), done)
        self.stats['sent'] += 1
        return ASYNC

    def _sent(self, mine, ok, cause, report):
        if self.sending is not mine:
            if ok is not None: self.m.say('CELL  late answer of the network for reference %d ignored' % mine[0])
            return
        self.sending = None
        if ok is None:
            return self._end(Error('cms', 332))
        if not ok:
            return self._end(Error('cms', cause if 0 < cause < 128 else 500))
        self._lines(['+CMGS: %d%s' % (mine[0], ',' + bytes(report).hex().upper() if report and self.csms == 1 else '')])
        self._end(None)

    def c_p_CNMA(self, op, args):
        if op == '=?': return ['+CNMA: (0-2)']
        if op not in ('', '='): raise Error('cms', 302)
        if self.mt_wait is None: raise Error('cms', 340)
        n = _int(args, 0, 0, range(3)) if op == '=' else 0
        if n == 2 and len(args) > 1 and args[1] not in (None, '0'):
            if not args[1].isdigit() or not 2 <= int(args[1]) <= 175: raise Error('cms', 304)
            self.collect = (lambda text: self._refuse(int(args[1]), text), '')
            self.m.at_write(b'\r\n> ')
            return ASYNC
        if n == 2:
            self._mt_done(False, CAUSE_PROTOCOL_ERROR)
        else:
            self._mt_done(True, 0)

    def _refuse(self, length, text):
        """+CNMA=2 with an SMS-DELIVER-REPORT: its TP-FCS chooses the RP cause (3GPP TS 23.040 9.2.3.22, 24.011 8.2.5.4)."""
        try:
            pdu = bytes.fromhex(text)
        except ValueError:
            raise Error('cms', 304)
        if len(pdu) != length or len(pdu) < 2: raise Error('cms', 304)
        if self.mt_wait is None: raise Error('cms', 340)
        self._mt_done(False, CELL.CAUSE_MEMORY_EXCEEDED if pdu[1] in (0xD0, 0xD3) else 111)
