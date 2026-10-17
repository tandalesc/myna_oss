"""The cell network behind a modem stand-in: the seam for text messages (and nothing else yet).

A stand-in owns one CellNetwork (AtModem.cell of emu_modem_at, ModemMock.cell of emu_modem_mock; None when the configuration
key cell.network is "off"), attached to a port of its own: an object with the methods of CellPort below. The stand-in's
message code talks to the network and knows nothing of what is behind it:

    phone -> network    network.submit(service_centre, tpdu, done)
                        service_centre   the address the phone gave: type of number, then the digits, two to a byte, swapped
                        tpdu             the SMS-SUBMIT of 3GPP TS 23.040 as the phone built it
                        done(ok, cause=0, report=b'')   the network's answer, called LATER (never from inside submit):
                                         ok = accepted; cause = the RP cause of a refusal (3GPP TS 24.011 table 8.4), report =
                                         the SMS-SUBMIT-REPORT, when the network sends one
    network -> phone    port.deliver(service_centre, tpdu, report=None)      port: the CellPort given to attach()
                        tpdu             an SMS-DELIVER; report(accepted, cause) is called when the phone has acknowledged or
                                         refused it (cause 22 = its store is full). The return value is False when the phone
                                         cannot be reached at all (radio off)
                        network.memory_available(done)   the phone has room again after a refusal with cause 22

A network registers the phone: with any network here the stand-in reports the phone registered on its card's home network
for calls and messages. That holds while the network has service (CellNetwork.service, set_service): without it the phone is
a phone with the radio on and no network. "loopback" always has service; "host" has it when the program says so.

This module imports nothing of the simulator (standard library only). It was emu_modem_mock/cell.py; that name re-exports it.

Time is the emulated time of the phone and nothing else: port.now_ns(), port.later(delay_ns, function). A function given to
later() runs from the stand-in's tick. No network of this module opens a socket, starts a thread or reads the host's clock.

Networks:  "loopback"  [MOCK] every submitted message is accepted and comes back to the same phone as an SMS-DELIVER from the
                       number it was sent to.
           "host"      the program around the simulator carries the messages (a page with a connection to a relay, a
                       test with two phones): it takes what the phone sends with take(), answers each with result() and
                       hands in what arrives with incoming(). This module does not know how they travel. When the program
                       acts is its own matter, so a run with this network repeats only if the program repeats.
"""
import time

EPOCH = 1224504000              # [MOCK] the network's clock at power-on: 2008-10-20 12:00:00 UTC, the default start of the
                                # simulator's real-time clock. The time stamp of a message is this plus the emulated time
CAUSE_MEMORY_EXCEEDED = 22      # RP cause "memory capacity exceeded"
CAUSE_SEMANTICALLY_INCORRECT = 95
SERVICE_CENTRE = '5550100'      # [MOCK] the network's service centre: a made-up number ('+' in front = international). The
                                # test card of the stock stand-in (emu_modem_mock/sim.py, MockSim.service_centre) holds the same


class CellNetwork:
    """What a network gives the stand-in. attach() is called once, at link-up."""
    name = None
    label = ''                  # put in front of the log note of everything that comes from this network: '[MOCK: ...] ' for an invented one
    service = True              # the phone can reach this network: it is registered, and messages pass (set_service)

    def attach(self, port):
        self.port = port

    def set_service(self, up):
        """The network can or cannot be reached from now on. Takes effect at the stand-in's next tick; saying the same again
        changes nothing. Without service the phone is what a phone with the radio on and no network is: not registered,
        signal level 0 (the call service sends the modem's events for the change, services/call.py service_changed), a
        message it sends gets the modem's answer "no connection" and a message for it cannot be delivered."""
        def go():
            if self.service != bool(up):
                self.service = bool(up)
                self.port.say('network "%s": %s' % (self.name, 'in service' if up else 'no service'))
                self.port.service_changed()
        self.port.later(0, go)

    def submit(self, service_centre, tpdu, done):
        raise NotImplementedError

    def memory_available(self, done):
        """The phone can take messages again. done(ok, cause) as for submit."""
        self.port.later(0, lambda: done(True, 0))


class CellPort:
    """The phone as a network sees it: the interface a stand-in gives to attach(). Each stand-in has its own
    (the class CellPort of emu_modem_at/modem.py and of emu_modem_mock/cell.py)."""

    def now_ns(self):
        """The phone's emulated time in ns."""
        raise NotImplementedError

    def later(self, delay_ns, fn):
        """Call fn() from the stand-in's tick, delay_ns of emulated time from now."""
        raise NotImplementedError

    def say(self, text):
        """A line for the run's log."""
        raise NotImplementedError

    def service_changed(self):
        """CellNetwork.service has changed: the stand-in tells the phone."""
        raise NotImplementedError

    def deliver(self, service_centre, tpdu, report=None):
        """An SMS-DELIVER for the phone (see the top of this file). False: the phone cannot be reached."""
        raise NotImplementedError


class Loopback(CellNetwork):
    """[MOCK] A network of one phone. A message is accepted ACCEPT_NS after the phone submitted it and delivered back to the
    phone DELIVER_NS after that; both delays are invented. A message the phone refuses for lack of room is kept and delivered
    again when the phone reports room; any other refusal drops it."""
    name = 'loopback'
    label = '[MOCK: loopback network] '
    ACCEPT_NS = 1_500_000_000
    DELIVER_NS = 3_000_000_000

    def attach(self, port):
        self.port = port
        self.held = []              # (service centre, SMS-DELIVER) refused with "memory capacity exceeded"

    def submit(self, service_centre, tpdu, done):
        try:
            deliver = submit_to_deliver(tpdu, EPOCH + self.port.now_ns() // 1_000_000_000)
        except ValueError as e:
            self.port.say('loopback: SMS-SUBMIT not understood (%s): refused, cause %d' % (e, CAUSE_SEMANTICALLY_INCORRECT))
            return self.port.later(self.ACCEPT_NS, lambda: done(False, CAUSE_SEMANTICALLY_INCORRECT))
        def accepted():
            done(True, 0)
            self.port.later(self.DELIVER_NS, lambda: self._deliver(service_centre, deliver))
        self.port.later(self.ACCEPT_NS, accepted)

    def _deliver(self, service_centre, deliver):
        def report(accepted, cause):
            if not accepted and cause == CAUSE_MEMORY_EXCEEDED:
                self.held.append((service_centre, deliver))
        if not self.port.deliver(service_centre, deliver, report):
            self.port.say('loopback: the phone cannot be reached, message dropped')

    def memory_available(self, done):
        held, self.held = self.held, []
        def go():
            done(True, 0)
            for service_centre, deliver in held:
                self.port.later(self.DELIVER_NS, lambda sc=service_centre, d=deliver: self._deliver(sc, d))
        self.port.later(self.ACCEPT_NS, go)


class Host(CellNetwork):
    """The network of the program around the simulator. Nothing is invented here: the program is the network.
        take()                       -> [(number, service centre, SMS-SUBMIT)] the phone has sent since the last call
        result(number, ok, cause=0)  the network's answer for one of them (cause: the RP cause of a refusal). The phone
                                     waits for it without a limit of its own: the program must answer every one
        incoming(service_centre, tpdu, report=None)   an SMS-DELIVER for the phone; report(accepted, cause) as for
                                     CellPort.deliver, and report(False, 0) when the phone cannot be reached
        set_service(up)              the program can (True) or cannot (False) reach its network: a page says True while
                                     its connection to the relay stands. The phone shows the operator name and the signal
                                     bars only then. At power-on there is NO service until the program says so. Without
                                     service a message of the phone is answered "no connection" and does not come out of
                                     take(), and incoming() reports report(False, 0)
    result(), incoming() and set_service() take effect at the stand-in's next tick. Called between two runs of the launcher,
    that is the first slice of the next run, asleep or not (db3210.run marks the machine touched, which ends the stand-in's
    rest); called from another thread during a run, the caller must set the machine's `touched` itself. A message the
    phone sent while there was service still waits for its result() when the service goes."""
    name = 'host'
    service = False

    def attach(self, port):
        self.port = port
        self.outbox, self.waiting, self.count = [], {}, 0

    def submit(self, service_centre, tpdu, done):
        self.count += 1
        self.waiting[self.count] = done
        self.outbox.append((self.count, bytes(service_centre), bytes(tpdu)))

    def take(self):
        out, self.outbox = self.outbox, []
        return out

    def result(self, number, ok, cause=0):
        done = self.waiting.pop(number, None)
        if done is not None:
            self.port.later(0, lambda: done(bool(ok), int(cause)))

    def incoming(self, service_centre, tpdu, report=None):
        def go():
            if not self.port.deliver(bytes(service_centre), bytes(tpdu), report) and report is not None:
                report(False, 0)
        self.port.later(0, go)


NETWORKS = {'loopback': Loopback, 'host': Host}


def create(name, port):
    """The network of the configuration value `name`, attached to `port` (a CellPort); None for "off"."""
    cls = NETWORKS.get(name)
    if cls is None:
        return None
    net = cls()
    net.attach(port)
    return net


# ---- 3GPP TS 23.040 transfer protocol units, as far as a network of this module needs them ----
def time_stamp(seconds):
    """TP-Service-Centre-Time-Stamp of a time in seconds since 1970 (UTC, time zone 0): seven octets of swapped decimal digits."""
    t = time.gmtime(seconds)
    return bytes((v % 10) << 4 | v // 10 for v in (t.tm_year % 100, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, 0))


def submit_to_deliver(tpdu, seconds, origin=None):
    """The SMS-DELIVER that the receiver of the SMS-SUBMIT `tpdu` gets. `origin` is the sender's address field (number of
    digits, type of number, swapped digits); None: the destination becomes the originating address, as when the receiver is
    the number it was sent to. Protocol identifier, coding scheme, user data and the header flags (reply
    path, user data header) are kept; the validity period goes and the time stamp of `seconds` comes; "no more messages".
    ValueError when `tpdu` is not a complete SMS-SUBMIT."""
    t = bytes(tpdu)
    if len(t) < 7 or t[0] & 3 != 1:
        raise ValueError('not an SMS-SUBMIT')
    at = 2
    address = t[at:at + 2 + (t[at] + 1) // 2]              # number of digits, type of number, digits
    at += len(address)
    validity = {0: 0, 2: 1, 1: 7, 3: 7}[(t[0] >> 3) & 3]   # TP-VPF: none, relative, enhanced, absolute
    if len(t) < at + 2 + validity + 1:
        raise ValueError('SMS-SUBMIT cut short')
    pid_dcs = t[at:at + 2]
    rest = t[at + 2 + validity:]                           # user data length, user data
    return bytes([(t[0] & 0xc0) | 0x04]) + (address if origin is None else bytes(origin)) + pid_dcs + time_stamp(seconds) + rest


def address_field(number):
    """The address field of a number given as text ('+' in front: international): number of digits, type, swapped digits."""
    d = number.lstrip('+')
    if not d.isdigit() or len(d) > 20:
        raise ValueError('not a number: %r' % number)
    padded = d + 'f' * (len(d) % 2)
    return bytes([len(d), 0x91 if number.startswith('+') else 0x81]) + bytes(int(padded[i + 1] + padded[i], 16) for i in range(0, len(padded), 2))


def digits(address):
    """The digits of an address field for a log line: `address` = type of number + swapped digits."""
    out = ''.join('%x%x' % (b & 15, b >> 4) for b in address[1:]).rstrip('f')
    return ('+' if address[:1] and address[0] & 0x70 == 0x10 else '') + out
