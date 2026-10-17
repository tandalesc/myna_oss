#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Myna's smart dialling and the search in Contacts through the simulator, driven by keys on Myna's screens, with the
host cell network of sim_telephony.py.

    make -C myna/firmware
    native/.venv/bin/python -I myna/firmware/test/sim_dial.py [--core own|unicorn] [--verbose] [--frames DIR]
    make -C myna/firmware clean all BENCH=1 DEFS=-DMYNA_TEST_HOOKS=1
    native/.venv/bin/python -I myna/firmware/test/sim_dial.py --bench [--core own|unicorn]

Steps: eight contacts typed into Contacts (one with an accented name, one with a German number), a text from a number
no contact has, a text to one contact; then in the dialer: names whose keys clash (Anne 2663, Bonn 2666), the
accented name by its first and its second word, a number found by digits in its middle, the conversation with the
unknown number, 0 or 1 for the break between words, the ranking (the name's start before a later word before a
number, the most recently messaged first, then the alphabet); a match chosen with down, Message opening its
conversation (the text goes to its number), the call key and Select on a match (calls are not available), Options and
View contact; the setting "Smart dialling" off (the plain number entry) and on; the search in Contacts (5-6 finds
Joanna Kim and John Ray, 5-6-4 John Ray, C takes a key back, C held and Back clear it, a number by its digits). The
firmware prints each search's hits on the console ("search: "266": 2: Anne Moss, Bonn Hart"), which the checks read.
With --frames every state is saved as a PNG. --bench (a BENCH build with the test hooks) fills the contacts index to
500 made-up contacts and gives the cost of each key in the dialer and in Contacts.
"""
import argparse, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sim_telephony import Run, Check, SC, PAD, deliver, predictive_off, answer_parts, default_core  # noqa: E402

# the letters of the text box's multi-tap with its accented ones (ui/textentry.c)
LETTERS = dict(PAD, **{'2': 'abc2äàåç', '3': 'def3éè', '4': 'ghi4ì', '6': 'mno6öòñ', '7': 'pqrs7ß', '8': 'tuv8üù'})
KEY_OF = {c: (k, i) for k, s in LETTERS.items() for i, c in enumerate(s)}

CONTACTS = [
    ('anne', 'moss', '+15550101'),
    ('bonn', 'hart', '+15550102'),
    ('cara', 'bell', '+15550103'),
    ('dan', 'abbott', '+15550104'),
    ('élodie', 'durand', '+33612345678'),
    ('john', 'ray', '+15550106'),
    ('joanna', 'kim', '+15550107'),
    ('carl', 'diaz', '+4915551234567'),
]
STRANGER = '+15550177'


def type_letters(r, text):
    """lower-case letters with multi-tap (accents too), 'right' between two letters of one key"""
    last = None
    for ch in text:
        k, i = KEY_OF[ch]
        if k == last:
            r.key('right', after=40)
        for _ in range(i + 1):
            r.key(k, ms=40, after=40)
        last = k
    r.key('right', after=60)


def add_contact(r, given, family, number):
    """Contacts, Options, New contact: the first name, the last name, a number; Save"""
    r.key('soft_right')
    r.key('soft_left')                 # Options
    r.key('1')                         # New contact
    r.key('1')                         # First name
    type_letters(r, given)
    r.key('select')
    r.key('2')                         # Last name
    type_letters(r, family)
    r.key('select')
    r.key('3')                         # Add number
    r.dial(number)
    r.key('select')
    r.key('soft_left')                 # Save
    r.settle()
    r.key('end')


def searched(r, query, ms=300):
    """the hits the firmware printed for this query since the mark: (total, [names])"""
    m = r.wait(r'search: "%s": (\d+): (.*)' % re.escape(query), ms)
    if not m:
        return None
    return int(m.group(1)), [n for n in m.group(2).split(', ') if n]


def dial(r, digits):
    for d in digits:
        r.key({'*': 'star', '#': 'hash'}.get(d, d), ms=40, after=60)
    r.settle(200)


def scenario(core, verbose, frames):
    check = Check()
    fdir = os.path.join(frames, 'unicorn' if core != 'own' else 'own') if frames else None
    print('== engine: %s' % ('compiled core' if core == 'own' else 'Unicorn'))
    r = Run(core, verbose, frames=fdir)
    check(r.wait(r'modem: ready in (\d+) ms', 10000) is not None, 'modem ready')
    r.net.set_service(True)
    check(r.wait(r'network: registration 1', 10000) is not None, 'registered')
    r.wait(r'display: first frame', 10000, since=0)
    r.phone.inputs.set_switch('slide', 'open')
    r.run(400)
    predictive_off(r, check)

    # ---- the book, a text from a stranger, a text to Carl (the most recent) ----
    r.set_mark()
    for given, family, number in CONTACTS:
        add_contact(r, given, family, number)
    saved = re.findall(r'ui: contact 0 saved: \d+ \("(.*?)" "(.*?)"', '\n'.join(r.console()[r.mark:]))
    check(saved == [(g[0].upper() + g[1:], f[0].upper() + f[1:]) for g, f, n in CONTACTS],
          'eight contacts typed in, the accented one too: %s' % saved)
    r.set_mark()
    r.net.incoming(SC, deliver(STRANGER, 'Are we still on for Friday?'), lambda a, c: None)
    r.wait(r'ui: new message', 5000)
    r.run(3500)
    dial(r, '5123')                    # Carl, by the digits in the middle of his number
    r.set_mark()
    r.key('down')
    r.key('soft_right')                # Message
    r.type('see you there.')
    r.key('select')
    got = answer_parts(r, 1)
    check(len(got) == 1 and got[0][0] == '+4915551234567', 'a match by its number, Message: the text goes to it (%s)'
          % (got[0][0] if got else None))
    r.settle()
    r.key('end')

    # ---- names whose keys clash ----
    r.set_mark()
    dial(r, '266')
    r.save('01-dial-266')
    check(searched(r, '266') == (2, ['Anne Moss', 'Bonn Hart']), '266: Anne (2663) and Bonn (2666), the alphabet\'s '
          'order: %s' % (searched(r, '266'),))
    dial(r, '3')
    r.save('02-dial-2663')
    check(searched(r, '2663') == (1, ['Anne Moss']), '2663: Anne only: %s' % (searched(r, '2663'),))
    r.key('clear')
    dial(r, '6')
    r.save('03-dial-2666')
    check(searched(r, '2666') == (1, ['Bonn Hart']), '2666: Bonn only: %s' % (searched(r, '2666'),))
    r.key('end')

    # ---- 0 or 1 for the break between words ----
    r.set_mark()
    dial(r, '26631')
    check(searched(r, '26631') == (1, ['Anne Moss']), '2663-1: Anne and the break before Moss: %s'
          % (searched(r, '26631'),))
    dial(r, '66')
    r.save('04-dial-break')
    check(searched(r, '2663166') == (1, ['Anne Moss']), '2663-1-66: Anne Mo..: %s' % (searched(r, '2663166'),))
    r.key('end')

    # ---- accents folded ----
    r.set_mark()
    dial(r, '3563')
    r.save('05-dial-accent')
    check(searched(r, '3563') == (1, ['Élodie Durand']), '3563: Élodie (É on 3): %s' % (searched(r, '3563'),))
    r.key('end')
    r.set_mark()
    dial(r, '38726')
    r.save('06-dial-second-word')
    check(searched(r, '38726') == (1, ['Élodie Durand']), '38726: Durand, a later word: %s'
          % (searched(r, '38726'),))
    r.key('end')

    # ---- a number by digits in its middle; the stranger's conversation ----
    r.set_mark()
    dial(r, '5123')
    r.save('07-dial-number')
    check(searched(r, '5123') == (1, ['Carl Diaz']), '5123: Carl by his number: %s' % (searched(r, '5123'),))
    r.key('end')
    r.set_mark()
    dial(r, '0177')
    r.save('08-dial-conversation')
    check(searched(r, '0177') == (1, [STRANGER]), '0177: the conversation with a number no contact has: %s'
          % (searched(r, '0177'),))
    r.key('end')

    # ---- the ranking ----
    r.set_mark()
    dial(r, '2')
    r.save('09-dial-ranking')
    want = (6, ['Carl Diaz', 'Anne Moss', 'Bonn Hart', 'Cara Bell', 'Dan Abbott', 'Élodie Durand'])
    check(searched(r, '2') == want, '2: the name\'s start (Carl, messaged last, then the alphabet), a later word '
          '(Dan Abbott), a number (Élodie\'s): %s' % (searched(r, '2'),))
    r.key('down')
    r.key('down')
    r.settle(200)
    r.save('10-dial-ranking-chosen')
    r.key('end')

    # ---- a match chosen: Message, the call key, Select, Options, View contact ----
    r.set_mark()
    dial(r, '2663')
    r.key('down')
    r.settle(200)
    r.save('11-dial-chosen')
    r.key('call')
    r.run(200)
    r.save('12-dial-call-key')
    check(r.wait(r'dialer: call key on a match: not available', 10) is not None, 'the call key on a match: calls are '
          'not available yet')
    r.run(3000)
    r.key('select')
    r.run(200)
    r.save('13-dial-select')
    r.run(3000)
    r.key('soft_left')                 # Options
    r.settle()
    r.save('14-dial-options')
    r.key('3')                         # View contact (Send message, Call, View contact)
    r.settle()
    r.save('15-dial-view-contact')
    r.set_mark()
    r.key('down')
    check(r.wait(r'ui: key down down \(contact\)', 100) is not None, 'Options, View contact: the contact')
    r.key('soft_right')                # back to the dialer, the match still chosen
    r.settle()
    r.save('16-dial-back-chosen')
    r.set_mark()
    r.key('soft_right')                # Message
    check(r.wait(r'dialer: message to \+15550101', 200) is not None, 'Message on the chosen match: Anne\'s number')
    r.type('hi anne.')
    r.key('select')
    got = answer_parts(r, 1)
    check(len(got) == 1 and got[0][0] == '+15550101' and got[0][3] == 'Hi anne.',
          'the conversation is Anne\'s: the text goes to +15550101 (%s)' % (got[0][:1] if got else None,))
    r.settle()
    r.key('end')

    # ---- the setting off: the plain number entry; on again ----
    r.set_mark()
    r.keys('select', 'hash')
    r.settle()
    r.save('17-settings')
    r.key('5')                         # Calls
    r.settle()
    r.save('18-settings-calls')
    r.key('1')                         # Smart dialling: off
    check(r.wait(r'ui: setting smart_dial = 0', 500) is not None, 'Settings, Calls: smart dialling off')
    r.key('end')
    r.set_mark()
    dial(r, '266')
    r.save('19-dial-plain')
    check(searched(r, '266', 10) is None, 'smart dialling off: no search, the card under the number')
    r.key('end')
    r.keys('select', 'hash', '5', '1', 'end')
    r.set_mark()
    dial(r, '266')
    check(searched(r, '266') is not None, 'smart dialling on again')
    r.key('end')

    # ---- the search in Contacts ----
    r.key('soft_right')
    r.settle()
    r.save('20-contacts')
    r.set_mark()
    dial(r, '56')
    r.save('21-contacts-56')
    want = (4, ['Joanna Kim', 'John Ray', 'Carl Diaz', 'Élodie Durand'])
    check(searched(r, '56') == want, 'Contacts, 5-6: Joanna Kim and John Ray, then by their numbers (...4567, '
          '...45678) Carl Diaz and Élodie Durand: %s' % (searched(r, '56'),))
    dial(r, '4')
    r.save('22-contacts-564')
    check(searched(r, '564') == (1, ['John Ray']), 'Contacts, 5-6-4: John Ray: %s' % (searched(r, '564'),))
    r.set_mark()
    r.key('clear')
    r.settle(200)
    check(searched(r, '56') == want, 'C: one key back: %s' % (searched(r, '56'),))
    r.key('down')
    r.settle(200)
    r.save('23-contacts-56-chosen')
    r.set_mark()
    r.key('clear', ms=900, after=200)
    r.settle(200)
    r.save('24-contacts-cleared')
    check(r.wait(r'contacts: search cleared', 10) is not None, 'C held: the search cleared')
    r.set_mark()
    dial(r, '5123')
    r.save('25-contacts-number')
    check(searched(r, '5123') == (1, ['Carl Diaz']), 'Contacts, 5123: Carl by his number: %s'
          % (searched(r, '5123'),))
    r.set_mark()
    r.key('soft_right')                # Back: the search cleared
    check(r.wait(r'contacts: search cleared', 100) is not None, 'Back: the search cleared')
    r.key('soft_right')                # Back: out of Contacts
    r.set_mark()
    r.key('down')
    check(r.wait(r'ui: key down down \(home\)', 100) is not None, 'Back again: out of Contacts')
    r.key('end')
    return check


def costs_of(r, pattern):
    """the numbers a pattern's group 1 gives in the console lines since the mark"""
    return [int(m.group(1)) for l in r.console()[r.mark:] for m in [re.search(pattern, l)] if m]


def bench(core, verbose):
    """a BENCH build with the test hooks: 500 contacts in the index, the cost of keys in the dialer and in Contacts"""
    r = Run(core, verbose)
    r.wait(r'modem: ready', 10000)
    r.net.set_service(True)
    r.wait(r'display: first frame', 10000, since=0)
    r.phone.inputs.set_switch('slide', 'open')
    r.run(400)
    r.set_mark()
    dial(r, '*#2668*5#')
    m = r.wait(r'contacts: test: (\d+) in the index \(.*\)', 2000)
    print('bench: %s' % (m.group(0) if m else 'the test hook did not answer (a build with MYNA_TEST_HOOKS?)'))
    r.key('end')
    rows = []
    for screen, keys, what in (('dialer', '5677', 'Joss'), ('dialer', '7672', 'Rosa'),
                               ('dialer', '2782', 'digits of numbers'), ('contacts', '5677', 'Joss')):
        if screen == 'contacts':
            r.set_mark()
            r.key('soft_right')
            r.settle()
            rows.append(('contacts, open', costs_of(r, r'bench: key on contacts: (\d+)'), [], [], []))
        r.set_mark()
        dial(r, keys)
        rows.append(('%s, %s (%s)' % (screen, '-'.join(keys), what),
                     costs_of(r, r'bench: key on %s: (\d+)' % screen), costs_of(r, r'search: "\d+": (\d+)'),
                     costs_of(r, r'bench: search "\d+" in \d+ contacts: (\d+)'),
                     costs_of(r, r'bench: search "\d+" in (\d+) contacts')))
        r.set_mark()
        r.keys('down', 'down')
        rows.append(('%s, down' % screen, costs_of(r, r'bench: key on %s: (\d+)' % screen), [], [], []))
        r.set_mark()
        r.key('clear', ms=900, after=300)
        rows.append(('%s, C then C held' % screen, costs_of(r, r'bench: key on %s: (\d+)' % screen), [], [], []))
        r.key('end')
    # the same keys with smart dialling off: what the dialer costs without the search
    r.keys('select', 'hash', '5', '1', 'end')
    r.set_mark()
    dial(r, '5677')
    rows.append(('dialer, 5-6-7-7, smart dialling off', costs_of(r, r'bench: key on dialer: (\d+)'), [], [], []))
    r.key('end')
    for name, keys, hits, search, looked in rows:
        print('bench %s: a key %s instructions; contacts looked at %s, hits %s, the search alone %s' % (
              name, keys, looked, hits, search))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--core', choices=('unicorn', 'own'), default=None,
                    help='default: own when it is built, else unicorn')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--frames', help='save the screens as PNG files under DIR/unicorn or DIR/own')
    ap.add_argument('--bench', action='store_true', help='a BENCH build with MYNA_TEST_HOOKS: the cost of keys')
    a = ap.parse_args()
    a.core = a.core or default_core()
    t = time.time()
    if a.bench:
        bench(a.core, a.verbose)
        return
    c = scenario(a.core, a.verbose, a.frames)
    print('%d passed, %d failed (%.1f s host time)' % (c.passed, c.failed, time.time() - t))
    sys.exit(1 if c.failed else 0)


if __name__ == '__main__':
    main()
