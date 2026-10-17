# SPDX-License-Identifier: MIT
"""The standby wallpapers of the three Myna themes, 240 x 320, drawn for this project as SVG (original work, MIT).

  dunes      theme Pebble: a warm evening, a low sun, four layers of soft dunes
  dunes_night  theme Pebble, dark: the same dunes at dusk, a small moon
  contour    theme Instrument: a graphite survey map, contour lines, one line in the signal colour
  lanterns   theme Lantern: a deep ink night, a clay glow on the horizon, out-of-focus lights

live(name) gives dunes and dunes_night in parts for the animated standby: the sky alone and each dune band alone, with
an edge that repeats every 240 px.
"""
import math
import random


def _svg(body, defs=''):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="240" height="320" viewBox="0 0 240 320"><defs>%s</defs>%s</svg>'
            % (defs, body))


def _wave(y, amp, phase, freq=1.0, bottom=320):
    """A soft band edge across the width: a smooth curve through points of a sum of two sines."""
    pts = []
    for i in range(13):
        x = i * 20
        yy = y + amp * math.sin(freq * x / 38.0 + phase) + amp * 0.45 * math.sin(freq * x / 17.0 + phase * 1.7)
        pts.append((x, yy))
    d = 'M0 %g' % pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cx = (x0 + x1) / 2
        d += ' C%g %g %g %g %g %g' % (cx, y0, cx, y1, x1, y1)
    return d + ' V%d H0 Z' % bottom


DUNE_BANDS = [(186, 9, 0.6, '#e8c3a0', '#e2b792'), (214, 11, 2.1, '#d9a27e', '#cf916d'),
              (244, 10, 4.0, '#b9765a', '#a9674d'), (276, 9, 5.3, '#7f5244', '#6e4639')]
NIGHT_BANDS = [(186, 9, 0.6, '#5a3d4b', '#4f3542'), (214, 11, 2.1, '#45303c', '#3c2934'),
               (244, 10, 4.0, '#33232d', '#2b1e26'), (276, 9, 5.3, '#21171d', '#1a1217')]


def _dunes_sky():
    """the sky of dunes without the dunes: (defs, body)"""
    defs = ('<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f8eee2"/>'
            '<stop offset=".55" stop-color="#f3d9bd"/><stop offset="1" stop-color="#eec3a0"/></linearGradient>'
            '<radialGradient id="sun"><stop offset="0" stop-color="#fbd0a6"/><stop offset=".62" stop-color="#f6b386"/>'
            '<stop offset="1" stop-color="#f6b386" stop-opacity="0"/></radialGradient>')
    body = '<rect width="240" height="320" fill="url(#sky)"/><circle cx="168" cy="178" r="44" fill="url(#sun)"/>'
    return defs, body


def _bands(defs, body, bands):
    for i, (y, a, p, top, bot) in enumerate(bands):
        defs += ('<linearGradient id="d%d" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s"/>'
                 '<stop offset="1" stop-color="%s"/></linearGradient>' % (i, top, bot))
        body += '<path d="%s" fill="url(#d%d)"/>' % (_wave(y, a, p), i)
    return _svg(body, defs)


def dunes():
    return _bands(*_dunes_sky(), DUNE_BANDS)


def _night_sky():
    """the sky of dunes_night without the dunes: (defs, body)"""
    defs = ('<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#161a33"/>'
            '<stop offset=".45" stop-color="#2a2747"/><stop offset=".62" stop-color="#4a3450"/>'
            '<stop offset="1" stop-color="#7a4a4c"/></linearGradient>'
            '<radialGradient id="glow"><stop offset="0" stop-color="#f3e6cf" stop-opacity=".38"/>'
            '<stop offset="1" stop-color="#f3e6cf" stop-opacity="0"/></radialGradient>'
            '<linearGradient id="moon" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fbf3e2"/>'
            '<stop offset="1" stop-color="#e9dcc2"/></linearGradient>')
    body = '<rect width="240" height="320" fill="url(#sky)"/>'
    for x, y, r, op in ((22, 30, .8, .7), (64, 142, .7, .5), (118, 136, .6, .45), (210, 34, .8, .65), (226, 96, .6, .5),
                        (14, 112, .6, .45), (98, 150, .5, .4), (150, 128, .6, .5)):
        body += '<circle cx="%g" cy="%g" r="%g" fill="#fff6e6" opacity="%g"/>' % (x, y, r, op)
    body += '<circle cx="184" cy="150" r="24" fill="url(#glow)"/><circle cx="184" cy="150" r="7.5" fill="url(#moon)"/>'
    return defs, body


def dunes_night():
    """The night variant of dunes (theme Pebble, dark): a blue-violet dusk sky with a dim warm afterglow at the horizon,
    a small pale moon low on the right, a few stars, the same four dune layers in dark warm tones."""
    return _bands(*_night_sky(), NIGHT_BANDS)


# ---- the living versions: the standby's slow drift (firmware: src/ui/livewall.c) ----
#
# The same dunes, each band with an edge that repeats every 240 px (the screen's width), so that the firmware can slide
# it sideways for ever: a frame is the sky, then each band copied at its own offset, the far ones slower. The edge is
# the still picture's first sine, with whole fractions of its period for the others (a half, and a third for a little
# more unevenness: the still ratio of 2.24 never repeats); rows, heights, phases and colours are the still picture's,
# and so is the sky (without the dunes).

LIVE_PERIOD = 240
LIVE_BOTTOM = 294          # the soft-key bar covers the rest


def _pwave_points(y, amp, phase):
    pts = []
    for x in range(-24, LIVE_PERIOD + 25, 8):
        t = 2 * math.pi * x / LIVE_PERIOD
        pts.append((x, y + amp * math.sin(t + phase) + amp * 0.45 * math.sin(2 * t + phase * 1.7)
                    + amp * 0.2 * math.sin(3 * t + phase * 2.3)))
    return pts


def _pwave(pts, bottom=320):
    d = 'M%g %g' % pts[0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cx = (x0 + x1) / 2
        d += ' C%g %g %g %g %g %g' % (cx, y0, cx, y1, x1, y1)
    return d + ' V%d H%g Z' % (bottom, pts[0][0])


def live(name):
    """{'sky': SVG, 'layers': [SVG of each band alone, far to near], 'edges': [(highest, lowest) y of each edge],
    'still_top': the highest y of the still picture's dunes}.
    Between two points the curve stays within their heights, so the points give the edge's extent exactly."""
    sky, bands = {'dunes': (_dunes_sky, DUNE_BANDS), 'dunes_night': (_night_sky, NIGHT_BANDS)}[name]
    defs, body = sky()
    # the still picture's highest dune point: from there down, the moving picture replaces it
    still = min(y + a * math.sin(x / 38.0 + p) + a * 0.45 * math.sin(x / 17.0 + p * 1.7)
                for y, a, p, _, _ in bands for x in range(0, 241, 20))
    out = {'sky': _svg(body, defs), 'layers': [], 'edges': [], 'still_top': still}
    for y, a, p, top, bot in bands:
        pts = _pwave_points(y, a, p)
        lo, hi = min(q[1] for q in pts), max(q[1] for q in pts)
        g = ('<linearGradient id="b" gradientUnits="userSpaceOnUse" x1="0" y1="%g" x2="0" y2="320">'
             '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient>' % (lo, top, bot))
        out['layers'].append(_svg('<path d="%s" fill="url(#b)"/>' % _pwave(pts), g))
        out['edges'].append((lo, hi))
    return out


def _blob(cx, cy, r, k, seed):
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, 6.28) for _ in range(3)]
    pts = []
    for i in range(48):
        a = 2 * math.pi * i / 48
        rr = r * (1 + k * (0.5 * math.sin(2 * a + ph[0]) + 0.3 * math.sin(3 * a + ph[1]) + 0.2 * math.sin(5 * a + ph[2])))
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a) * 0.82))
    return 'M' + 'L'.join('%.1f %.1f' % p for p in pts) + 'Z'


def contour(accent='#f2c12e'):
    defs = ('<linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a2d32"/>'
            '<stop offset="1" stop-color="#16181b"/></linearGradient>'
            '<pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" fill="none" '
            'stroke="#ffffff" stroke-opacity=".035" stroke-width="1"/></pattern>')
    body = '<rect width="240" height="320" fill="url(#g)"/><rect width="240" height="320" fill="url(#grid)"/>'
    for cx, cy, n, seed in ((150, 210, 11, 3), (40, 120, 6, 8)):
        for i in range(n, 0, -1):
            hi = (cx, i) == (150, 6)
            body += '<path d="%s" fill="none" stroke="%s" stroke-opacity="%g" stroke-width="%g"/>' % (
                _blob(cx, cy, 10 + i * 11, 0.18, seed), accent if hi else '#ffffff', 1 if hi else .14, 1.4 if hi else 1)
    body += ('<path d="M150 204V216M144 210H156" stroke="%s" stroke-width="1.2"/>' % accent)
    return _svg(body, defs)


def lanterns(glow='#d9694a'):
    defs = ('<linearGradient id="n" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#101a2b"/>'
            '<stop offset=".62" stop-color="#22304a"/><stop offset="1" stop-color="#2b2742"/></linearGradient>'
            '<radialGradient id="h" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="%s" stop-opacity=".75"/>'
            '<stop offset="1" stop-color="%s" stop-opacity="0"/></radialGradient>'
            '<radialGradient id="o" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#ffd9a8" stop-opacity=".95"/>'
            '<stop offset=".45" stop-color="#f3a46c" stop-opacity=".55"/><stop offset="1" stop-color="#f3a46c" stop-opacity="0"/>'
            '</radialGradient>' % (glow, glow))
    body = '<rect width="240" height="320" fill="url(#n)"/><ellipse cx="120" cy="248" rx="190" ry="46" fill="url(#h)"/>'
    for x, y, r, op in ((46, 196, 16, .9), (92, 170, 9, .7), (158, 150, 22, .8), (204, 204, 11, .75), (124, 214, 7, .6),
                        (22, 140, 6, .45), (190, 112, 5, .4), (70, 232, 10, .65)):
        body += '<circle cx="%g" cy="%g" r="%g" fill="url(#o)" opacity="%g"/>' % (x, y, r * 1.8, op)
    body += '<path d="%s" fill="#0d1422"/>' % _wave(266, 7, 1.2)
    body += '<path d="%s" fill="#090e18"/>' % _wave(290, 6, 3.4)
    return _svg(body, defs)


WALLPAPERS = {'dunes': dunes, 'dunes_night': dunes_night, 'contour': contour, 'lanterns': lanterns}
