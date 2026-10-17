#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The animated standby (src/ui/livewall.c) through the simulator, driven by keys, checked by its frames.

    make -C myna/firmware                      (a build with -DMYNA_TEST_HOOKS=1 adds the Still check, --hooks)
    native/.venv/bin/python -I myna/firmware/test/sim_wallpaper.py [--core unicorn|own|both] [--frames DIR] [--hooks]

Checks: the dunes move at standby (only their rows: the clock, the date and the status bar stay as they are), at about
10 frames a second; they come to rest about 23 s after the last key and then the phone sleeps (no frame, nothing due
before the next minute); a key on standby wakes them; nothing moves behind the menu, and they move again back on
standby; a toast stops them while it is shown; the same in Pebble night; with --hooks (test codes in the dialer) the
Still setting gives the still picture. With --core both the frames of the two engines are compared byte for byte.
"""
import argparse, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sim_telephony as tel  # noqa: E402

W, H = 240, 320
MOVING_TOP = 173               # the first row that moves (mkassets: live dunes, rows 173-294)
MOVING_BOTTOM = 294


class Run(tel.Run):
    def __init__(self, core, verbose, frames=None):
        self.count = 0
        self.history = []          # (emulated ms, frame bytes) of every panel update
        super().__init__(core, verbose, frames=frames)

    def on_frame(self, w, h, rgb, number):
        super().on_frame(w, h, rgb, number)
        self.count += 1
        self.history.append((self.now_ms() if hasattr(self, 'phone') else 0, self.frame[2]))

    def frames_in(self, ms):
        """run ms; the frames shown meanwhile"""
        n = len(self.history)
        self.run(ms)
        return [f for _, f in self.history[n:]]


def rows(frame, y0, y1):
    return frame[y0 * W * 3:y1 * W * 3]


def scenario(core, verbose, frames, hooks, check):
    fdir = os.path.join(frames, 'unicorn' if core != 'own' else 'own') if frames else None
    print('== engine: %s' % ('compiled core' if core == 'own' else 'Unicorn'))
    r = Run(core, verbose, frames=fdir)
    r.net.set_service(True)
    check(r.wait(r'network: registration 1', 10000) is not None, 'registered')
    r.wait(r'display: first frame', 10000, since=0)
    r.phone.inputs.set_switch('slide', 'open')
    r.run(2000)                                     # the toast "Slide open" goes away; the dunes move again

    got = r.frames_in(1000)
    top_same = all(rows(f, 0, MOVING_TOP) == rows(got[0], 0, MOVING_TOP) for f in got)
    moved = len(set(rows(f, MOVING_TOP, MOVING_BOTTOM) for f in got))
    # 10 frames a second; a frame in which no band reaches its next pixel draws nothing
    check(6 <= len(got) <= 10 and moved == len(got), 'standby: the dunes move, up to 10 frames a second (%d frames, '
          '%d different)' % (len(got), moved))
    check(top_same, 'standby: the clock, the date and the status bar are not drawn again')
    r.save('01-day-a')
    r.run(1500)
    r.save('02-day-b')

    r.set_mark()
    m = r.wait(r'livewall: at rest after (\d+) frames', 30000)
    check(m is not None, 'at rest about 23 s after the last key (%s)' % (m.group(0) if m else None))
    rest_at = r.now_ms()
    r.save('03-day-rest')
    r.run(300)
    res = tel.db3210.run(r.phone, 1 * tel.MS, hold=True)     # asleep: when is the next thing due?
    check(res['rest_ns'] / 1e6 > 58000 - r.now_ms(), 'at rest: the phone sleeps until the next minute (next work in '
          '%.1f s, at %.1f s)' % (res['rest_ns'] / 1e9, r.now_ms() / 1000 + res['rest_ns'] / 1e9))
    got = r.frames_in(max(0, 59000 - r.now_ms()))  # until just before the next minute (the clock's update)
    check(not got, 'at rest: no frame until the next minute (%d frames from %.1f s to 59 s)' % (len(got),
                                                                                              rest_at / 1000))

    r.key('clear')                                  # a key on standby (C does nothing else there)
    got = r.frames_in(1000)
    check(len(got) >= 6, 'a key on standby: the dunes move again (%d frames in 1 s)' % len(got))

    r.key('select')                                 # the menu
    r.run(1000)
    got = r.frames_in(2000)
    check(not got, 'behind the menu: nothing moves (%d frames in 2 s)' % len(got))
    r.key('soft_right')                             # back to standby
    got = r.frames_in(1500)
    check(len(got) >= 8, 'back on standby: the dunes move again (%d frames in 1.5 s)' % len(got))

    r.phone.inputs.set_switch('slide', 'closed')    # a toast: "Slide closed"
    r.run(100)
    got = r.frames_in(1000)
    check(len(set(rows(f, MOVING_TOP, MOVING_BOTTOM) for f in got)) <= 1, "a toast: the dunes wait under it (%d frames)" % len(got))
    r.phone.inputs.set_switch('slide', 'open')
    r.run(2000)

    # Pebble night (Settings, 2 Display, 1 Theme)
    r.key('select')
    r.key('hash')
    r.key('2')
    r.key('1')
    r.key('end')
    got = r.frames_in(1500)
    check(len(got) >= 8, 'Pebble night: the dunes move (%d frames in 1.5 s)' % len(got))
    r.save('04-night-a')
    r.run(2000)
    r.save('05-night-b')
    r.set_mark()
    check(r.wait(r'livewall: at rest', 30000) is not None, 'Pebble night: at rest after the idle time')
    r.save('06-night-rest')

    if hooks:
        r.keys('star', 'hash', '9', '2', '5', '5', 'star', '0', 'hash')        # test code: the still picture
        r.key('end')
        got = r.frames_in(1500)
        check(not got, 'Still: nothing moves')
        r.save('07-night-still')
        r.keys('star', 'hash', '9', '2', '5', '5', 'star', '1', 'hash')
        r.key('end')
        got = r.frames_in(1500)
        check(len(got) >= 8, 'Animated again: the dunes move (%d frames)' % len(got))
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--core', choices=('unicorn', 'own', 'both'), default='both')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--frames', help='save frames as PNG files under DIR/unicorn or DIR/own')
    ap.add_argument('--hooks', action='store_true', help='the build has MYNA_TEST_HOOKS: check the Still setting too')
    a = ap.parse_args()
    t = time.time()
    check = tel.Check()
    cores = ('unicorn', 'own') if a.core == 'both' else (a.core,)
    runs = [scenario(c, a.verbose, a.frames, a.hooks, check) for c in cores]
    if len(runs) == 2:
        x, y = runs
        same = len(x.history) == len(y.history) and all(p[1] == q[1] for p, q in zip(x.history, y.history))
        check(same, 'the two engines show the same %d frames, byte for byte' % len(x.history))
    print('%d passed, %d failed (%.1f s host time)' % (check.passed, check.failed, time.time() - t))
    sys.exit(1 if check.failed else 0)


if __name__ == '__main__':
    main()
