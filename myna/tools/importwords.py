#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One-time import of the English word list for predictive text: 12dicts (Alan Beale) -> myna/assets/words/en.txt.

Source: 12dicts 6.0.2, http://wordlist.aspell.net/12dicts/, downloaded as
    http://downloads.sourceforge.net/wordlist/12dicts-6.0.2.zip
    (1,992,138 bytes, SHA-256 64ac1d35acb66b550c7ebc56e080b62e0bad8f5984d72059dc2e05ac48780e52)
Licence: the 12dicts lists are released to the public domain by their author; the lemmatised lists depend on AGID
(Kevin Atkinson), whose notice is a permissive one (use, copy, modify, distribute and sell, with the notice kept): see
myna/assets/words/LICENSE-12dicts.txt. Nothing is share-alike.

Two files of the archive are read (treated as untrusted data: only words of plain letters and an apostrophe pass):
  Lemmatized/2+2+3frq.txt  the lemmas in frequency bands (band 1: "the", "be", "to"; each band about half as frequent
                           as the one before it; from the BYU Corpus of Contemporary American English), regular
                           inflections left out
  Lemmatized/2+2+3lem.txt  the same lemmas with all their inflections, alphabetical
Every word gets a rank in half bands: band x 2 for a headword; a form listed under it in 2+2+3frq one band later when
it looks irregular (went, was, gone), three bands later when it looks derived (goodness, rightly); a regular
inflection found only in 2+2+3lem two bands later (the band counts the whole lemma, so a form is taken as less
frequent than its lemma). Ties: headwords first, then shorter words, then the source's order. Bands after MAX_BAND are
left out (rare words), and so are abbreviations in capitals (but "I"), hyphenated words, words with other signs and a
few archaic forms (SKIP, NOT_FORMS); the first MAX_WORDS words are kept. A few contractions the source does not have (don't,
I'm ...) come from myna/assets/words/extra.txt (the project's own short list, with their bands).

    python3 -I myna/tools/importwords.py DOWNLOAD_DIR myna/assets/words/extra.txt myna/assets/words/en.txt

DOWNLOAD_DIR is the folder the archive was unpacked into. The output is one word per line, the most frequent first.
"""
import os
import re
import sys

MAX_BAND = 17
MAX_WORDS = 32000
INFLECTED = 2                          # a form found only in 2+2+3lem: taken as four times less frequent than its lemma
# words that are kept as headwords but not as forms of another headword (archaic forms: "art" of be, "yer" of your)
NOT_FORMS = set('art yer thee thou thy thine ye'.split())
# forms of the lemmatised lists that nobody types in a text message: archaic verb forms, and plurals or verb forms of
# function words that would otherwise rank with the words themselves
SKIP = set('''wast wert doth dost hast hath didst hadst shalt wouldst couldst shouldst canst art's ya yous doh dohs dos
hes shes hims hers's buts ins ons ifs ands ors offs ups outs thats whats thises tos fors froms bys ats yeses nos
mes yous wot saith haves sayeth cum cums noes wilt olde ohs yeps yups hows twos whys bigs luvs shew
mams yer whos thos'''.split())
# trade names the lists carry that a phone of ours does not offer (the release check refuses them too)
TRADE = {'Walkman'}
WORD = re.compile(r"^[A-Za-z]+(?:'[A-Za-z]+)?$")


def plain(w):
    """the word if it may be in the list, else None"""
    w = w.strip().strip('()').rstrip('*').strip()
    if not WORD.match(w):
        return None
    if w != 'I' and len(w) > 1 and w.isupper():
        return None                    # an abbreviation (TV, DNA)
    if len(w) == 1 and w not in ('a', 'I'):
        return None
    if w in SKIP:
        return None
    return w


def read_frq(path):
    """[(word, band, headword or None, order)] from 2+2+3frq.txt (the headword a form is listed under), and
    {headword: band}"""
    out, heads, band, order, head = [], {}, 0, 0, None
    with open(path, encoding='latin-1') as f:
        for line in f:
            m = re.match(r'^----- (\d+) -----', line)
            if m:
                band = int(m.group(1))
                continue
            if not line.strip():
                continue
            indented = line[0] in ' \t'
            for part in line.split(','):
                w = plain(part)
                order += 1
                if not w:
                    continue
                if not indented:
                    head = w
                    heads.setdefault(w, band)
                    out.append((w, band, None, order))
                elif w not in NOT_FORMS:
                    out.append((w, band, head, order))
    return out, heads


def read_lem(path):
    """{headword: [inflections]} from 2+2+3lem.txt"""
    lem, head = {}, None
    with open(path, encoding='latin-1') as f:
        for line in f:
            if not line.strip():
                continue
            line = re.sub(r'->\s*\[[^\]]*\]', '', line)
            if line[0] in ' \t':
                if head is not None:
                    lem.setdefault(head, []).extend(p.strip() for p in line.split(','))
            else:
                head = line.strip().strip('()').rstrip('*')
    return lem


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    src, extra, out = sys.argv[1:]
    words, heads = read_frq(os.path.join(src, 'Lemmatized', '2+2+3frq.txt'))
    lem = read_lem(os.path.join(src, 'Lemmatized', '2+2+3lem.txt'))
    best = {}                          # word -> (rank, not headword, length, order)

    def add(w, rank, head, order):
        if w in TRADE:
            return
        key = (rank, 0 if head else 1, len(w), order)
        if w not in best or key < best[w]:
            best[w] = key

    order = len(words)
    for w, band, head, o in words:
        if band > MAX_BAND:
            continue
        if head is None:
            add(w, band * 2, True, o)
        elif not w.lower().startswith(head.lower()[:max(1, len(head) - 1)]) or len(w) <= len(head) + 2:
            add(w, band * 2 + 2, False, o)     # an irregular form (went, gone, was): about half as frequent
        else:
            add(w, (band + 3) * 2, False, o)   # a derived word (goodness, rightly): its own frequency is unknown
    for h, band in heads.items():
        if band > MAX_BAND:
            continue
        for p in lem.get(h, []):
            w = plain(p)
            if w:
                order += 1
                add(w, (band + INFLECTED) * 2, False, order)
    with open(extra, encoding='ascii') as f:
        for line in f:
            line = line.split('#')[0].split()
            if len(line) == 2 and plain(line[0]):
                order += 1
                add(line[0], int(line[1]) * 2, True, order)
    # one spelling per word: a lower-case word and the same in capitals (may / May) keep both, as both are typed
    ranked = sorted(best, key=lambda w: best[w])[:MAX_WORDS]
    with open(out, 'w', encoding='ascii', newline='\n') as f:
        for w in ranked:
            f.write(w + '\n')
    print('%d words -> %s' % (len(ranked), out))


if __name__ == '__main__':
    main()
