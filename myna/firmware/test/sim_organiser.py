#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Myna's Clock (alarm, timer, stopwatch) through the simulator, driven by keys on Myna's own screens.

    make -C myna/firmware
    native/.venv/bin/python -I myna/firmware/test/sim_organiser.py [--core own] [--verbose] [--frames DIR]

Steps: the Clock list (menu key 8); the alarm set two minutes ahead with the time field (it turns on, the bell shows in
the status bar); the phone back on standby, asleep; the alarm rings on time (the alert screen over standby), Snooze;
it rings again 9 minutes later over the Clock list, Stop; the timer set to 5 s, started, left: it goes off over the
standby screen and the alert is closed; the stopwatch started, two laps, stopped, reset; the alarm turned off and on
again with Options; a power cycle with the flash state: the alarm, its time and the timer's length come back; the
clock set a minute forward in Settings: the alarm rings at its own minute of the new time. With
--frames every state is saved as a PNG. Uses the stand-in's loopback network (the network plays no part here).
"""
import argparse, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sim_telephony import Run, Check  # noqa: E402


def start(core, verbose, fdir, flash=b''):
    r = Run(core, verbose, flash, frames=fdir, network='loopback')
    r.wait(r'display: first frame', 10000, since=0)
    r.phone.inputs.set_switch('slide', 'open')
    r.run(400)
    return r


def scenario(core, verbose, frames):
    check = Check()
    fdir = os.path.join(frames, 'unicorn' if core != 'own' else 'own') if frames else None
    print('== engine: %s' % ('compiled core' if core == 'own' else 'Unicorn'))
    r = start(core, verbose, fdir)
    m = r.wait(r'clock: alarm (\d\d:\d\d) (on|off), timer (\d+) s', 2000, since=0)
    check(m is not None and m.group(2) == 'off', 'clock task started: alarm off on a new phone (%s)' % (m and m.group(0)))

    # the Clock list
    r.key('select')                      # the menu
    r.key('8')                           # Clock
    r.settle()
    r.save('01-clock-list')
    r.key('1')                           # Alarm
    r.settle()
    r.save('02-alarm-off')
    r.key('soft_left')                   # Options
    r.settle()
    r.save('03-alarm-options')
    r.key('1')                           # Set time
    r.settle()
    r.keys('1', '2', '0', '2')           # 12:02 (the phone starts at 12:00)
    r.settle()
    r.save('04-alarm-field')
    r.set_mark()
    r.key('select')                      # Save: the alarm is on
    check(r.wait(r'clock: alarm 12:02 on', 1000) is not None, 'the alarm set to 12:02 and on')
    r.run(300)
    r.save('05-alarm-set-note')
    r.run(2600)
    r.save('06-alarm-on')

    # standby, asleep until 12:02: the alarm rings on time
    r.key('end')
    r.settle()
    r.save('07-standby-bell')
    r.set_mark()
    m = r.wait(r'clock: alarm rings', 130000)
    check(m is not None, 'the alarm rings on standby (at %.1f s)' % (r.now_ms() / 1000))
    r.run(120)
    r.save('08-alarm-ringing')
    r.run(260)
    r.save('09-alarm-ringing-nudge')
    t_ring = r.now_ms()
    r.set_mark()
    r.key('select')                      # Snooze
    check(r.wait(r'clock: alarm snoozed for 9 min', 500) is not None, 'Snooze')
    r.run(200)
    r.save('10-snoozed-note')

    # it rings again 9 minutes later, here over the Clock list
    r.run(2000)
    r.key('select')
    r.key('8')
    r.settle()
    r.save('11-clock-list-snoozed')
    r.set_mark()
    r.run(530000)
    m = r.wait(r'clock: alarm rings', 20000)
    dt = (r.now_ms() - t_ring) / 1000
    check(m is not None and 535 <= dt <= 545, 'the snoozed alarm rings 9 minutes later (%.1f s)' % dt)
    r.run(200)
    r.save('12-alarm-over-clock-list')
    # nobody answers: after a minute it snoozes by itself, and rings again 9 minutes later
    r.set_mark()
    t_ring = r.now_ms()
    m = r.wait(r'clock: alarm snoozed for 9 min', 62000)
    dt = (r.now_ms() - t_ring) / 1000
    check(m is not None and 59 <= dt <= 61, 'unanswered for a minute: it snoozes by itself (%.1f s)' % dt)
    r.set_mark()
    r.run(530000)
    check(r.wait(r'clock: alarm rings', 20000) is not None, 'and rings again')
    r.run(200)
    r.set_mark()
    r.key('soft_right')                  # Stop
    check(r.wait(r'clock: alarm stopped', 500) is not None, 'Stop')
    r.run(200)
    r.save('13-stopped-note')
    r.run(2000)
    r.save('14-clock-list-after')

    # the timer: 5 s, started, then left; it goes off on standby
    r.key('2')                           # Timer
    r.settle()
    r.save('15-timer-ready')
    r.key('soft_left')                   # Set
    r.keys('0', '0', '0', '5')
    r.set_mark()
    r.key('select')
    check(r.wait(r'clock: timer set to 5 s', 500) is not None, 'timer set to 0:05')
    r.settle()
    r.key('select')                      # Start
    r.run(1600)
    r.save('16-timer-running')
    r.key('select')                      # Pause
    r.run(1500)
    r.save('17-timer-paused')
    r.key('select')                      # Resume
    r.key('end')                         # standby: it runs on
    r.set_mark()
    m = r.wait(r'clock: timer done', 6000)
    check(m is not None, 'the timer goes off over standby')
    r.run(200)
    r.save('18-timer-done')
    r.set_mark()
    r.key('select')                      # OK
    check(r.wait(r'clock: timer alert closed', 500) is not None, 'the timer alert closed with OK')
    r.settle()

    # the stopwatch
    r.key('select')
    r.key('8')
    r.key('3')
    r.settle()
    r.save('19-stopwatch')
    r.set_mark()
    r.key('select')                      # Start
    r.run(1500)
    r.key('soft_left')                   # Lap
    r.run(900)
    r.key('soft_left')                   # Lap
    r.run(450)
    r.save('20-stopwatch-running')
    r.key('select')                      # Stop
    r.settle()
    r.save('21-stopwatch-stopped')
    laps = [int(x) for x in re.findall(r'stopwatch: lap \d+ at (\d+) ms', '\n'.join(r.console()[r.mark:]))]
    stop = r.wait(r'stopwatch: stopped at (\d+) ms', 100)
    check(len(laps) == 2 and 1500 <= laps[0] <= 1700 and 900 <= laps[1] - laps[0] <= 1100 and stop is not None,
          'stopwatch: two laps and a stop (%s, %s)' % (laps, stop and stop.group(1)))
    r.set_mark()
    r.key('soft_left')                   # Reset
    check(r.wait(r'stopwatch: reset', 500) is not None, 'stopwatch reset')
    r.settle()
    r.save('22-stopwatch-reset')
    r.key('soft_right')

    # the alarm off and on with Options and select
    r.key('1')
    r.set_mark()
    r.key('select')                      # Turn off
    check(r.wait(r'clock: alarm 12:02 off', 500) is not None, 'select turns the alarm off')
    r.run(1700)
    r.save('23-alarm-turned-off')
    r.key('soft_left')
    r.key('2')                           # Turn on
    check(r.wait(r'clock: alarm 12:02 on', 500) is not None, 'Options, Turn on')
    r.key('end')

    # night theme: the Clock's screens again
    r.key('select')
    r.key('hash')
    r.key('2')                           # Display
    r.key('1')                           # Theme: Pebble night
    r.key('end')
    r.key('select')
    r.key('8')
    r.settle()
    r.save('30-night-clock-list')
    r.key('1')
    r.run(2800)
    r.save('31-night-alarm')
    r.key('soft_right')
    r.key('3')
    r.key('select')
    r.run(1300)
    r.key('soft_left')
    r.run(700)
    r.save('32-night-stopwatch')
    r.key('select')
    r.key('end')

    # power off and on: the alarm comes back
    r.set_mark()
    r.key('end', 3600)
    r.run(3000)
    flash = r.phone.flash_state()
    r2 = start(core, verbose, fdir, flash)
    m = r2.wait(r'clock: alarm (\d\d:\d\d) (on|off), timer (\d+) s', 2000, since=0)
    check(m is not None and m.groups() == ('12:02', 'on', '5'),
          'power cycle: the alarm (12:02, on) and the timer (5 s) come back (%s)' % (m and m.group(0)))
    r2.save('40-after-power-cycle-standby')

    # the clock moved forward a minute (Settings, Date & time: 12:01): the alarm follows the new time of day
    r2.key('select')
    r2.key('hash')                       # Settings
    r2.key('3')                          # Time & date
    r2.key('1')                          # Time
    r2.keys('1', '2', '0', '1')
    r2.set_mark()
    r2.key('select')
    t_set = r2.now_ms()
    r2.key('end')
    m = r2.wait(r'clock: alarm rings', 130000)
    dt = (r2.now_ms() - t_set) / 1000
    check(m is not None and 50 <= dt <= 62, 'after the clock was set to 12:01 the alarm rings at its 12:02 (%.1f s)' % dt)
    r2.run(200)
    r2.save('41-alarm-after-clock-change')
    return check


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--core', choices=('unicorn', 'own'), default='unicorn')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--frames', help='save the screens as PNG files under DIR/unicorn or DIR/own')
    a = ap.parse_args()
    t = time.time()
    c = scenario(a.core, a.verbose, a.frames)
    print('%d passed, %d failed (%.1f s host time)' % (c.passed, c.failed, time.time() - t))
    sys.exit(1 if c.failed else 0)


if __name__ == '__main__':
    main()
