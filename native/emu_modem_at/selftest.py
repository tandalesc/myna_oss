"""Selftest of the AT modem stand-in. No firmware needed:  native/.venv/bin/python -I native/emu_modem_at/selftest.py

A Python "firmware side" drives the application's end of the link model (emu_link.AaifLink side A) through its registers,
as a firmware would: programmed I/O on channel 0, and in one test the DMA controller model. Checked: the 27.010 frame check
sequence and framing, the AT dialogue in raw mode and on DLC 1, text messages on the loopback and host networks (submit,
deliver, +CNMA, refusals, time-outs), unsolicited codes on service changes, that the stand-in is quiet until the firmware
speaks, and that a network event handed in from outside a run wakes a sleeping CPU at once.
With --launcher (and myna/firmware/build/myna.elf built) also a run of the Myna device through the launcher, on Unicorn and on
the compiled core (DBCORE_OUT names its build folder when it is not native/core/build).
"""
import os, struct, sys
NATIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, NATIVE)
from emu_link import AaifLink, Dmac
from emu_cell import cell as CELL
from emu_modem_at import cmux as MUX, config as CONFIG, at as AT
from emu_modem_at.modem import AtModem

MS = 1_000_000
S = 1_000_000_000


class Fw:
    """The firmware's end of the link: channel 0 by programmed I/O, receive interrupt on data."""

    def __init__(self, link, enable=True):
        self.a = link.a
        if enable:
            self.a.write(0x000, 4, 1)           # TX0 enable
            self.a.write(0x200, 4, 1)           # RX0 enable
            self.a.write(0x20c, 4, 8)           # RX0 interrupt while data
            self.a.write(0x500, 4, 0x100)       # channel interrupt enable: receive channel 0

    def room(self):
        return 64 - self.a.read(0x008, 4)

    def put(self, data):
        n = min(len(data), self.room())
        for b in data[:n]:
            self.a.write(0x020, 1, b)
        return n

    def get(self):
        out = bytearray()
        while self.a.read(0x208, 4):
            out.append(self.a.read(0x220, 1))
        return bytes(out)


class Bench:
    def __init__(self, enable=True, **conf):
        self.t = 0
        self.log = []
        self.lines = {}
        self.link = AaifLink(set_line_a=lambda n, l: self.lines.__setitem__(n, l))
        CONFIG.use(dict({'sim.present': True, 'cell.network': 'loopback'}, **conf))
        try:
            cfg, _ = CONFIG.load({})
        finally:
            CONFIG.use(None)
        self.m = AtModem(self.link.b, lambda: self.t, self.log.append, cfg=cfg)
        self.m.start()
        self.fw = Fw(self.link, enable)
        self.got = bytearray()

    def run(self, ns, step=100_000):
        end = self.t + ns
        while self.t < end:
            self.t = min(end, self.t + step)
            self.m.tick()
            self.got += self.fw.get()

    def send(self, data, ns=2 * MS):
        data = bytes(data)
        while data:
            n = self.fw.put(data)
            data = data[n:]
            self.run(100_000)
        self.run(ns)

    def take(self):
        out, self.got = bytes(self.got), bytearray()
        return out

    def at(self, line, ns=2 * MS):
        self.send(line.encode() + b'\r', ns)
        return self.take().decode('latin-1')


def ok(*lines):
    return ''.join('\r\n%s\r\n' % l for l in lines + ('OK',))


# ---------------------------------------------------------------------------------------------------------------------
def test_fcs_and_frames():
    """27.010 known frames (the FCS of Annex B), the two-octet length, UI frames, and a parser that resyncs after damage."""
    assert MUX.frame(0, MUX.SABM | MUX.PF, cr=1) == bytes.fromhex('F9033F011CF9')
    assert MUX.frame(0, MUX.UA | MUX.PF, cr=1) == bytes.fromhex('F90373 01D7F9'.replace(' ', ''))
    assert MUX.frame(0, MUX.DISC | MUX.PF, cr=1) == bytes.fromhex('F9035301FDF9')
    p = MUX.Parser()
    big = bytes(range(256)) * 2
    stream = (b'\x00junk' + MUX.frame(1, MUX.UIH, b'AT\r', 1) + MUX.frame(5, MUX.UIH, big) + bytes.fromhex('F9033F01FFF9')
              + MUX.frame(2, MUX.UI, b'ui', 1) + MUX.frame(1, MUX.UIH, b'x'))
    fs = []
    for i in range(0, len(stream), 7):
        fs += p.feed(stream[i:i + 7])
    assert [(f.dlci, f.kind, f.info) for f in fs] == [(1, MUX.UIH, b'AT\r'), (5, MUX.UIH, big), (2, MUX.UI, b'ui'), (1, MUX.UIH, b'x')]
    assert p.errors == 1 and 'FCS' in p.last_error and fs[0].cr == 1 and fs[1].cr == 0
    assert MUX.length_field(127) == b'\xff' and MUX.length_field(128) == b'\x00\x01'
    assert MUX.parse_messages(MUX.message(MUX.MSC, b'\x07\x8d') + MUX.message(MUX.TEST, b'hi', command=False)) == [(0xE3, b'\x07\x8d'), (0x21, b'hi')]
    return 'SABM / UA / DISC of DLC 0 with their published FCS; 512-octet frame; bad FCS dropped and the next frame found'


def test_quiet_until_spoken_to():
    b = Bench()
    b.run(500 * MS, 10 * MS)
    assert b.take() == b'' and b.m.stats['tx'] == 0 and not b.m.link_up and not b.lines.get(5)
    b.m.cell.port.deliver(bytes.fromhex('81555001'), bytes.fromhex('0407815505f90000800102210000000148'))
    b.run(10 * MS)
    assert b.take() == b'' and b.m.stats['tx'] == 0
    q = Bench(enable=False)                     # the firmware never enables its channel: nothing reaches it
    q.run(10 * MS)
    assert q.link.a.read(0x208, 4) == 0 and not q.m.link_up
    return 'no byte and no interrupt until the firmware sends; a message for a silent phone is refused'


def test_at_basics():
    b = Bench(**{'phone.number': '+811577966830'})
    assert b.at('AT') == 'AT\r' + ok()                                  # echo on at power-on (V.250)
    assert b.at('ATE0') == 'ATE0\r' + ok()
    assert b.at('at') == ok()
    assert b.at('AT+CGMI;+CGMM;+CGMR') == ok(AT.MANUFACTURER, AT.MODEL, AT.REVISION)
    imei = b.at('AT+CGSN')
    assert imei == ok(AT.IMEI) and len(AT.IMEI) == 15 and AT.luhn(AT.IMEI[:14]) == AT.IMEI[14]
    assert b.at('ATI') == ok(AT.MANUFACTURER, AT.MODEL, AT.REVISION)
    assert b.at('AT+FOO') == '\r\nERROR\r\n'
    assert b.at('AT+CPIN=1234') == '\r\nERROR\r\n'                      # CMEE=0: plain ERROR
    assert b.at('AT+CMEE=1') == ok()
    assert b.at('AT+CPIN?') == ok('+CPIN: READY')
    assert b.at('AT+CPIN="1234"') == '\r\n+CME ERROR: 3\r\n'
    assert b.at('AT+CMEE=2;+CPIN="1"') == '\r\n+CME ERROR: operation not allowed\r\n'
    assert b.at('AT+CMEE=1;+CIMI') == ok('001010123456789')
    assert b.at('AT+CNUM') == ok('+CNUM: ,"+811577966830",145')
    b.m.set_number('3246')
    assert b.at('AT+CNUM') == ok('+CNUM: ,"3246",129')
    assert b.at('AT+COPS?') == ok('+COPS: 0,0,"Simulator",0')
    assert b.at('AT+COPS=3,2;+COPS?') == ok('+COPS: 0,2,"00101",0')
    assert b.at('AT+COPS=?') == ok('+COPS: (2,"Simulator","Simulator","00101",0),,(0,2,3),(0-2)')
    assert b.at('AT+CSQ') == ok('+CSQ: 31,99')
    assert b.at('AT+CREG?') == ok('+CREG: 0,1')
    assert b.at('AT+CREG=2;+CREG?') == ok('+CREG: 2,1,"0001","00000001",0')
    assert b.at('AT+CREG=3') == '\r\n+CME ERROR: 50\r\n'
    assert b.at('AT+CCLK?') == ok('+CCLK: "08/10/20,12:00:00+00"')
    b.run(83 * S, 100 * MS)
    assert b.at('AT+CCLK?') == ok('+CCLK: "08/10/20,12:01:23+00"')
    assert b.at('AT+CIND=?') == ok('+CIND: ("signal",(0-5)),("service",(0,1)),("roam",(0,1))')
    assert b.at('AT+CIND?') == ok('+CIND: 5,1,0')
    assert b.at('AT+CMER=3,0,0,1') == ok()
    # radio off: unsolicited codes after the final result code of the command that caused them
    assert b.at('AT+CFUN=4') == ok() + '\r\n+CREG: 0\r\n\r\n+CIEV: 1,0\r\n\r\n+CIEV: 2,0\r\n'
    assert b.at('AT+CSQ;+CFUN?') == ok('+CSQ: 99,99', '+CFUN: 4')
    assert b.at('AT+CFUN=1') == ok() + '\r\n+CREG: 1,"0001","00000001",0\r\n\r\n+CIEV: 1,5\r\n\r\n+CIEV: 2,1\r\n'
    assert b.at('AT+COPS=2') == ok() + '\r\n+CREG: 0\r\n\r\n+CIEV: 1,0\r\n\r\n+CIEV: 2,0\r\n'
    assert b.at('AT+COPS?') == ok('+COPS: 2')
    b.at('AT+COPS=0')
    assert b.at('ATZ;+CREG?') == ok('+CREG: 0,1')                     # ATZ: channel settings back (echo on again)
    assert b.at('ATE0') == 'ATE0\r' + ok()
    b.send(b'AT+CS\x08\x08CSQ\r'); assert b.take() == ok('+CSQ: 31,99').encode()     # backspace
    b.send(b'hello\r\nAT\r'); assert b.take() == ok().encode()                         # a line without AT is ignored
    nos = Bench(**{'sim.present': False})
    assert nos.at('ATE0;+CMEE=1') == 'ATE0;+CMEE=1\r' + ok()
    assert nos.at('AT+CPIN?') == '\r\n+CME ERROR: 10\r\n' and nos.at('AT+CIMI') == '\r\n+CME ERROR: 10\r\n'
    assert nos.at('AT+CREG?') == ok('+CREG: 0,0') and nos.at('AT+CSQ') == ok('+CSQ: 99,99')
    off = Bench(**{'cell.network': 'off'})
    off.at('ATE0')
    assert off.m.cell is None and off.at('AT+CREG?') == ok('+CREG: 0,2') and off.at('AT+COPS?') == ok('+COPS: 0')
    return 'echo, identity, card READY / not inserted, CNUM, COPS, CREG 0-2, CSQ, CIND / CMER / CIEV, CCLK, CFUN, error forms'


def submit_pdu(text='Hi', to='5550199', sca=b'\x00'):
    """An SMS-SUBMIT in PDU mode (TP-MR 0, 7-bit text up to 7 characters for the test), with the SCA octets in front."""
    septets = [ord(c) for c in text]
    bits, acc, nb = bytearray(), 0, 0
    for s in septets:
        acc |= s << nb; nb += 7
        while nb >= 8:
            bits.append(acc & 0xff); acc >>= 8; nb -= 8
    if nb: bits.append(acc)
    tpdu = bytes([0x11, 0]) + CELL.address_field(to) + bytes([0, 0, 0xff, len(septets)]) + bytes(bits)
    return sca + tpdu, len(tpdu)


def test_sms_loopback():
    b = Bench()
    assert b.at('ATE0;+CMEE=1;+CMGF=0;+CNMI=2,2') == 'ATE0;+CMEE=1;+CMGF=0;+CNMI=2,2\r' + ok()
    assert b.at('AT+CMGF=1') == '\r\n+CMS ERROR: 303\r\n' and b.at('AT+CSCA?') == ok('+CSCA: "5550100",129')
    pdu, n = submit_pdu()
    assert b.at('AT+CMGS=%d' % n) == '\r\n> '
    b.send(pdu.hex().upper().encode() + b'\x1a', 1400 * MS)
    assert b.take() == b''                                              # the loopback network answers after 1.5 s
    b.run(200 * MS)
    assert b.take() == ok('+CMGS: 1').encode()
    b.run(2800 * MS, MS); assert b.take() == b''
    b.run(300 * MS, MS)
    tpdu = bytearray(pdu[1:]); tpdu[1] = 1
    deliver = CELL.submit_to_deliver(bytes(tpdu), CELL.EPOCH)      # stamped when the network took it
    sca = CELL.address_field('5550100')[1:]
    got = b.take().decode()
    assert got == '\r\n+CMT: ,%d\r\n%s\r\n' % (len(deliver), (bytes([len(sca)]) + sca + deliver).hex().upper()), got
    assert b.at('AT+CNMA') == '\r\n+CMS ERROR: 340\r\n'                 # phase 2 (+CSMS=0): the stand-in acknowledged
    # an ESC cancels; a wrong length is refused
    assert b.at('AT+CMGS=%d' % n) == '\r\n> '
    b.send(b'0011\x1b'); assert b.take() == ok().encode()
    assert b.at('AT+CMGS=%d' % (n + 1)) == '\r\n> '
    b.send(pdu.hex().encode() + b'\x1a'); assert b.take() == b'\r\n+CMS ERROR: 304\r\n'
    # +CSMS=1: the firmware acknowledges; a refusal for lack of room is kept by the network until +CNMI is given again
    assert b.at('AT+CSMS=1') == ok('+CSMS: 1,1,0')
    b.at('AT+CMGS=%d' % n); b.send(pdu.hex().encode() + b'\x1a', 4600 * MS)
    out = b.take().decode()
    assert out.startswith(ok('+CMGS: 2')) and '+CMT: ,%d' % len(deliver) in out, out
    b.send(b'AT+CNMA=2,2\r'); assert b.take() == b'\r\n> '
    b.send(b'00D3\x1a'); assert b.take() == ok().encode()
    assert len(b.m.cell.held) == 1 and b.m.engine.full_refused
    assert b.at('AT+CNMI=2,2', 4600 * MS).startswith(ok() + '\r\n+CMT: ,%d' % len(deliver)) and not b.m.cell.held
    assert b.at('AT+CNMA') == ok()                                       # accepted this time
    # no +CNMA in 30 s: the network hears a refusal, and +CNMI <mt> goes to 0 (27.005)
    b.at('AT+CMGS=%d' % n); b.send(pdu.hex().encode() + b'\x1a', 4600 * MS); b.take()
    b.run(29 * S, 100 * MS); assert b.at('AT+CNMI?') == ok('+CNMI: 2,2,0,0,0')
    b.run(2 * S, 100 * MS); assert b.at('AT+CNMI?') == ok('+CNMI: 2,0,0,0,0')
    assert any('no +CNMA in 30 s' in l for l in b.log)
    # a message while a command line runs waits for its final result code
    b.at('AT+CNMI=2,2;+CSMS=0')
    b.at('AT+CMGS=%d' % n); b.send(pdu.hex().encode() + b'\x1a', 4400 * MS)
    assert b.take() == ok('+CMGS: 4').encode()
    b.send(b'AT+CMGS=%d\r' % n, 400 * MS)                                # prompt open while the message arrives
    assert b.take() == b'\r\n> '
    b.send(b'\x1b'); assert b.take().decode().startswith(ok() + '\r\n+CMT: ,')
    nos = Bench(**{'sim.present': False})
    nos.at('ATE0'); nos.at('AT+CMGS=%d' % n); nos.send(pdu.hex().encode() + b'\x1a')
    assert nos.take() == b'\r\n+CMS ERROR: 310\r\n'
    off = Bench(**{'cell.network': 'off'})
    off.at('ATE0'); off.at('AT+CMGS=%d' % n); off.send(pdu.hex().encode() + b'\x1a')
    assert off.take() == b'\r\n+CMS ERROR: 331\r\n'
    return 'submit -> +CMGS after 1.5 s -> +CMT 3 s later; ESC, bad length; +CSMS=1 with +CNMA, refusal 22 and RP-SMMA, 30 s time-out; no card; no network'


def test_sms_host():
    b = Bench(**{'cell.network': 'host'})
    net = b.m.cell
    assert net.name == 'host' and not net.service
    assert b.at('ATE0;+CMEE=1;+CREG=1;+CNMI=2,2;+CSMS=1') == 'ATE0;+CMEE=1;+CREG=1;+CNMI=2,2;+CSMS=1\r' + ok('+CSMS: 1,1,0')
    assert b.at('AT+CREG?') == ok('+CREG: 1,2') and b.at('AT+CSQ') == ok('+CSQ: 99,99')
    pdu, n = submit_pdu('Yo', '811577966830')
    b.at('AT+CMGS=%d' % n); b.send(pdu.hex().encode() + b'\x1a')
    assert b.take() == b'\r\n+CMS ERROR: 331\r\n' and net.take() == []
    net.set_service(True); b.run(MS)
    assert b.take() == b'\r\n+CREG: 1\r\n' and b.at('AT+CSQ') == ok('+CSQ: 31,99')
    b.at('AT+CMGS=%d' % n); b.send(pdu.hex().encode() + b'\x1a', 10 * MS)
    (k, sc, tpdu), = net.take()
    assert sc == CELL.address_field('5550100')[1:] and tpdu[1] == 1 and tpdu[2:] == pdu[3:] and b.take() == b''
    net.result(k, True, 0, ); b.run(MS)
    assert b.take() == ok('+CMGS: 1').encode()
    b.at('AT+CMGS=%d' % n); b.send(pdu.hex().encode() + b'\x1a', 10 * MS)
    (k, _, _), = net.take(); net.result(k, False, 27); b.run(MS)
    assert b.take() == b'\r\n+CMS ERROR: 27\r\n'
    b.at('AT+CMGS=%d' % n); b.send(pdu.hex().encode() + b'\x1a', 10 * MS)
    (k, _, _), = net.take(); b.run(60 * S, 100 * MS)
    assert b.take() == b'\r\n+CMS ERROR: 332\r\n'                       # the network never answered
    net.result(k, True); b.run(MS); assert b.take() == b'' and any('late answer' in l for l in b.log)
    # a message for the phone: +CMT, the firmware's +CNMA goes back to the program
    heard = []
    deliver = bytes.fromhex('040C9181517796860300008001022100000002D937')
    net.incoming(bytes.fromhex('81555001'), deliver, lambda acc, cause: heard.append((acc, cause))); b.run(MS)
    assert b.take().decode() == '\r\n+CMT: ,%d\r\n0481555001%s\r\n' % (len(deliver), deliver.hex().upper()) and heard == []
    assert b.at('AT+CNMA') == ok() and heard == [(True, 0)]
    net.incoming(bytes.fromhex('81555001'), deliver, lambda acc, cause: heard.append((acc, cause))); b.run(MS); b.take()
    assert b.at('AT+CNMA=2') == ok() and heard[-1] == (False, 111)
    net.set_service(False); b.run(MS)
    assert b.take() == b'\r\n+CREG: 2\r\n'
    net.incoming(bytes.fromhex('81555001'), deliver, lambda acc, cause: heard.append((acc, cause))); b.run(MS)
    assert heard[-1] == (False, 0) and b.take() == b''                  # no service: not delivered
    net.set_service(True); b.run(MS); b.take()
    b.at('AT+CNMI=0,0')
    net.incoming(bytes.fromhex('81555001'), deliver, lambda acc, cause: heard.append((acc, cause))); b.run(MS)
    assert heard[-1] == (False, 0) and b.take() == b''                  # +CNMI <mt> 0: the phone takes no message
    return 'no service: 331 and +CREG 2; service: +CREG 1, take / result ok / cause 27 / no answer 332; incoming +CMT, +CNMA ack and refusal; refused without service or +CNMI'


def test_cmux():
    b = Bench(**{'cell.network': 'host'})
    p = MUX.Parser()
    def frames(ns=2 * MS):
        b.run(ns)
        return [(f.dlci, f.cr, f.control, f.info) for f in p.feed(b.take())]
    def send(dlci, control, info=b'', ns=2 * MS):
        b.send(MUX.frame(dlci, control, info, cr=1), 0)
        return frames(ns)
    assert b.at('ATE0') == 'ATE0\r' + ok() and b.at('AT+CMUX?') == ok('+CMUX: 0,0,5,31,10,3,30,10,2')
    assert b.at('AT+CMUX=1') == '\r\nERROR\r\n'
    assert b.at('AT+CMUX=0') == ok() and b.m.mode == 'mux'
    assert send(0, MUX.SABM | MUX.PF) == [(0, 1, MUX.UA | MUX.PF, b'')]
    assert send(2, MUX.SABM | MUX.PF) == [(2, 1, MUX.DM | MUX.PF, b'')]                  # audio: reserved
    assert send(9, MUX.SABM | MUX.PF) == [(9, 1, MUX.DM | MUX.PF, b'')]
    assert send(1, MUX.UIH, b'AT\r') == [(1, 1, MUX.DM, b'')]                            # DLC 1 not open yet
    assert send(1, MUX.SABM | MUX.PF) == [(1, 1, MUX.UA | MUX.PF, b'')]
    assert send(1, MUX.UIH, b'AT+CSQ;+CMUX=0\r') == [(1, 0, MUX.UIH, b'\r\n+CSQ: 99,99\r\n\r\nERROR\r\n')]
    # answers longer than N1 = 31 come in several frames
    got = send(1, MUX.UIH, b'AT+CIND=?\r')
    assert all(len(i) <= 31 for _, _, _, i in got) and b''.join(i for *_, i in got) == ok('+CIND: ("signal",(0-5)),("service",(0,1)),("roam",(0,1))').encode()
    # control channel: PN, MSC, Test, an unsupported message, FCoff / FCon
    pn = bytes([1, 0, 0, 10, 0x00, 0x01, 3, 2])                                           # N1 256
    assert send(0, MUX.UIH, MUX.message(MUX.PN, pn)) == [(0, 0, MUX.UIH, MUX.message(MUX.PN, pn, command=False))]
    assert send(0, MUX.UIH, MUX.message(MUX.PN, bytes([1, 0, 0, 10, 0xff, 0xff, 3, 2]))) == [
        (0, 0, MUX.UIH, MUX.message(MUX.PN, bytes([1, 0, 0, 10, 0x00, 0x04, 3, 2]), command=False))]      # capped at 1024
    assert send(0, MUX.UIH, MUX.message(MUX.TEST, b'ping')) == [(0, 0, MUX.UIH, MUX.message(MUX.TEST, b'ping', command=False))]
    assert send(0, MUX.UIH, MUX.message(MUX.RPN, b'\x07')) == [(0, 0, MUX.UIH, MUX.message(MUX.NSC, bytes([MUX.RPN]), command=False))]
    assert send(0, MUX.UIH, MUX.message(MUX.MSC, b'\x07\x8f')) == [(0, 0, MUX.UIH, MUX.message(MUX.MSC, b'\x07\x8f', command=False))]
    b.m.cell.set_service(True)
    assert frames() == []                                                                 # DLC 1 flow-controlled by MSC FC = 1
    b.send(MUX.frame(1, MUX.UIH, b'AT+CREG=1\r', 1), 0)
    assert frames() == [] and b.m.at_pending == ok().encode()
    assert send(0, MUX.UIH, MUX.message(MUX.MSC, b'\x07\x8d')) == [
        (0, 0, MUX.UIH, MUX.message(MUX.MSC, b'\x07\x8d', command=False)), (1, 0, MUX.UIH, ok().encode())]
    assert send(0, MUX.UIH, MUX.message(MUX.FCOFF)) == [(0, 0, MUX.UIH, MUX.message(MUX.FCOFF, command=False))]
    b.m.cell.set_service(False)
    assert frames() == []
    assert send(0, MUX.UIH, MUX.message(MUX.FCON)) == [(0, 0, MUX.UIH, MUX.message(MUX.FCON, command=False)), (1, 0, MUX.UIH, b'\r\n+CREG: 2\r\n')]
    # a damaged frame is dropped and said in the log; the next one is taken
    bad = bytearray(MUX.frame(1, MUX.UIH, b'AT\r', 1)); bad[-2] ^= 1
    b.send(bytes(bad), 0)
    assert send(1, MUX.UIH, b'AT\r') == [(1, 0, MUX.UIH, ok().encode())] and any('CMUX frame dropped' in l for l in b.log)
    # DISC of DLC 1; CLD back to raw AT
    assert send(1, MUX.DISC | MUX.PF) == [(1, 1, MUX.UA | MUX.PF, b'')] and not b.m.at_open()
    assert send(1, MUX.DISC | MUX.PF) == [(1, 1, MUX.DM | MUX.PF, b'')]
    assert send(0, MUX.UIH, MUX.message(MUX.CLD)) == [(0, 0, MUX.UIH, MUX.message(MUX.CLD, command=False))]
    assert b.m.mode == 'raw' and b.at('AT') == ok()
    # a firmware that starts with SABM and no AT+CMUX; DISC on DLC 0 closes
    c = Bench()
    p = MUX.Parser()
    c.send(MUX.frame(0, MUX.SABM | MUX.PF, cr=1) + MUX.frame(1, MUX.SABM | MUX.PF, cr=1) + MUX.frame(1, MUX.UIH, b'ATE0;+CSQ\r', 1))
    got = [(f.dlci, f.control, f.info) for f in p.feed(c.take())]
    assert got == [(0, MUX.UA | MUX.PF, b''), (1, MUX.UA | MUX.PF, b''), (1, MUX.UIH, b'ATE0;+CSQ\r' + ok('+CSQ: 31,99').encode())], got
    c.send(MUX.frame(0, MUX.DISC | MUX.PF, cr=1))
    assert [(f.dlci, f.control) for f in p.feed(c.take())] == [(0, MUX.UA | MUX.PF)] and c.m.mode == 'raw'
    return 'AT+CMUX=0, SABM / UA / DM, DLC 2 reserved, N1 split, PN (capped), Test, NSC, MSC and FCoff / FCon hold DLC 1, bad FCS, DISC, CLD, SABM without AT+CMUX'


def test_dma_registers():
    """The firmware side with the DMA controller model: transmit by DMA from memory to the link port, receive by DMA into memory."""
    b = Bench()
    mem = bytearray(0x1000)
    BASE = 0x4b000000
    rd = lambda a, n: bytes(mem[a - BASE:a - BASE + n])
    def wr(a, data): mem[a - BASE:a - BASE + len(data)] = data
    tc = {}
    dm = Dmac(rd, wr, lambda n, l: tc.__setitem__(n, l), 2, 'dmaA')
    b.link.a.connect_dma(dm, 0xC0022000)
    b.link.a.write(0x000, 4, 3); b.link.a.write(0x200, 4, 3)          # TX0 / RX0: enable + DMA requests
    wr(BASE + 0x100, b'AT+CSQ\r')
    def start(ch, ctrl, src, dst, typ):
        dm.write(0x400 + 16 * ch, 4, ctrl); dm.write(0x404 + 16 * ch, 4, src); dm.write(0x408 + 16 * ch, 4, dst)
        dm.write(0x40c + 16 * ch, 4, 0); dm.write(0x100 + 4 * ch, 4, typ << 1 | 1)
    answer = b'AT+CSQ\r' + ok('+CSQ: 31,99').encode()
    start(9, len(answer), 0xC0022220, BASE + 0x200, 2)                 # receive: port to memory
    start(2, 7, BASE + 0x100, 0xC0022020, 1)                           # transmit: memory to port
    assert dm.read(0x008, 4) & 4                                       # channel 2 done: the bytes are in the link
    b.t += MS; b.m.tick()
    assert dm.read(0x008, 4) & (1 << 9) and bytes(mem[0x200:0x200 + len(answer)]) == answer and tc.get(2)
    return 'AT+CSQ out by DMA channel 2, echo and answer in by DMA channel 9'


def test_wake_from_outside_a_run():
    """A network event handed in between two runs, while the CPU sleeps with nothing due: the next step of the interrupt
    system runs the stand-in, the bytes reach the firmware's receive channel and the link's receive line (5) wakes the CPU."""
    from emu_irq.system import IrqTimerSystem
    from emu_modem_at import attach_peer

    class M:                                    # the parts of a Machine that IrqTimerSystem and the stand-in use
        insns, irq_pending, touched = 0, False, False
        def log(self, *a): pass
        def attach(self, *a): pass
    m = M()
    irq = IrqTimerSystem(m, log=lambda *a: None)
    link = AaifLink(set_line_a=irq.vic.set_line)
    irq.vic.vic0.write(0x10, 4, 1 << 5)         # VIC0 enable: line 5 (link receive)
    CONFIG.use({'sim.present': True, 'cell.network': 'host'})
    try:
        log = []
        modem = attach_peer(link.b, irq, log.append)
    finally:
        CONFIG.use(None)
    fw = Fw(link)
    for ch in b'ATE0;+CREG=1\r':
        fw.a.write(0x020, 1, ch)
    m.touched = True; irq.step()                # the slice in which the firmware wrote: the stand-in answers
    assert fw.get() == b'ATE0;+CREG=1\r' + ok().encode()
    m.touched = False; irq.step()
    assert irq.step_due == float('inf') and irq.next_event_ns() is None and not irq.vic.irq_out    # asleep, nothing scheduled
    t0 = irq.clock.now_ns
    modem.cell.set_service(True)                # from outside a run (a page between two runs)
    assert irq.next_event_ns() == t0 and irq.step_due <= t0 and m.touched
    assert irq.idle() and irq.clock.now_ns == t0                       # the CPU's wait ends at once, not at a later time
    m.touched = False; irq.step()
    assert irq.vic.irq_out and m.irq_pending and fw.get() == b'\r\n+CREG: 1\r\n'
    return 'set_service between runs: next event = now, the step runs the stand-in, +CREG URC in RX0, line 5 raised at the same time'


def test_config():
    CONFIG.use({'sim.present': True, 'phone.number': '+4930123', 'cell.network': 'host'})
    try:
        cfg, notes = CONFIG.load({})
        assert cfg['phone.number'] == '+4930123' and cfg['cell.network'] == 'host' and notes == []
        CONFIG.use({'phone.number': 'abc'})
        cfg, notes = CONFIG.load({'MOCK_CELL': 'loopback'})
        assert cfg['phone.number'] == '' and cfg['cell.network'] == 'loopback' and any('phone.number' in n for n in notes)
        CONFIG.use(None)
        cfg, notes = CONFIG.load({'MOCK_NUMBER': '1234'})
        assert cfg['phone.number'] == '1234' and cfg['sim.present'] is False
        CONFIG.use({'sim.lock': 'off', 'phone.lock': 'off', 'net.bridge': 'host', 'sim.imsi': '12', 'bogus': 1})
        cfg, notes = CONFIG.load({})
        assert notes == ["unknown key 'bogus' ignored", 'sim.imsi must be 15 digits: default kept'], notes
        # one file serves both stand-ins: the stock stand-in's keys are known here by name only (no import of it at run time).
        # Checked against it where it is there (not in Myna's release)
        try:
            from emu_modem_mock import config as stock, sim, cell as stock_cell
        except ImportError:
            return 'phone.number, MOCK_NUMBER, unknown keys (no stock stand-in here to compare the shared keys with)'
        assert stock.GIVEN is None                                      # the stock stand-in's own setting is left alone
        mine = set(CONFIG.DEFAULTS) - {'phone.number'}
        assert set(CONFIG.OTHER_KEYS) == set(stock.DEFAULTS) - mine and mine <= set(stock.DEFAULTS), set(stock.DEFAULTS) ^ set(CONFIG.OTHER_KEYS)
        assert all(CONFIG.DEFAULTS[k] == stock.DEFAULTS[k] for k in mine) and CONFIG.CELL_NETWORK == stock.CELL_NETWORK
        assert CELL.SERVICE_CENTRE == sim.MockSim().service_centre and stock_cell.Host is CELL.Host and stock_cell.EPOCH == CELL.EPOCH
    finally:
        CONFIG.use(None)
    return 'shared keys of the stock file (by name; same defaults), phone.number, MOCK_NUMBER, unknown keys'


TESTS = [test_fcs_and_frames, test_quiet_until_spoken_to, test_at_basics, test_sms_loopback, test_sms_host, test_cmux,
         test_dma_registers, test_wake_from_outside_a_run, test_config]


def test_launcher(core='unicorn'):
    """Myna with this stand-in through the launcher, a run held at its end as a page runs it: after the network gains service
    between two runs, the stand-in's answer is in the link at the start of the next run (registers poked from outside, as a
    firmware that uses the link would do)."""
    sys.path.insert(0, os.path.join(NATIVE, 'sim'))
    import db3210, devices
    prof = devices.select('myna')
    if not os.path.isfile(prof.BOOT_ELF):
        return 'SKIPPED: %s not built' % prof.BOOT_ELF
    out = []
    phone = db3210.build('myna', peer_config={'sim.present': True, 'cell.network': 'host'}, options=['--standard', '--core', core], out=out.append)
    peer = [v for v in phone.attached.values() if hasattr(getattr(v, 'cell', None), 'take')]
    assert len(peer) == 1, phone.attached
    at = peer[0]
    db3210.run(phone, 300 * MS, hold=True)
    a = at.side.peer
    for off, v in ((0x000, 1), (0x200, 1)):
        a.write(off, 4, v)
    for ch in b'ATE0;+CREG=1\r':
        a.write(0x020, 1, ch)
    t0 = at.now_ns()
    db3210.run(phone, 50 * MS, hold=True)
    got = bytearray()
    while a.read(0x208, 4): got.append(a.read(0x220, 1))
    assert bytes(got) == b'ATE0;+CREG=1\r' + ok().encode(), got
    at.cell.set_service(True)
    t1 = at.now_ns()
    db3210.run(phone, 50 * MS, hold=True)
    while a.read(0x208, 4): got.append(a.read(0x220, 1))
    urc = [l for l in out if 'URC +CREG: 1' in l]
    assert bytes(got).endswith(b'\r\n+CREG: 1\r\n') and urc, (got, out[-5:])
    when = float(urc[0].split(' ms|')[0].split()[-1]) * MS
    assert abs(when - t1) < 1 * MS, (when, t1)
    return '%s: Myna + emu_modem_at: AT answered; +CREG URC %.3f ms after set_service' % (core, abs(when - t1) / MS)


def test_launcher_own():
    """The same on the compiled core (native/core/build, or DBCORE_OUT)."""
    try:
        sys.path.insert(0, os.path.join(NATIVE, 'core', 'python'))
        import dbcore
        dbcore.find_library()
    except (ImportError, OSError) as e:
        return 'SKIPPED: no compiled core (%s)' % e
    return test_launcher('own')


def main():
    tests = TESTS + ([test_launcher, test_launcher_own] if '--launcher' in sys.argv else [])
    for t in tests:
        r = t()
        print('%-34s ok  %s' % (t.__name__, r or ''))
    print('selftest: all passed')


if __name__ == '__main__':
    main()
