# SPDX-License-Identifier: MIT
"""The Myna lettering: a monoline geometric alphabet drawn for this project, and the round sign.

Original work of the project (MIT, as the project). No font outlines are used: every glyph is a centre line that the
picture strokes with round ends. Units: baseline 0, capital, figure and ascender height 6, x-height 4, descender 2,
y grows downwards. Each entry: (advance width without the gap, path). The same file is in each skin folder.

The product name is not final. The name on every body and screen comes from NAME below, which the environment variable
BRAND overrides (BRAND=suzu python3 -I draw.py): change it in one place, run the scripts, and every wordmark follows.
Any lowercase name works: the alphabet below has every letter a-z.
"""
import os

NAME = os.environ.get('BRAND', 'myna')

GLYPHS = {
    # figures
    '0': (4, 'M2 -6A2 2 0 0 0 0 -4V-2A2 2 0 0 0 4 -2V-4A2 2 0 0 0 2 -6Z'),
    '1': (3, 'M0.4 -4.6L2.2 -6V0'),
    '2': (4, 'M0.05 -4.1A2 2 0 1 1 3.45 -2.55L0 0H4'),
    '3': (4, 'M0.3 -6H3.7L1.45 -3.92A2 2 0 1 1 0.3 -0.85'),
    '4': (4, 'M2.9 0V-6L0 -1.7H4.2'),
    '5': (4, 'M3.7 -6H0.65L0.45 -3.35C0.9 -3.8 1.45 -4 2 -4A2 2 0 1 1 0.25 -0.95'),
    '6': (4, 'M3.3 -6C1.4 -5.6 0 -4.2 0 -2M0 -2A2 2 0 1 0 4 -2A2 2 0 1 0 0 -2'),
    '7': (4, 'M0 -6H4L1.4 0'),
    '8': (4, 'M2 -6A1.4 1.4 0 1 0 2 -3.2A1.4 1.4 0 1 0 2 -6ZM2 -3.2A1.6 1.6 0 1 0 2 0A1.6 1.6 0 1 0 2 -3.2Z'),
    '9': (4, 'M4 -4A2 2 0 1 0 0 -4A2 2 0 1 0 4 -4C4 -1.8 2.6 -0.4 0.7 0'),
    # capitals
    'A': (4.2, 'M0 0L2.1 -6L4.2 0M0.75 -2.1H3.45'),
    'B': (3.8, 'M0 0V-6H2.1A1.5 1.5 0 0 1 2.1 -3H0M2.1 -3H2.3A1.5 1.5 0 0 1 2.3 0H0'),
    'C': (4, 'M4 -4.6A2 2 0 0 0 0 -4V-2A2 2 0 0 0 4 -1.4'),
    'D': (4, 'M0 0V-6H1.6A2.4 2.4 0 0 1 4 -3.6V-2.4A2.4 2.4 0 0 1 1.6 0Z'),
    'E': (3.6, 'M3.6 -6H0V0H3.6M0 -3H3'),
    'F': (3.6, 'M3.6 -6H0V0M0 -3H3'),
    'G': (4, 'M4 -4.6A2 2 0 0 0 0 -4V-2A2 2 0 0 0 4 -2V-3H2.4'),
    'H': (4, 'M0 -6V0M4 -6V0M0 -3H4'),
    'I': (0, 'M0 -6V0'),
    'J': (3.4, 'M3.4 -6V-1.7A1.7 1.7 0 0 1 0 -1.7'),
    'K': (4, 'M0 -6V0M4 -6L0 -2M1.45 -3.4L4 0'),
    'L': (3.4, 'M0 -6V0H3.4'),
    'M': (5, 'M0 0V-6L2.5 -2L5 -6V0'),
    'N': (4, 'M0 0V-6L4 0V-6'),
    'O': (4.8, 'M2.4 -6A2.4 3 0 1 0 2.4 0A2.4 3 0 1 0 2.4 -6Z'),
    'P': (3.8, 'M0 0V-6H2.2A1.6 1.6 0 0 1 2.2 -2.8H0'),
    'Q': (4.8, 'M2.4 -6A2.4 3 0 1 0 2.4 0A2.4 3 0 1 0 2.4 -6ZM3 -1.3L4.8 0.4'),
    'R': (3.9, 'M0 0V-6H2.2A1.6 1.6 0 0 1 2.2 -2.8H0M2.1 -2.8L3.9 0'),
    'S': (3.8, 'M3.7 -5.1C3.3 -5.7 2.7 -6 1.9 -6C0.9 -6 0.15 -5.4 0.15 -4.5C0.15 -2.7 3.8 -3.3 3.8 -1.4C3.8 -0.5 3 0 1.9 0C1 0 0.4 -0.3 0 -0.9'),
    'T': (4.4, 'M0 -6H4.4M2.2 -6V0'),
    'U': (4, 'M0 -6V-2A2 2 0 0 0 4 -2V-6'),
    'V': (4.2, 'M0 -6L2.1 0L4.2 -6'),
    'W': (5.4, 'M0 -6L1.35 0L2.7 -4.4L4.05 0L5.4 -6'),
    'X': (4, 'M0 -6L4 0M4 -6L0 0'),
    'Y': (4.2, 'M0 -6L2.1 -3L4.2 -6M2.1 -3V0'),
    'Z': (4, 'M0 -6H4L0 0H4'),
    # the small letters (x-height 4, ascender 6, descender 2)
    'a': (4, 'M4 -4V0M4 -2A2 2 0 1 0 0 -2A2 2 0 1 0 4 -2'),
    'b': (4, 'M0 -6V0M0 -2A2 2 0 1 1 4 -2A2 2 0 1 1 0 -2'),
    'c': (3.8, 'M3.8 -3.1A2 2 0 1 0 3.8 -0.9'),
    'd': (4, 'M4 -6V0M4 -2A2 2 0 1 0 0 -2A2 2 0 1 0 4 -2'),
    'e': (4, 'M0.05 -2H4A2 2 0 1 0 3.5 -0.68'),
    'f': (2.8, 'M2.8 -6H2.4A1.4 1.4 0 0 0 1 -4.6V0M0 -4H2.6'),
    'g': (4, 'M4 -2A2 2 0 1 0 0 -2A2 2 0 1 0 4 -2M4 -4V0A2 2 0 0 1 0.4 1.2'),
    'h': (4, 'M0 -6V0M0 -2A2 2 0 0 1 4 -2V0'),
    'i': (0, 'M0 -4V0M0 -5.6V-5.5'),
    'j': (1.2, 'M1.2 -4V0.6A1.4 1.4 0 0 1 -0.5 1.9M1.2 -5.6V-5.5'),
    'k': (3.6, 'M0 -6V0M3.4 -4L0 -1.4M1.25 -2.35L3.6 0'),
    'l': (0, 'M0 -6V0'),
    'm': (6, 'M0 0V-4M0 -2.5A1.5 1.5 0 0 1 3 -2.5V0M3 -2.5A1.5 1.5 0 0 1 6 -2.5V0'),
    'n': (4, 'M0 0V-4M0 -2A2 2 0 0 1 4 -2V0'),
    'o': (4, 'M2 -4A2 2 0 1 0 2 0A2 2 0 1 0 2 -4Z'),
    'p': (4, 'M0 -4V2M0 -2A2 2 0 1 1 4 -2A2 2 0 1 1 0 -2'),
    'q': (4, 'M4 -4V2M4 -2A2 2 0 1 0 0 -2A2 2 0 1 0 4 -2'),
    'r': (2.8, 'M0 -4V0M0 -2A2 2 0 0 1 2.8 -3.8'),
    's': (3.6, 'M3.4 -3.4C3 -3.85 2.5 -4 1.8 -4C0.8 -4 0.2 -3.6 0.2 -3C0.2 -1.7 3.6 -2.3 3.6 -1C3.6 -0.3 2.9 0 1.9 0C1 0 0.4 -0.2 0 -0.7'),
    't': (2.6, 'M1 -5.6V-1A1 1 0 0 0 2 0H2.6M0 -4H2.6'),
    'u': (4, 'M0 -4V-2A2 2 0 0 0 4 -2M4 -4V0'),
    'v': (3.8, 'M0 -4L1.9 0L3.8 -4'),
    'w': (5, 'M0 -4L1.25 0L2.5 -3L3.75 0L5 -4'),
    'x': (3.6, 'M0 -4L3.6 0M3.6 -4L0 0'),
    'y': (4, 'M0 -4V-2A2 2 0 0 0 4 -2M4 -4V0A2 2 0 0 1 0.4 1.2'),
    'z': (3.6, 'M0 -4H3.6L0 0H3.6'),
    # signs
    '*': (4, 'M2 -5V-1M0.27 -4L3.73 -2M0.27 -2L3.73 -4'),
    '#': (4.2, 'M1.4 -5.2V-0.8M2.8 -5.2V-0.8M0 -3.9H4.2M0 -2.1H4.2'),
    '+': (3.6, 'M1.8 -4.6V-1.4M0.2 -3H3.4'),
    '-': (2.6, 'M0 -2.6H2.6'),
    '/': (2.4, 'M0 0.4L2.4 -6.4'),
    ' ': (1.6, ''),
}


def width(s, gap):
    """The width of the line s, in glyph units, with gap between two glyphs."""
    return sum(GLYPHS[c][0] for c in s) + gap * (len(s) - 1)


def line(s, x, y, size, colour, weight=0.6, anchor='start', gap=1.3):
    """The line s as one stroked path: (x, y) is the start of the baseline (anchor 'middle': its middle, 'end': its end),
    size the height of a capital in picture pixels, weight the stroke in glyph units."""
    k = size / 6.0
    w = width(s, gap) * k
    x0 = x - (w / 2 if anchor == 'middle' else w if anchor == 'end' else 0)
    parts, dx = [], 0.0
    for c in s:
        adv, d = GLYPHS[c]
        if d:
            parts.append('<path transform="translate(%g 0)" d="%s"/>' % (round(dx, 3), d))
        dx += adv + gap
    return ('<g transform="translate(%g %g) scale(%g)" fill="none" stroke="%s" stroke-width="%g" stroke-linecap="round" '
            'stroke-linejoin="round">%s</g>' % (round(x0, 3), round(y, 3), round(k, 4), colour, weight, ''.join(parts)))


def wordmark(x, y, xheight, colour, anchor='middle', weight=0.62, name=None):
    """The product name (NAME, or name) in the small letters above: (x, y) on the baseline, xheight in picture pixels."""
    return line((name or NAME).lower(), x, y, xheight * 1.5, colour, weight, anchor, gap=1.25)


def sign(cx, cy, r, colour, cut=0.8):
    """The Myna sign: a solid circle with a flat cut at the top and at the bottom (cut = the height of each cut line from
    the centre, as a part of r)."""
    h = r * cut
    a = (r * r - h * h) ** 0.5
    return ('<path d="M%g %gH%gA%g %g 0 0 1 %g %gH%gA%g %g 0 0 1 %g %gZ" fill="%s"/>'
            % (cx - a, cy - h, cx + a, r, r, cx + a, cy + h, cx - a, r, r, cx - a, cy - h, colour))
