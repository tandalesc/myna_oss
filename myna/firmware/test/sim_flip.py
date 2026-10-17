#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Myna on the P2 flip (native/devices/myna_flip) through the simulator: the board-ID strap and the lid.

    make -C myna/firmware
    native/.venv/bin/python -I myna/firmware/test/sim_flip.py [--core unicorn|own|both] [--verbose] [--frames DIR]

The flip is the slider's board with the board-ID strap set (GPIO bank 3 pin 0, myna/spec/07-gpio-power.md 1.3); its lid
is the slide switch. Steps: the firmware reads the strap (P2 flip); switched on with the lid closed, the first frame is
black and the panel is kept dark; with the lid closed the keys of the face do nothing and a side key reaches the UI;
opening lights the panel and shows standby; closing in Messages and opening again comes back to Messages; a text
arriving while the lid is closed shows no frame, and after opening the standby shows it (it differs from the standby
before), and Messages has it; switched on with the lid open (as the phone page does), the panel comes on as on the
slider. With --core both the frames of the two engines are compared byte for byte.
"""
import argparse, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sim_telephony as tel  # noqa: E402

FRIEND = tel.FRIEND


class Run(tel.Run):
    def __init__(self, core, verbose, frames=None, lid=None):
        self.history = []                  # every panel update, in order
        super().__init__(core, verbose, frames=frames, device='myna_flip')
        if lid:
            self.phone.inputs.set_switch('slide', lid)      # before the first instruction: the lid as the phone starts

    def on_frame(self, w, h, rgb, number):
        super().on_frame(w, h, rgb, number)
        self.history.append(self.frame[2])

    def black(self):
        return self.frame is not None and not any(self.frame[2])

    def lid(self, state, ms=600):
        self.set_mark()
        self.phone.inputs.set_switch('slide', state)
        self.run(ms)


def scenario(core, verbose, frames, check):
    fdir = os.path.join(frames, 'unicorn' if core != 'own' else 'own') if frames else None
    print('== engine: %s' % ('compiled core' if core == 'own' else 'Unicorn'))
    r = Run(core, verbose, frames=fdir)
    r.net.set_service(True)
    check(r.wait(r'board: id 1, P2 flip', 2000, since=0) is not None, 'the firmware reads the board-ID strap: P2 flip')
    check(r.wait(r'^lid: closed', 2000, since=0) is not None, 'the switch is the lid, closed at power-on')
    check(r.wait(r'display: first frame at [\d.]+ ms, panel kept dark', 10000, since=0) is not None,
          'switched on with the lid closed: the panel is kept dark')
    check(r.wait(r'network: registration 1', 10000) is not None, 'registered')
    r.run(500)
    check(r.black(), 'lid closed: the screen is black')

    # the keys: the face is under the lid, a side key is not
    r.set_mark()
    r.key('5')
    r.key('end')
    r.key('soft_left')
    check(r.wait(r'ui: key', 200) is None, 'lid closed: the keys of the face do nothing (5, END, left soft key)')
    r.key('vol_up')
    check(r.wait(r'ui: key vol_up down', 200) is not None, 'lid closed: a side key reaches the UI (volume up)')
    check(r.black(), 'lid closed: still black after the keys')

    # open: standby
    r.lid('open', 1500)
    check(r.wait(r'ui: lid open: awake \(home\)', 100) is not None and r.wait(r'display: panel on', 100) is not None,
          'lid opened: the panel comes on, standby')
    check(not r.black(), 'lid open: standby is shown')
    r.save('01-open-standby')

    # close in Messages, open again: Messages
    r.key('soft_left')
    r.settle()
    r.save('02-messages')
    shown = r.frame[2]
    r.lid('closed')
    check(r.wait(r'ui: lid closed: asleep \(messages\)', 100) is not None and r.wait(r'display: panel dark', 100) is not None,
          'lid closed in Messages: asleep, the panel dark')
    check(r.black(), 'lid closed: the screen is black')
    r.lid('open')
    check(r.wait(r'ui: lid open: awake \(messages\)', 100) is not None, 'lid opened: back in Messages')
    check(r.frame[2] == shown, 'Messages as they were before the lid closed (the same picture)')
    r.key('end')
    r.settle(2000)                         # standby, the dunes moving
    r.save('03-standby-before')
    before = r.frame[2]

    # a text while the lid is closed
    r.lid('closed')
    n = len(r.history)
    r.set_mark()
    r.net.incoming(tel.SC, tel.deliver(FRIEND, 'Are you on the bus yet?'), lambda a, c: None)
    m = r.wait(r'ui: new message \d+ from \+4915551234567: toast', 5000)
    check(m is not None, 'lid closed: a text arrives (its toast is made)')
    r.run(4000)                            # the toast comes and goes meanwhile
    check(len(r.history) == n, 'lid closed: nothing is drawn while it is closed (%d frames)' % (len(r.history) - n))
    r.lid('open', 1000)
    check(not r.black() and r.frame[2] != before, 'lid opened: the standby shows the new text (it differs from before)')
    r.save('04-standby-new-message')
    r.key('soft_left')
    r.settle()
    r.save('05-messages-unread')
    r.key('select')                        # the newest conversation (the unread one)
    r.settle()
    r.save('06-conversation')
    r.key('end')
    r.settle()

    # the phone page switches the flip on with its lid open
    print('== switched on with the lid open')
    s = Run(core, verbose, frames=os.path.join(fdir, 'lid-open') if fdir else None, lid='open')
    check(s.wait(r'^lid: open', 2000, since=0) is not None, 'lid open at power-on')
    check(s.wait(r'display: first frame at [\d.]+ ms, panel on', 10000, since=0) is not None,
          'switched on with the lid open: the panel comes on after its first frame')
    s.run(1500)
    check(not s.black(), 'switched on with the lid open: standby is shown')
    s.save('01-standby')
    return r, s


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--core', choices=('unicorn', 'own', 'both'), default='both')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--frames', help='save the screens as PNG files under DIR/unicorn or DIR/own')
    a = ap.parse_args()
    t = time.time()
    check = tel.Check()
    cores = ('unicorn', 'own') if a.core == 'both' else (a.core,)
    runs = [scenario(c, a.verbose, a.frames, check) for c in cores]
    if len(runs) == 2:
        for x, y, what in ((runs[0][0], runs[1][0], 'lid closed at power-on'), (runs[0][1], runs[1][1], 'lid open at power-on')):
            same = len(x.history) == len(y.history) and all(p == q for p, q in zip(x.history, y.history))
            check(same, '%s: the two engines show the same %d frames, byte for byte (%d)' % (what, len(x.history), len(y.history)))
    print('%d passed, %d failed (%.1f s host time)' % (check.passed, check.failed, time.time() - t))
    sys.exit(1 if check.failed else 0)


if __name__ == '__main__':
    main()
