#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Myna's text input and the phone's own screens through the simulator, driven by keys on Myna's screens, with the
host cell network of sim_telephony.py (the texts typed are read back from the PDUs the phone sends).

    make -C myna/firmware
    native/.venv/bin/python -I myna/firmware/test/sim_ui.py [--core own] [--verbose] [--frames DIR] [--bench]

Steps: predictive text (one press per letter, candidates with *, an apostrophe word, punctuation on 1, the capital
after a sentence's end, a word chosen over the first one learnt and offered first afterwards, a completion taken with
right, a word no list has spelt with Spell and kept in My words, a number key held for its digit, 0 for a space);
the case on * (abc, ABC, Abc) and the input methods on # held (letters, 123, back to predictive text); the
symbols on * held; C held clears the box; the setting
"Predictive text" off and on; Cyrillic text received and shown; the keypad lock (* then Lock; a key says how; Unlock
then *); the profiles (Silent from Settings, # held on standby back to Normal) with their signs; the shortcuts of the
navigation key on standby; the Settings tree and My words (a word forgotten); a power cycle (My words and the
settings kept); a master reset (everything erased). With --frames every state is saved as a PNG; with a BENCH build
and --bench the cost of each key in the text box is collected (instructions to the end of its paint).
"""
import argparse, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sim_telephony import Run, Check, OWN, SC, deliver, decode_submit  # noqa: E402

WORDS = os.path.join(HERE, '..', '..', 'assets', 'words', 'en.txt')
KEY = {c: k for k, s in {'2': 'abc', '3': 'def', '4': 'ghi', '5': 'jkl', '6': 'mno', '7': 'pqrs', '8': 'tuv',
                         '9': 'wxyz'}.items() for c in s}
KEY["'"] = '1'


def seq(word):
    return ''.join(KEY[c] for c in word.lower())


class Words:
    """the candidate order of the built-in list (most frequent first among the words of one key sequence), with
    the words learnt in front (the most recent first), as services/words.c gives them"""
    def __init__(self):
        self.by_seq = {}
        for w in open(WORDS, encoding='utf-8').read().split():
            if all(c.lower() in KEY for c in w):
                self.by_seq.setdefault(seq(w), []).append(w)
        self.mine = []

    def candidates(self, keys):
        out = []
        for w in self.mine + self.by_seq.get(keys, []):
            if seq(w) == keys and w.lower() not in [o.lower() for o in out]:
                out.append(w)
        return out[:12]

    def learn(self, word):
        if word in self.mine:
            self.mine.remove(word)
        self.mine.insert(0, word)


def type_word(r, words, word, learn=True):
    """one press per letter, then * until the word shows (a word chosen over the first one is learnt)"""
    keys = seq(word)
    for k in keys:
        r.key(k, ms=40, after=60)
    cands = words.candidates(keys)
    i = [c.lower() for c in cands].index(word.lower())
    for _ in range(i):
        r.key('star', ms=40, after=60)
    if i and learn:
        words.learn(cands[i])
    return i


def type_text(r, words, text):
    """a sentence in predictive text: words, # for a space, 1 for '.' (then * for the others of key 1)"""
    signs = ['.', ',', '?', '!']
    for tok in re.findall(r"[A-Za-z']+|[ .,?!]", text):
        if tok == ' ':
            r.key('hash', ms=40, after=60)
        elif tok in signs:
            r.key('1', ms=40, after=60)
            for _ in range(signs.index(tok)):
                r.key('star', ms=40, after=60)
        else:
            type_word(r, words, tok)


def sent_text(r):
    """the text of the next SMS-SUBMIT the phone sends (answered as sent)"""
    s = r.take()
    if not s:
        return None
    n, sc, tpdu = s[0]
    r.net.result(n, True)
    return decode_submit(bytes(tpdu))[3]


def open_conversation(r):
    """from standby: Messages, New message, Enter number, the own number: the conversation"""
    r.key('soft_left')
    r.key('select')
    r.key('select')
    for ch in OWN:
        r.key('star' if ch == '+' else ch, ms=40, after=40)
    r.key('select')
    r.settle()


def scenario(core, verbose, frames, bench):
    check = Check()
    measures = {}
    fdir = os.path.join(frames, 'unicorn' if core != 'own' else 'own') if frames else None
    print('== engine: %s' % ('compiled core' if core == 'own' else 'Unicorn'))
    r = Run(core, verbose, frames=fdir)
    words = Words()
    check(r.wait(r'modem: ready in (\d+) ms', 10000) is not None, 'modem ready')
    r.net.set_service(True)
    check(r.wait(r'network: registration 1', 10000) is not None, 'registered')
    r.wait(r'display: first frame', 10000, since=0)
    r.phone.inputs.set_switch('slide', 'open')
    r.run(400)

    # ---- predictive text in a conversation ----
    open_conversation(r)
    r.save('01-box-predictive')
    for k in seq('good'):
        r.key(k, ms=40, after=60)
    r.settle()
    r.save('02-word-good')
    r.key('star')
    r.settle()
    r.save('03-word-next-candidate')
    r.key('star')
    r.settle()
    r.save('04-word-home')
    words.learn('home')
    # the rest: ". I'm at six, ok?" (home is typed above)
    r.key('1', after=60)
    r.key('hash')
    type_text(r, words, "I'm at six")
    r.key('1', after=60)
    r.key('star', after=60)            # ',' (the second sign of key 1)
    r.key('hash')
    type_text(r, words, 'ok')
    r.key('1', after=60)
    r.key('star', after=60)
    r.key('star', after=60)            # '?'
    r.settle(300)
    r.save('05-sentence')
    r.set_mark()
    r.key('select')
    got = sent_text(r)
    check(got == 'Home. I\'m at six, ok?', 'predictive text: one press a letter, * for the next word, 1 and * for '
          'signs, a capital at a sentence\'s start: %r' % got)
    r.settle()
    r.save('06-sent')

    # learnt: 4663 now shows "home" first
    r.set_mark()
    for k in seq('home'):
        r.key(k, ms=40, after=60)
    r.settle()
    r.save('07-learnt-home-first')
    check(r.wait(r'words: "home" learnt', 10, since=0) is not None, 'a word chosen over the first is learnt')
    r.key('hash')

    # a completion, taken with right
    for k in seq('tomorr'):
        r.key(k, ms=40, after=60)
    r.settle()
    r.save('08-completion')
    r.key('right')
    r.key('hash')

    # a word no list has: Spell
    for k in seq('myna'):
        r.key(k, ms=40, after=60)
    r.settle()
    r.save('09-unknown-word-spell')
    r.key('soft_left')                 # Spell
    r.settle()
    r.save('10-spell-screen')
    r.type('myna')
    r.settle()
    r.save('11-spell-typed')
    r.set_mark()
    r.key('select')                    # Save: in the text, and in My words
    check(r.wait(r'words: "myna" learnt', 500) is not None, 'Spell: the word is kept in My words')
    words.learn('myna')
    r.settle()
    r.save('12-spelt-in-box')
    r.key('hash')
    # it is offered now
    for k in seq('myna'):
        r.key(k, ms=40, after=60)
    r.key('hash')
    # a number key held: its digit
    r.key('5', ms=900, after=100)
    r.key('0', ms=900, after=100)
    r.settle()
    r.save('13-held-digits')
    r.set_mark()
    r.key('select')
    got = sent_text(r)
    check(got is not None and got.endswith('myna 50'), 'a spelt word offered next time, digits held: %r' % got)
    check(got is not None and got.startswith('Home tomorrow'), 'a completion taken with right: %r' % got)

    # the case on *, the input methods on # held, with their sign
    for i, name in enumerate(('abc', 'ABC', 'Abc')):
        r.key('star')
        r.settle(200)
        r.save('14-case-%d-%s' % (i, name))
    r.set_mark()
    for i, name in enumerate(('letters', '123', 'predictive')):
        r.key('hash', ms=900, after=200)
        r.settle(200)
        r.save('14-method-%d-%s' % (i, name))
    check(r.wait(r'ui: setting predictive = 0', 10) is not None and r.wait(r'ui: setting predictive = 1', 10)
          is not None, '# held: letters, 123, predictive text again (the setting follows)')
    # multi-tap in Abc (# is the space), then the symbols on * held
    r.key('hash', ms=900, after=200)   # letters, Abc
    r.type('hi ')
    r.key('star', ms=900, after=200)   # the symbols
    r.settle()
    r.save('15-symbols')
    r.keys('down', 'right', 'right', 'right', 'right', 'right')    # @ (row 2, column 6)
    r.settle()
    r.save('16-symbols-at')
    r.key('select')
    r.settle()
    r.save('17-symbol-inserted')
    r.set_mark()
    r.key('select')
    got = sent_text(r)
    check(got == 'Hi @', 'multi-tap and a symbol from the grid: %r' % got)
    # C held clears the box
    r.type('abc')
    r.key('clear', ms=900, after=100)
    r.settle()
    r.save('18-cleared')
    r.key('hash', ms=900, after=200)   # 123
    r.key('hash', ms=900, after=200)   # predictive text again
    r.key('end')

    # ---- Cyrillic received ----
    r.set_mark()
    r.net.incoming(SC, deliver(OWN, 'Привет! Встреча в 18:00, ок?'), lambda a, c: None)
    r.wait(r'ui: new message', 5000)
    r.run(3500)
    r.key('soft_left')
    r.key('select')
    r.settle()
    r.save('19-cyrillic')
    r.key('end')

    # ---- the setting: predictive text off, then on ----
    r.set_mark()
    r.keys('select', 'hash', '4')
    r.settle()
    r.save('20-settings-text-input')
    r.key('1')
    check(r.wait(r'ui: setting predictive = 0', 500) is not None, 'Settings: predictive text off')
    r.key('end')
    open_conversation(r)
    r.save('21-box-abc')
    r.key('end')
    r.keys('select', 'hash', '4', '1', 'end')

    # ---- keypad lock ----
    r.set_mark()
    r.key('star')
    r.settle(200)
    r.save('22-lock-hint')
    r.key('soft_right')                # Lock
    check(r.wait(r'ui: keypad locked', 500) is not None, 'keypad lock: * then Lock')
    r.run(1700)
    r.save('23-locked')
    r.key('5')
    r.settle(200)
    r.save('24-locked-key')
    check(r.wait(r'ui: key 5 down \(home\)', 100) is not None and r.wait(r'dialer', 10) is None,
          'locked: a key opens nothing')
    r.key('soft_right')                # Unlock
    r.settle(200)
    r.save('25-unlock-hint')
    r.key('star')
    check(r.wait(r'ui: keypad unlocked', 500) is not None, 'Unlock then *: unlocked')
    r.run(1700)

    # ---- profiles ----
    r.set_mark()
    r.keys('select', 'hash', '1')
    r.settle()
    r.save('26-settings-sounds')
    r.key('1')                         # Profile
    r.settle()
    r.save('27-profile-choice')
    r.key('2')                         # Silent
    check(r.wait(r'ui: setting profile = 1', 500) is not None, 'profile: Silent')
    r.key('end')
    r.run(1700)
    r.save('28-standby-silent')
    r.set_mark()
    r.key('hash', ms=900, after=200)   # # held: back to Normal
    check(r.wait(r'ui: setting profile = 0', 500) is not None, '# held on standby: the Normal profile again')
    r.run(1700)

    # ---- standby shortcuts ----
    for k, want, name in (('up', 'clock', 'up-clock'), ('down', 'notes', 'down-notes'),
                          ('left', 'recipient', 'left-new-message'), ('right', 'settings', 'right-settings')):
        r.set_mark()
        r.key(k)
        r.key('end')
        check(r.wait(r'ui: key end down \(%s\)' % want, 200) is not None, 'standby %s: %s' % (k, want))

    # ---- Calendar and Notes ----
    r.set_mark()
    r.keys('select', '9')
    r.settle()
    r.save('29a-calendar')
    r.keys('right', 'down')
    r.settle()
    r.save('29b-calendar-moved')
    check(r.wait(r'ui: key down down \(calendar\)', 10) is not None, 'menu 9: the calendar')
    r.key('end')
    r.keys('select', 'star')
    type_text(r, words, 'buy bread')
    r.key('soft_left')
    r.settle()
    r.save('29c-notes-options')
    r.key('1')                         # Add symbol
    r.settle()
    r.key('select')                    # '.'
    r.key('select')                    # Save
    r.run(1700)
    r.save('29d-notes-saved')
    r.key('end')

    # ---- the Settings tree ----
    r.keys('select', 'hash')
    r.settle()
    r.save('30-settings')
    for i, n, name in ((2, 2, 'display'), (3, 3, 'time'), (6, 5, 'status'), (7, 6, 'reset')):    # 5 is Calls
        r.key(str(i))
        r.settle()
        r.save('3%d-settings-%s' % (n, name))
        r.key('soft_right')
    r.key('4')
    r.key('2')                         # My words
    r.settle()
    r.save('37-my-words')
    r.key('select')                    # Forget the first ("myna")
    r.settle()
    r.save('38-forget-question')
    r.set_mark()
    r.key('select')
    r.settle()
    r.save('39-forgotten')
    r.key('end')

    # ---- power cycle: My words and the settings kept ----
    r.set_mark()
    r.keys('select', 'hash', '2', '1', 'end')      # Pebble night
    r.key('end', 3600)
    r.run(3000)
    flash = r.phone.flash_state()
    r2 = Run(core, verbose, flash, frames=fdir)
    check(r2.wait(r'settings: .* theme 0', 10000, since=0) is not None, 'power cycle: Pebble night kept')
    r2.wait(r'display: first frame', 10000, since=0)
    r2.phone.inputs.set_switch('slide', 'open')
    r2.net.set_service(True)
    r2.run(600)
    r2.save('40-night-standby')
    open_conversation(r2)
    r2.set_mark()
    for k in seq('home'):
        r2.key(k, ms=40, after=60)
    check(r2.wait(r'words: 1 of my words read', 500) is not None, 'power cycle: My words read again')
    r2.settle()
    r2.save('41-night-learnt-word')
    r2.key('end')
    # master reset
    r2.keys('select', 'hash', '7', '2')
    r2.settle()
    r2.save('42-master-reset-question')
    r2.set_mark()
    r2.key('select')
    check(r2.wait(r'storage: user: erased \(0\)', 1000) is not None, 'master reset: the file systems erased')
    r2.run(3000)
    flash = r2.phone.flash_state()
    r3 = Run(core, verbose, flash, frames=fdir)
    m = r3.wait(r'settings: (\d) of \d groups read', 10000, since=0)
    check(m is not None and m.group(1) == '0', 'after the master reset: no settings kept (%s)' % (m and m.group(0)))
    check(r3.wait(r'sms store: 0 messages', 5000, since=0) is not None, 'after the master reset: no messages')
    r3.wait(r'display: first frame', 10000, since=0)
    r3.run(600)
    r3.save('43-after-master-reset')
    print('measures:', measures)
    return check


def bench(core, verbose):
    """a BENCH build: the cost of keys in the text box, predictive and multi-tap"""
    r = Run(core, verbose)
    words = Words()
    r.wait(r'modem: ready', 10000)
    r.net.set_service(True)
    r.wait(r'display: first frame', 10000, since=0)
    r.phone.inputs.set_switch('slide', 'open')
    r.run(400)
    open_conversation(r)
    r.set_mark()
    type_text(r, words, 'the quick brown fox jumps over the lazy dog. good morning, how are you today? ')
    lines = r.console()[r.mark:]
    costs = [int(m.group(1)) for l in lines for m in [re.search(r'bench: key on conversation: (\d+)', l)] if m]
    r.key('hash', ms=900, after=200)   # letters
    r.key('star')                      # abc
    r.set_mark()
    r.type('the quick brown fox ')
    lines = r.console()[r.mark:]
    tap = [int(m.group(1)) for l in lines for m in [re.search(r'bench: key on conversation: (\d+)', l)] if m]
    for name, c in (('predictive', costs), ('multi-tap', tap)):
        c = sorted(c)
        if c:
            print('bench %s: %d keys, median %d, 90%% %d, max %d instructions' % (name, len(c), c[len(c) // 2],
                                                                               c[len(c) * 9 // 10], c[-1]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--core', choices=('unicorn', 'own'), default='unicorn')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--frames', help='save the screens as PNG files under DIR/unicorn or DIR/own')
    ap.add_argument('--bench', action='store_true', help='a BENCH build: the cost of keys in the text box')
    a = ap.parse_args()
    t = time.time()
    if a.bench:
        bench(a.core, a.verbose)
        return
    c = scenario(a.core, a.verbose, a.frames, a.bench)
    print('%d passed, %d failed (%.1f s host time)' % (c.passed, c.failed, time.time() - t))
    sys.exit(1 if c.failed else 0)


if __name__ == '__main__':
    main()
