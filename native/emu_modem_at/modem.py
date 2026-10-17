"""AtModem: the modem end of the link for a firmware that speaks standard protocols. No unicorn import.

Seam: one side of emu_link.AaifLink (in the launcher: link.b), used only through its public interface, like the stock
stand-in (emu_modem_mock/peer.py): register writes and the DMA-port objects of AaifSide.connect_dma(). It registers as that
side's DMA controller; poke() is called whenever bytes can move, and does nothing: the work is done in tick(), after the slice
in which the firmware reached the link.

Transport (myna/spec/14-modem-at.md):
  link channel 0 in both directions, a plain byte stream (message boundaries are not used and are ignored)
  raw mode at power-on: the channel carries AT command lines (at.py)
  AT+CMUX=0 (or a 27.010 frame that starts with the flag F9 where a command line would start) switches the channel to the
  27.010 basic-option multiplexer (cmux.py): DLC 0 control, DLC 1 the AT commands, DLC 2 reserved for the audio service
  (refused with DM for now), other DLCs refused with DM. Closing DLC 0 (DISC or CLD) returns to raw mode.
The stand-in never sends first: nothing goes out until the firmware has sent something, and no byte reaches the firmware
while its receive channel 0 is disabled (the link model holds it back).

The cell network (emu_cell/cell.py) is shared with the stock stand-in: AtModem.cell is the network of the configuration key
cell.network, attached to a port of this stand-in (CellPort below has the interface of cell.CellPort). A program finds it as
the stock one: an object of the run with an attribute `cell` that has take(). Nothing of the stock stand-in is imported.

Time: now_ns() is the application's emulated time. schedule() keeps events; next_event_ns() tells a sleeping CPU when the
stand-in has work. An event added from outside a run (a page hands in a message between two runs) also lowers the
interrupt system's step_due and marks the machine touched, so that the next step() runs tick() at once: the bytes go into the
link, the link raises its receive interrupt (line 5, and line 8 while the firmware has set the link asleep) and the CPU wakes.
"""
import heapq
from emu_cell import cell as CELL
from . import at as AT, cmux as MUX, config as CONFIG

AAIF_BASE = 0xC0022000
CHANNEL = 0
N1_MAX = 1024                       # [MOCK] the largest information field the stand-in accepts in PN / AT+CMUX
DLC_CONTROL, DLC_AT, DLC_AUDIO = 0, 1, 2
SERVICES = {DLC_AT: 'AT commands'}  # DLCs that can be opened; DLC 2 (audio) is reserved and refused until it exists


class CellPort:
    """The phone as a network of cell.py sees it (the interface of cell.CellPort)."""

    def __init__(self, modem):
        self.modem = modem

    def now_ns(self):
        return self.modem.now_ns()

    def later(self, delay_ns, fn):
        self.modem.schedule(delay_ns, fn)

    def say(self, text):
        self.modem.say('CELL  ' + text)

    def service_changed(self):
        self.modem.engine.update_network()

    def deliver(self, service_centre, tpdu, report=None):
        return self.modem.engine.deliver(bytes(service_centre), bytes(tpdu), report)


class AtModem:
    def __init__(self, side, now_ns, log=print, irq=None, cfg=None):
        self.side, self.now_ns, self.log, self.irq = side, now_ns, log, irq
        self.cfg_given = cfg
        self.ports = {}
        self.events, self.seq = [], 0
        self.started = self.link_up = False
        self.mode = 'raw'
        self.wire = bytearray()                 # bytes for the firmware, waiting for room in the link
        self.backlog = bytearray()              # bytes from the firmware for the multiplexer, after AT+CMUX
        self.parser = None
        self.open = set()                       # open DLCs
        self.n1 = {}                            # information field limit of each DLC (PN), default the AT+CMUX value
        self.flow_off, self.dlc_fc = False, set()
        self.at_pending = bytearray()           # AT output for DLC 1, framed at the end of the tick (held while flow control is off)
        self.mux_request = None
        self.number_given = None
        self.cell = None
        self.engine = None
        self.stats = {'rx': 0, 'tx': 0, 'frames_rx': 0, 'frames_tx': 0, 'dropped': 0}
        side.connect_dma(self, AAIF_BASE)

    # ---- the side's DMA-controller interface -------------------------------------------------------------
    def attach_port(self, addr, port):
        self.ports[addr] = port

    def poke(self):
        pass

    # ---- the interrupt system's timer interface ------------------------------------------------------------
    def next_event_ns(self):
        return self.events[0][0] if self.events else None

    def pending_events(self):
        return [(d, 'modem-at event', -1) for d, _, _ in sorted(self.events)[:8]]

    def advance(self):
        pass

    # ---- set-up ----------------------------------------------------------------------------------------------
    def start(self):
        """Enable the stand-in's end of channel 0 (enable + DMA requests: the port interface moves the bytes), read the
        configuration, attach the cell network. Nothing is sent."""
        self.started = True
        self.tx, self.rx = self.ports[AAIF_BASE + 0x20 + 0x40 * CHANNEL], self.ports[AAIF_BASE + 0x220 + 0x40 * CHANNEL]
        self.side.write(0x000 + 0x40 * CHANNEL, 4, 3)
        self.side.write(0x200 + 0x40 * CHANNEL, 4, 3)
        if self.cfg_given is not None:
            self.cfg, notes = self.cfg_given, []
        else:
            self.cfg, notes = CONFIG.load()
        self.say(CONFIG.describe(self.cfg, notes))
        self.engine = AT.AtEngine(self)
        net = CELL.NETWORKS.get(self.cfg['cell.network'])
        if net is not None:
            self.cell = net()
            self.cell.attach(CellPort(self))
        self.engine.shown = self.engine.net_state()

    def set_number(self, number):
        """The phone's own number for +CNUM, as the program knows it (a page: the number of the relay); None: the configuration's."""
        self.number_given = number

    def number(self):
        return self.number_given if self.number_given is not None else self.cfg.get('phone.number', '')

    def say(self, text):
        self.log('[sim] modem-at %.3f ms| %s' % (self.now_ns() / 1e6, text))

    def schedule(self, delay_ns, fn):
        due = self.now_ns() + max(0, int(delay_ns))
        self.seq += 1
        heapq.heappush(self.events, (due, self.seq, fn))
        irq = self.irq
        if irq is not None:                     # the steppers may rest (IrqTimerSystem.step): make them run by then
            if getattr(irq, 'step_due', None) is not None and due < irq.step_due:
                irq.step_due = due
            if getattr(irq.m, 'touched', None) is not None:
                irq.m.touched = True

    # ---- the engine --------------------------------------------------------------------------------------------
    def has_input(self):
        return self.started and bool(self.rx.dma_avail() or self.backlog)

    def tick(self):
        if not self.started:
            return
        while True:
            progress = False
            now = self.now_ns()
            while self.events and self.events[0][0] <= now:
                heapq.heappop(self.events)[2]()
                progress = True
            n = self.rx.dma_avail()
            if n or self.backlog:
                data = bytes(self.backlog) + self.rx.read_bytes(n)
                self.backlog.clear()
                self.stats['rx'] += len(data)
                if not self.link_up:
                    self.link_up = True
                    self.say('link up: first bytes from the firmware on channel %d' % CHANNEL)
                self._input(data)
                progress = True
            while self.side.read(0x204 + 0x40 * CHANNEL, 4) & 0x40:      # message boundaries of the firmware: not used
                self.side.write(0x204 + 0x40 * CHANNEL, 4, 0x40)
            self._flush_at()
            progress |= self._output()
            if not progress:
                break

    def _output(self):
        n = min(len(self.wire), self.tx.dma_space())
        if n <= 0:
            return False
        self.tx.write_bytes(bytes(self.wire[:n]))
        del self.wire[:n]
        self.stats['tx'] += n
        return True

    def _input(self, data):
        if self.mode == 'raw':
            e = self.engine
            if data[:1] == bytes([MUX.FLAG]) and not e.line and not e.busy and e.collect is None:
                self.say('a 27.010 frame where a command line would start: the multiplexer starts with the defaults')
                self.start_mux(e.mux_params, data)
                return
            e.feed(data)
        else:
            parser = self.parser
            for f in parser.feed(data):
                if self.parser is not parser:
                    break                       # the multiplexer was closed: what followed in the same bytes is dropped
                self.stats['frames_rx'] += 1
                self._frame(f)
            if parser.errors != self._errors_seen:
                self._errors_seen = parser.errors
                self.say('CMUX frame dropped (%d so far): %s' % (parser.errors, parser.last_error))

    # ---- what the AT interpreter uses ----------------------------------------------------------------------------
    def raw_mode(self):
        return self.mode == 'raw'

    def at_open(self):
        return self.mode == 'raw' or DLC_AT in self.open

    def at_write(self, data):
        if self.mode == 'raw':
            self.wire += data
        elif DLC_AT in self.open:
            self.at_pending += data
        else:
            self.stats['dropped'] += len(data)

    def start_mux(self, params, rest=b''):
        self.mode = 'mux'
        self.default_n1 = params[3]
        self.parser = MUX.Parser(max_info=N1_MAX)
        self._errors_seen = 0
        self.open, self.n1, self.flow_off, self.dlc_fc = set(), {}, False, set()
        self.at_pending.clear()
        self.backlog += rest
        self.say('CMUX: basic option, N1 %d: waiting for SABM on DLC 0' % self.default_n1)

    def _close_mux(self, why):
        self.say('CMUX closed (%s): back to AT commands on the raw channel' % why)
        self.mode = 'raw'
        self.open.clear()
        self.stats['dropped'] += len(self.at_pending); self.at_pending.clear()
        self.parser = None
        self.engine.reset_channel()

    # ---- 27.010 ------------------------------------------------------------------------------------------------
    def _send(self, dlci, control, info=b'', cr=0):
        """A frame of the stand-in (the responder). Commands and data carry C/R 0, responses C/R 1 (27.010 5.2.1.2)."""
        self.wire += MUX.frame(dlci, control, info, cr)
        self.stats['frames_tx'] += 1

    def _flush_at(self):
        """The AT output of this tick in UIH frames of at most N1 octets, unless flow control holds DLC 1 (FCoff, MSC FC)."""
        if not self.at_pending or self.mode != 'mux' or self.flow_off or DLC_AT in self.dlc_fc:
            return
        n1 = self.n1.get(DLC_AT, self.default_n1)
        data, self.at_pending = bytes(self.at_pending), bytearray()
        for i in range(0, len(data), n1):
            self._send(DLC_AT, MUX.UIH, data[i:i + n1])

    def _frame(self, f):
        d, kind, final = f.dlci, f.kind, MUX.PF if f.pf else 0
        if kind == MUX.SABM:
            if d == DLC_CONTROL or (DLC_CONTROL in self.open and d in SERVICES):
                self.open.add(d)
                self._send(d, MUX.UA | final, cr=1)
                self.say('CMUX DLC %d open%s' % (d, ' (%s)' % SERVICES[d] if d in SERVICES else ''))
            else:
                self._send(d, MUX.DM | final, cr=1)
                self.say('CMUX SABM on DLC %d refused with DM%s' % (d, ' (reserved for the audio service)' if d == DLC_AUDIO else ''))
        elif kind == MUX.DISC:
            if d in self.open:
                self._send(d, MUX.UA | final, cr=1)
                if d == DLC_CONTROL:
                    return self._close_mux('DISC on DLC 0')
                self.open.discard(d)
                self.say('CMUX DLC %d closed' % d)
                if d == DLC_AT:
                    self.engine.reset_channel()
            else:
                self._send(d, MUX.DM | final, cr=1)
        elif kind in (MUX.UIH, MUX.UI):
            if d not in self.open:
                if DLC_CONTROL in self.open:
                    self._send(d, MUX.DM | final, cr=1)
                return
            if d == DLC_CONTROL:
                self._control(f.info)
            elif d == DLC_AT:
                self.engine.feed(f.info)
        # UA and DM: the stand-in sends no command that they could answer

    def _control(self, info):
        try:
            msgs = MUX.parse_messages(info)
        except ValueError as e:
            return self.say('CMUX control message not understood (%s): %s' % (e, info.hex()))
        for t, v in msgs:
            if not t & 2:                       # a response: the stand-in sends no command that it could answer
                continue
            if t == MUX.CLD:
                self._send(DLC_CONTROL, MUX.UIH, MUX.message(MUX.CLD, command=False))
                return self._close_mux('CLD')
            if t == MUX.TEST:
                self._send(DLC_CONTROL, MUX.UIH, MUX.message(MUX.TEST, v, command=False))
            elif t in (MUX.FCON, MUX.FCOFF):
                self.flow_off = t == MUX.FCOFF
                self._send(DLC_CONTROL, MUX.UIH, MUX.message(t, command=False))
            elif t == MUX.MSC and len(v) >= 2:
                d = v[0] >> 2
                if v[1] & 2: self.dlc_fc.add(d)
                else: self.dlc_fc.discard(d)
                self._send(DLC_CONTROL, MUX.UIH, MUX.message(MUX.MSC, v, command=False))
            elif t == MUX.PN and len(v) == 8:
                n1 = max(1, min(N1_MAX, v[4] | v[5] << 8))
                self.n1[v[0] & 0x3F] = n1
                reply = bytes([v[0] & 0x3F, 0, v[2], v[3], n1 & 0xff, n1 >> 8, v[6], v[7]])     # UIH frames, convergence layer 1
                self._send(DLC_CONTROL, MUX.UIH, MUX.message(MUX.PN, reply, command=False))
            else:
                self._send(DLC_CONTROL, MUX.UIH, MUX.message(MUX.NSC, bytes([t]), command=False))
                self.say('CMUX control message %s not supported: answered NSC' % MUX.MSG_NAMES.get(t, '%#04x' % t))

    # ---- report ------------------------------------------------------------------------------------------------
    def summary(self):
        s, e = self.stats, self.engine.stats if self.engine else {}
        return ('modem-at: link %s, channel %d: %d bytes in, %d out; %s%s; command lines %d (errors %d), unsolicited codes %d; '
                'texts sent %d, received %d' % (
                    'up' if self.link_up else 'never used', CHANNEL, s['rx'], s['tx'],
                    'CMUX, DLCs open %s, frames in %d out %d, dropped %d' % (sorted(self.open), s['frames_rx'], s['frames_tx'],
                                                                             self.parser.errors) if self.mode == 'mux' else 'raw AT mode',
                    ', %d bytes lost on a closed AT channel' % s['dropped'] if s['dropped'] else '',
                    e.get('lines', 0), e.get('errors', 0), e.get('urcs', 0), e.get('sent', 0), e.get('received', 0)))
