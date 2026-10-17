#!/usr/bin/env python3
"""Draw the pictures of this skin: the Myna P2 flip, the clamshell of the pebble family.

    python3 -I draw.py          (from any directory: it works on the folder it is in; BRAND=name changes the wordmark)

Original work of the project, standard library only; the parts are those of the P2 family (pebble.py, the same file as in
the chin slider's folder).

The phone is two halves of one plan joined by a hinge. Open, the lid carries the dark pane with the screen and the name
under it; the base carries one key field set straight into its face: the soft keys, call and end, the coin, activity and
back, then the twelve number keys, all cells of one surface, each gently domed, cut apart by grooves only where keys meet
(no tray, no separate plate). Under the field the base's plain end carries the microphone.

The hinge: a satin barrel, the lid's, between two knuckles in the body colour, the base's; all three are one cylinder of
radius R on one axis, which lies across the top end of the base, halfway between the two halves when closed. Each half
ends a barrel radius from the axis, so the barrel fills the gap between them in the open picture and stands above both
in the closed one. Closed, the phone shows the outside of its lid, "Ripple": no outer display; high-gloss lacquer with a
field of spun-metal pinstripe rings cut through it round one jewel-cut light window (it glows for a call, a message or
charging); the name in polished metal near the free end (the section "the lid's outside" below). The base's back is the
soft-touch shell, as the chin slider's back: the lacquer is the lid's alone.

Frames (docs/SKINS_3D.md, "A flip"): the open picture shows both halves face-on, the lid as if opened flat; a point of the
base is OFFSET lower in it than in the closed picture; a point of the lid at closed y is at open y = AXIS_O - (y - AXIS_C)
(the lid turned over the axis). The 3D viewer turns the lid to the open angle of skin.json.
"""
import importlib.util
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('pebble', os.path.join(HERE, 'pebble.py'))
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)
L = B.L
W = B.W

R = 8                           # the hinge's radius in picture px (2.29 mm): barrel and knuckles
HALF = 232                      # each half, from its hinge end to its free end (66.3 mm)
AXIS_C = 4 + R                  # the hinge axis: y in the closed picture (the barrel's top is the body's top)
AXIS_O = 4 + HALF + R           # y in the open picture (the lid's free end is the body's top)
OFFSET = AXIS_O - AXIS_C        # the base is this much lower in the open picture than in the closed one
SIDES = (4, 172)                # left and right of both halves
HINGE_CORNER = (9, .35)         # the corners of each half at its hinge end; at the free end the body corner (B.CORNER)
BARREL = (20, 156)              # the satin barrel (the lid's), between the base's two knuckles
KNUCKLES = ((4, 19.5), (156.5, 172))
KNUCKLE_ROUND = 2.8             # the round of a knuckle's outer end
LAMP = (88, 80)                 # the light window on the lid's outside (closed picture)
LAMP_RING, LAMP_WINDOW = 10.5, 8.2  # its ring of spun metal and its jewel-cut window: radii
PANE = (12, 11, 20, 8)          # the lid's pane (open picture): its left, its top, how far under the screen it ends, its inset
NAME_OUT = 232                  # the name on the lid's outside, near its free end (closed picture, baseline)
BUMPERS_LID = ((34, 227), (142, 227))     # rubber pads (open picture): under the pane, they meet the base above its field
BUMPERS_BASE = ((34, 471), (142, 471))    # beside the microphone, they meet the lid's window above the screen


def lid_open():
    return AXIS_O - R - HALF, AXIS_O - R            # 4, 236


def base_open():
    return AXIS_O + R, AXIS_O + R + HALF            # 252, 484


def closed_half():
    return AXIS_C + R, AXIS_C + R + HALF            # 20, 252


def half(y0, y1, hinge_top, inset=0):
    """The plan of a half from y0 to y1, its hinge end at y0 (hinge_top) or at y1; inset shrinks it (for the band)."""
    e, k = HINGE_CORNER if hinge_top else B.CORNER
    eb, kb = B.CORNER if hinge_top else HINGE_CORNER
    return B.soft_rect(SIDES[0] + inset, y0 + inset, SIDES[1] - inset, y1 - inset, e - inset, k, bottom=(eb - inset, kb))


def ends_rect(x0, y0, x1, y1, rl, rr):
    """A rectangle with its two left corners rounded by rl and its two right corners by rr."""
    return ('M%g %g H%g A%g %g 0 0 1 %g %g V%g A%g %g 0 0 1 %g %g H%g A%g %g 0 0 1 %g %g V%g A%g %g 0 0 1 %g %g Z'
            % (x0 + rl, y0, x1 - rr, rr, rr, x1, y0 + rr, y1 - rr, rr, rr, x1 - rr, y1, x0 + rl, rl, rl, x0, y1 - rl,
               y0 + rl, rl, rl, x0 + rl, y0))


def flip_defs():
    """The barrel's satin, the shading of a cylinder in the body colour, the light window, the rubber pads."""
    a, b = B.P['band']
    lit = B.P['lit']
    return ('<linearGradient id="barrel" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s"/>'
            '<stop offset=".34" stop-color="%s"/><stop offset=".8" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient>'
            '<linearGradient id="cyl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity=".12"/>'
            '<stop offset=".3" stop-color="#fff" stop-opacity="%g"/><stop offset=".62" stop-color="#fff" stop-opacity="0"/>'
            '<stop offset="1" stop-color="#000" stop-opacity=".34"/></linearGradient>'
            '<radialGradient id="lamp" cx=".42" cy=".38" r=".7"><stop offset="0" stop-color="#ffffff"/>'
            '<stop offset=".7" stop-color="#f1ede6"/><stop offset="1" stop-color="#c9c3ba"/></radialGradient>'
            '<radialGradient id="disc" cx=".4" cy=".36" r=".75"><stop offset="0" stop-color="#fff" stop-opacity="%g"/>'
            '<stop offset=".6" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".3"/></radialGradient>'
            '<filter id="hblur" x="-10%%" y="-100%%" width="120%%" height="300%%"><feGaussianBlur stdDeviation="1.3"/></filter>'
            % (b, a, b, b, .12 if lit else .42, .1 if lit else .35))


# ---- the hinge, seen face on (front or back): axis across the picture at y yc
def knuckles(yc):
    """The base's two knuckles: short cylinders in the body colour, their outer ends rounded, their inner ends crisp."""
    out = ''
    for xa, xb in KNUCKLES:
        rl, rr = (KNUCKLE_ROUND, .6) if xa == SIDES[0] else (.6, KNUCKLE_ROUND)
        d = ends_rect(xa, yc - R, xb, yc + R, rl, rr)
        out += ('<path d="%s" fill="%s" filter="url(#seat)"/><path d="%s" fill="url(#cyl)"/>'
                '<path d="%s" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".5"/>' % (d, B.P['body'], d, d))
    return out


def barrel(yc):
    """The lid's barrel in satin metal between the knuckles: the dark gaps at its ends, its highlight along the upper third."""
    x0, x1 = BARREL
    d = ends_rect(x0, yc - R, x1, yc + R, .8, .8)
    gaps = ''.join(B.rr(x - .9, yc - R + 1, 1.8, 2 * R - 2, .5, '#000', 'opacity=".72"') for x in (KNUCKLES[0][1] + .25, KNUCKLES[1][0] - .25))
    return (gaps + '<path d="%s" fill="url(#barrel)" stroke="#000" stroke-opacity=".3" stroke-width=".5"/>' % d
            + '<path d="M%g %gH%g" stroke="#fff" stroke-opacity=".6" stroke-width=".8" stroke-linecap="round"/>' % (x0 + 3, yc - R * .45, x1 - 3)
            + '<path d="M%g %gH%g" stroke="#000" stroke-opacity=".12" stroke-width="1.6"/>' % (x0 + 1, yc + R - 1.2, x1 - 1))


def bumper(cx, cy):
    """A rubber pad (1.9 x 1 mm) that holds the halves apart when closed: a pill in a dark tone of the body, its lower lip lit."""
    return (B.rr(cx - 3.3, cy - 1.75 + .45, 6.6, 3.5, 1.75, '#fff', 'opacity="%g"' % (.12 if B.P['lit'] else .45))
            + B.rr(cx - 3.3, cy - 1.75, 6.6, 3.5, 1.75, B.P['groove'])
            + B.rr(cx - 2.6, cy - 1.2, 5.2, 1.1, .55, '#fff', 'opacity=".12"'))


# ---- the front pictures
def lid_inner(view):
    """The lid open, its inner face: the pane with the earpiece, the screen and the name; two pads under the pane."""
    y0, y1 = lid_open()
    g = view['glass']
    out = B.body(half(y0, y1, False), y0, y1) + [B.band(half(y0, y1, False, .7))]
    out += B.pane(g, PANE[0], PANE[1], g[1] + g[3] + PANE[2], inset=PANE[3])
    out += [bumper(*p) for p in BUMPERS_LID]
    return out


def base_front(view):
    """The base open: its key field, the microphone, two pads, the knuckles, and the barrel's shadow on its upper edge."""
    keys = view['keys']
    y0, y1 = base_open()
    path = half(y0, y1, True)
    out = B.body(path, y0, y1) + [B.band(half(y0, y1, True, .7))]
    out += B.plate(keys, {k: keys[k] for k in B.PAD_KEYS})
    out.append(B.slot(W / 2, y1 - 14))
    out += [bumper(*p) for p in BUMPERS_BASE]
    cid = B.uid('hshade')
    out.append('<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)"><rect x="%g" y="%g" width="%g" height="5" '
               'rx="2.5" fill="#000" opacity=".3" filter="url(#hblur)"/></g>' % (cid, path, cid, BARREL[0] + 1.2, y0 - 2.6, BARREL[1] - BARREL[0]))
    out.append(knuckles(AXIS_O))
    return out


# ---- the lid's outside: Ripple
#
# High-gloss lacquer in the body colour (a slight crown: the middle of the lid 1.4 mm higher than its long edges, 0.8 mm
# than its ends), with a field of pinstripe rings cut through it round the light window: spun-brushed metal 0.34 mm wide
# near the window, thinner and further apart going out, stopping round the name. Spun, so one radial highlight runs
# through every ring as the phone turns. The light window is a jewel cut in clear acrylic over a white diffuser, in a ring
# of the same metal; the name is polished metal. The metal is the colour's: Stone champagne, Ink blue steel, Ember rose
# gold.
#
# Four pictures of it, all in the closed picture's frame:
#   closed.svg          the 2D page's: with light drawn in (the gloss, the crown, the spun highlight, the cut of each ring)
#   closed.albedo.svg   the 3D view's: the colours only (lacquer, metal, window), no light
#   closed.mask.svg     which finish where (body3d front_finish): black the lacquer, green the pinstripes (pin), red the
#                       name (polish)
#   closed.relief.svg   height, white high: each ring a shallow groove (relief_mm deep)
# The rings, the cartouche round the name and the window are the same numbers in all four.
METALS = {      # the ring metal of each colour: name, colour (albedo), light and dark (the 2D picture's highlight and shade)
    'stone': ('champagne', '#ead7ae', '#fffaf0', '#9c8457'),
    'ink': ('blue steel', '#a9b8d2', '#f4f7fc', '#5c6881'),
    'ember': ('rose gold', '#efbda8', '#fff2ec', '#a26a56'),
}
WINDOW = '#f3f1ec'               # the jewel's colour: clear acrylic over the white diffuser
RIPPLE = (13, 168, 4.5)          # px: the first ring's radius, the field's reach, how far inside the lid's outline it stops
CARTOUCHE = (44, 17)             # px: the quiet place round the name (a pill), where no ring runs
CROWN = [1.4, 0.8]               # mm: the lid's crown, across and along
RELIEF_MM = .03                  # mm: how deep a ring is cut
JEWEL = {'facets': 12, 'crown': .45, 'girdle': .12, 'table': .52}    # the window's cut: facets, mm, mm, part of its radius
LAMP_PROUD = .15                 # mm: the light window's ring above the lid's outside
FINISH = {'base': 'lacquer', 'r': 'polish', 'g': 'pin', 'mask': 'closed.mask.svg', 'relief': 'closed.relief.svg', 'relief_mm': RELIEF_MM,
          'crown': CROWN, 'brush': {'g': {'grooves': 'circles', 'at': list(LAMP)}}}


_rid = [0]


def rid(stem):
    """An id for the Ripple drawings' own defs (pebble.uid's numbers stay as they were for the other pictures)."""
    _rid[0] += 1
    return 'rp%s%d' % (stem, _rid[0])


def ripple_rings():
    """(radius, width) of each ring, px: 1.2 px (0.34 mm) near the window, thinner going out, the gaps growing."""
    out, r = [], float(RIPPLE[0])
    while r < RIPPLE[1]:
        out.append((round(r, 3), round(max(.55, 1.2 - .0045 * r), 3)))
        r += 4.2 + .028 * r
    return out


def ripple(clip, lamp, name_at, paint):
    """The field of rings round lamp, inside clip (a path), not in the cartouche round name_at; paint(r, w) draws a ring."""
    cx, cy = lamp
    mid, cid = rid('quiet'), rid('rip')
    cw, ch = CARTOUCHE
    quiet = ('<mask id="%s"><rect width="%d" height="600" fill="#fff"/><rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="#000"/></mask>'
             % (mid, W, name_at[0] - cw / 2, name_at[1] - 11.5, cw, ch, ch / 2))
    rings = ''.join(paint(cx, cy, r, w) for r, w in ripple_rings())
    return quiet + '<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)"><g mask="url(#%s)">%s</g></g>' % (cid, clip, cid, mid, rings)


def ring_in(colour, extra=''):
    return lambda cx, cy, r, w: '<circle cx="%g" cy="%g" r="%g" fill="none" stroke="%s" stroke-width="%g"%s/>' % (cx, cy, r, colour, w, extra)


def name_mark(name_at, colour, turned):
    mark = L.wordmark(name_at[0], name_at[1], 3.2, colour)
    return '<g transform="rotate(180 %g %g)">%s</g>' % (name_at[0], name_at[1] - 2.4, mark) if turned else mark


def jewel(cx, cy, r, lit):
    """The light window, face on: a jewel cut of JEWEL['facets'] sides (the table, the star and upper facets round it); lit:
    each facet as bright as it faces the light up on the left, else all in the window's colour."""
    n, t = JEWEL['facets'], JEWEL['table']
    g = lambda i: (cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
    q = lambda i: (cx + r * t * math.cos(2 * math.pi * (i + .5) / n), cy + r * t * math.sin(2 * math.pi * (i + .5) / n))
    poly = lambda pts, fill, op: '<path d="M%sZ" fill="%s" fill-opacity="%.3f"/>' % ('L'.join('%.2f %.2f' % p for p in pts), fill, op)
    out = ['<circle cx="%g" cy="%g" r="%g" fill="%s"/>' % (cx, cy, r, WINDOW)]
    if lit:
        light = math.radians(-135)                                   # up on the left
        for i in range(n):
            for pts, a in (((g(i), g(i + 1), q(i)), 2 * math.pi * (i + .5) / n), ((q(i - 1), g(i), q(i)), 2 * math.pi * i / n)):
                k = math.cos(a - light)
                out.append(poly(pts, '#fff' if k > 0 else '#5f5b55', .75 * k if k > 0 else -.45 * k))
        out.append(poly([q(i) for i in range(n)], '#fff', .5))
        out.append('<path d="M%sZ" fill="none" stroke="#000" stroke-opacity=".12" stroke-width=".25"/>'
                   % 'L'.join('%.2f %.2f' % q(i) for i in range(n)))
    out.append('<circle cx="%g" cy="%g" r="%g" fill="none" stroke="#000" stroke-opacity="%g" stroke-width=".35"/>' % (cx, cy, r, .3 if lit else .12))
    return ''.join(out)


def sweep(cx, cy, angle, half, blur, reach=200):
    """Two opposite wedges through (cx, cy) along angle (degrees), each half degrees wide on either side: where spun metal
    catches the light."""
    pts = []
    for a in (angle, angle + 180):
        a0, a1 = math.radians(a - half), math.radians(a + half)
        pts.append('M%g %gL%.2f %.2fL%.2f %.2fZ' % (cx, cy, cx + reach * math.cos(a0), cy + reach * math.sin(a0), cx + reach * math.cos(a1), cy + reach * math.sin(a1)))
    fid = rid('sw')
    return ('<filter id="%s" x="-50%%" y="-50%%" width="200%%" height="200%%"><feGaussianBlur stdDeviation="%g"/></filter>' % (fid, blur),
            '<path d="%s" fill="#fff" filter="url(#%s)"/>' % (''.join(pts), fid))


def current():
    """The colour pebble.py draws in now (pebble.use)."""
    return next(k for k, v in B.PALETTES.items() if v == B.P)


def _lid_outside(path, y0, y1, lamp, name_at, variant=None, turned=False, kind='lit'):
    """The lid's outside, Ripple (above). kind: 'lit', the 2D page's picture (closed.svg); 'albedo', the colours only (the 3D
    view's closed.albedo.svg, and back_open.svg); 'mask' and 'relief' (body3d front_finish). turned: seen from behind with
    the phone open (the lid turned over the axis), so the name is upside down."""
    cx, cy = lamp
    hinge_top = not turned
    clip = half(y0, y1, hinge_top, RIPPLE[2])
    _, metal, light, dark = METALS[variant or current()]
    if kind == 'mask':
        return ['<rect width="%d" height="%d" fill="#000"/>' % (W, 600), ripple(clip, lamp, name_at, ring_in('#00ff00')),
                name_mark(name_at, '#ff0000', turned)]
    if kind == 'relief':
        fid = rid('cut')
        return ['<rect width="%d" height="%d" fill="#fff"/>' % (W, 600),
                '<filter id="%s" x="-5%%" y="-5%%" width="110%%" height="110%%"><feGaussianBlur stdDeviation=".3"/></filter>' % fid,
                '<g filter="url(#%s)">%s</g>' % (fid, ripple(clip, lamp, name_at, ring_in('#000')))]
    if kind == 'albedo':
        return ['<path d="%s" fill="%s"/>' % (path, B.P['body']), ripple(clip, lamp, name_at, ring_in(metal)),
                B.band(half(y0, y1, hinge_top, .7)),
                '<circle cx="%g" cy="%g" r="%g" fill="%s"/>' % (cx, cy, LAMP_RING, metal), jewel(cx, cy, LAMP_WINDOW, False),
                name_mark(name_at, metal, turned)]
    # the 2D picture: the moulded lid, the crown (light in the middle, its edges turning away), the rings (the cut's shade
    # under each, the metal, the spun highlight across them up on the left and down on the right and their shade across
    # that), the gloss (the key light's box and a long sheen), the band, the window and the name
    lit = B.P['lit']
    out = B.body(path, y0, y1, upper=not turned)
    gid, cid = rid('crown'), rid('lidclip')
    out.append('<radialGradient id="%s" cx=".42" cy=".36" r=".75"><stop offset="0" stop-color="#fff" stop-opacity="%g"/>'
               '<stop offset=".55" stop-color="#fff" stop-opacity="0"/><stop offset=".85" stop-color="#000" stop-opacity="0"/>'
               '<stop offset="1" stop-color="#000" stop-opacity="%g"/></radialGradient>' % (gid, .1 if lit else .22, .16 if lit else .1))
    out.append('<clipPath id="%s"><path d="%s"/></clipPath>' % (cid, path))
    out.append('<path d="%s" fill="url(#%s)"/>' % (path, gid))
    hi, hm = sweep(cx, cy, -128, 11, 4.5)
    lo, lm = sweep(cx, cy, -38, 20, 8)
    mh, ml = rid('spun'), rid('spunlo')
    out.append(hi + lo + '<mask id="%s">%s</mask><mask id="%s">%s</mask>' % (mh, hm, ml, lm))
    out.append(ripple(clip, lamp, name_at, lambda x, y, r, w: '<circle cx="%g" cy="%g" r="%g" fill="none" stroke="#000" stroke-opacity="%g" '
                      'stroke-width="%g"/>' % (x, y + .28, r, .22 if lit else .1, w + .25)))
    out.append(ripple(clip, lamp, name_at, ring_in(metal)))
    out.append('<g mask="url(#%s)">%s</g>' % (ml, ripple(clip, lamp, name_at, ring_in(dark, ' stroke-opacity=".85"'))))
    out.append('<g mask="url(#%s)">%s</g>' % (mh, ripple(clip, lamp, name_at, ring_in(light))))
    # the gloss: the key light's box up on the left, soft, and a long faint sheen across the lid
    bid, sid = rid('box'), rid('sheen')
    x0, x1 = SIDES
    out.append('<filter id="%s" x="-30%%" y="-30%%" width="160%%" height="160%%"><feGaussianBlur stdDeviation="3.2"/></filter>'
               '<linearGradient id="%s" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
               '<stop offset=".33" stop-color="#fff" stop-opacity="%g"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient>'
               % (bid, sid, .1 if lit else .2))
    by = (y0 + 14) if not turned else (y1 - 64)
    out.append('<g clip-path="url(#%s)"><path d="%s" fill="url(#%s)"/><rect x="%g" y="%g" width="40" height="46" rx="10" '
               'transform="rotate(-14 %g %g)" fill="#fff" opacity="%g" filter="url(#%s)"/></g>'
               % (cid, path, sid, x0 + 12, by, x0 + 32, by + 23, .18 if lit else .34, bid))
    out.append(B.band(half(y0, y1, hinge_top, .7)))
    # the window's ring: spun metal, lit on its upper left, a seat of shade round it; the jewel in it
    ringid = rid('ring')
    out.append('<radialGradient id="%s" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="%s"/><stop offset=".55" stop-color="%s"/>'
               '<stop offset="1" stop-color="%s"/></radialGradient>' % (ringid, light, metal, dark))
    out.append('<circle cx="%g" cy="%g" r="%g" fill="url(#%s)" filter="url(#seat)"/>' % (cx, cy, LAMP_RING, ringid))
    out.append(jewel(cx, cy, LAMP_WINDOW, True))
    out.append(name_mark(name_at, dark if not lit else light, turned))
    return out


def lid_outside(path, y0, y1, lamp, name_at, variant=None, turned=False, kind='lit'):
    """_lid_outside(), leaving pebble.uid's count where the lid's earlier drawing (two ids) left it for the pictures drawn
    after it (closed.svg and back_open.svg), and where it was for the new ones (no ids), so they keep theirs."""
    n = B._ids[0]
    out = _lid_outside(path, y0, y1, lamp, name_at, variant, turned, kind)
    B._ids[0] = n + (2 if kind == 'lit' or turned else 0)
    return out


def front(view, part, variant=None):
    """closed.svg (part 'closed'; 'albedo', 'mask', 'relief': the lid's outside for the 3D view); open.svg; the layers
    lid.svg, base.svg and hinge.svg (open picture)."""
    w, h = view['size']
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">' % (w, h, w, h),
           B.defs().replace('</defs>', flip_defs() + '</defs>')]
    if part in ('closed', 'albedo', 'mask', 'relief'):
        y0, y1 = closed_half()
        if part in ('closed', 'albedo'):
            out += [knuckles(AXIS_C), barrel(AXIS_C)]
        else:
            out = out[:1]
        out += lid_outside(half(y0, y1, True), y0, y1, LAMP, (W / 2, NAME_OUT), variant, kind='lit' if part == 'closed' else part)
    else:
        if part in ('open', 'base'):
            out += base_front(view)
        if part in ('open', 'lid'):
            out += lid_inner(view)
        if part in ('open', 'hinge'):
            out.append(barrel(AXIS_O))
    out.append('</svg>')
    return '\n'.join(x for x in out if x) + '\n'


# ---- the outside: the back, the sides and the hinge's ends, for the 3D view (skin.json "body3d")
#
# The lid is one shell in the body colour (its outer cover and its inner cover meet at a part line 2 mm from the outer face),
# with the satin band on both its edges: round the outside, the closed phone's face, and round the inner face. The base is
# built as the chin slider's back slab: a front cover in the body colour carries the key field and the satin band; a carrier
# in the darker tone forms the side band; the rear shell in the body colour forms the back with its 2 mm edge radius, and
# the battery cover is the middle of it, between two seams straight across the back.
#
# Rear layout (closed picture, seen from behind, so the phone's left is on the right): the camera on the centre line near
# the hinge, the coin's metal in the coin's shape; the flash under it; the cover's seams; the name engraved low on the
# cover; the loudspeaker under the lower seam; a nail notch at one end of the lower seam, the lanyard eyelet at the other
# corner. Sides: volume rocker and the two-stage shutter on the right of the base, the memory card door on the left, the
# USB-C receptacle and the lanyard slot on the base's free end; the lid has no keys. The hinge's ends show the knuckles'
# round ends, each with the cap of the hinge pin.
#
# These pictures are albedo, as the chin slider's: the colours and the details of the surfaces, with no light drawn in on
# the parts that the 3D view maps them onto (no shade across the thickness, no turning ends, no drop shadows), because the
# 3D view lights them itself. The front pictures (the 2D page's) keep their drawn light. The hinge's ends in the side
# pictures and the knuckles beside the base in the back pictures keep theirs: the 3D view has their solids instead.
LENS = (88, 50, 15)              # the camera ring: centre and radius (closed picture, seen from behind)
FLASH = (88, 73)
SEAMS = (86, 212)                # the battery cover's seams across the back
NAME_Y = 196
GRILLE = (88, 231, (9, 10, 9))
NOTCH_X = 36                     # the nail notch under the lower seam (seen from behind; the phone's right)
EYELET = (140, 242)              # the lanyard eyelet on the back (seen from behind; the phone's lower left corner)
ROCKER = (36, 80)                # right side of the base, closed picture y: volume up (upper half) and down (lower half)
SHUTTER = (196, 224)             # right side: the two-stage shutter, spun metal
ROCKER_H, SHUTTER_H = 4.2, 4.4   # px: half their height across the side, about the middle of the carrier band
CARD = (110, 163)                # left side: the memory card door
USB_C = (8.94, 3.26)             # mm: the USB-C receptacle's opening on the base's free end, centred across it
USB_Z = 11.55                    # mm: the middle of the opening, from the closed front (the middle of the carrier band)
USB_DEPTH = 3.6                  # mm: how far the receptacle's shell goes in
PIN = 2.2                        # px: the cap of the hinge pin in each knuckle's end

# The keys of the base as solids (body3d "caps") and the coin's opening ("wells"), in mm from the base's front: every key
# is a cell of the one key field, standing a little proud of the face; the coin stands in its opening and rises a little
# above the cells. Closed, the cells clear the lid's inner face by 0.5 mm, the coin by 0.35 (the gap is 0.9).
CELL_Z = (-.4, 0)               # the key field's cells: top, foot
OPENING = .6                    # the coin's opening: depth
COIN_Z = (-.3, .6)              # the coin: top of its rim, foot (on the opening's floor)
COIN_DOME = .25                 # the coin's middle above its rim
KEY_EDGE = (.18, .25)           # the round of the top edge: cells, coin


def _n(v):
    s = '%.2f' % v
    return s.rstrip('0').rstrip('.') if '.' in s else s


def _path(*parts):
    """A path from commands and numbers: numbers are written with at most two decimals."""
    return re.sub(r'([MHVCAZ]) ', r'\1', ' '.join(p if isinstance(p, str) else _n(p) for p in parts))


def round_rect_path(x, y, w, h, r):
    return _path('M', x + r, y, 'H', x + w - r, 'A', r, r, '0 0 1', x + w, y + r, 'V', y + h - r, 'A', r, r, '0 0 1', x + w - r, y + h,
                 'H', x + r, 'A', r, r, '0 0 1', x, y + h - r, 'V', y + r, 'A', r, r, '0 0 1', x + r, y, 'Z')


def circle_path(cx, cy, r):
    return _path('M', cx - r, cy, 'A', r, r, '0 1 1', cx + r, cy, 'A', r, r, '0 1 1', cx - r, cy, 'Z')


def sign_path(cx, cy, r, h):
    """The Myna sign (lettering.sign) as an outline: a circle of radius r cut flat at h above and below its centre."""
    a = (r * r - h * h) ** .5
    return _path('M', cx - a, cy - h, 'H', cx + a, 'A', r, r, '0 0 1', cx + a, cy + h, 'H', cx - a, 'A', r, r, '0 0 1', cx - a, cy - h, 'Z')


def plate_grooves(keys, pad):
    """The grooves pebble.plate cuts the key field by (keys and pad in the picture's own frame), as the d of its paths: the
    cuts (one across under the soft keys, one between the soft keys, on each side one between call and activity (end and
    clear) that ends at the coin's opening, one under each row of number keys and two between their columns), the groove
    round the field and the coin's opening. Nothing cuts the field between call and end or between activity and clear."""
    names = ('soft_left', 'soft_right', 'call', 'end', 'activity', 'clear')
    rects = [keys[n] for n in names] + [pad[n] for n in B.PAD_KEYS]
    x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
    x1, y1 = max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)
    cx = B.mid(keys['select'])[0]
    top, bottom = keys['up'][1], keys['down'][1] + keys['down'][3]
    cy, h = (top + bottom) / 2, (bottom - top) / 2
    ring = (keys['right'][0] + keys['right'][2] - keys['left'][0]) / 2 + 3
    ys, ya = keys['call'][1] - 1, keys['activity'][1] - 1
    tops = sorted({pad[n][1] for n in B.PAD_KEYS})
    cuts = 'M%g %gH%g M%g %gV%g M%g %gH%g M%g %gH%g' % (x0, ys, x1, cx, y0, ys, x0, ya, cx - ring, cx + ring, ya, x1)
    cuts += ''.join(' M%g %gH%g' % (x0, t - 1, x1) for t in tops)
    cuts += ''.join(' M%g %gV%g' % (pad[n][0], tops[0] - 1, y1) for n in ('2', '3'))
    return [cuts, B.soft_rect(x0, y0, x1, y1, *B.INNER), re.search(r' d="([^"]+)"', B.L.sign(cx, cy, ring, '#000', (h + 3) / ring)).group(1)]


def front3d(skin):
    """(wells, caps, grooves) of body3d: the cells of the key field, cut as pebble.plate cuts them with the pad (each key the
    field's surface between the grooves, less half a groove on each side, the plate's lower keys less the coin's opening),
    the coin, and the coin's opening; and the grooves they follow, as the drawing has them (open picture), which
    check_body3d() looks for in the drawing. Outlines in closed-view px (the base is OFFSET higher than in the open picture).

    As on the chin slider, nothing cuts the field above or below the coin's opening: call and end are one moulding round the
    top of the coin, activity and clear one round its bottom, each half its own key (pressed, the moulding tips that way, as
    a rocker does)."""
    vo = next(v for v in skin['views'] if v['id'] == skin['hinge']['open'])
    grooves = plate_grooves(vo['keys'], {k: vo['keys'][k] for k in B.PAD_KEYS})
    keys = {k: [r[0], r[1] - OFFSET, r[2], r[3]] for k, r in vo['keys'].items()}
    pad = {k: keys[k] for k in B.PAD_KEYS}
    g = B.GROOVE / 2
    names = ('soft_left', 'soft_right', 'call', 'end', 'activity', 'clear')
    rects = [keys[n] for n in names] + [pad[n] for n in B.PAD_KEYS]
    x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
    x1, y1 = max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)
    cx = B.mid(keys['select'])[0]
    top, bottom = keys['up'][1], keys['down'][1] + keys['down'][3]
    cy, h = (top + bottom) / 2, (bottom - top) / 2
    r = (keys['right'][0] + keys['right'][2] - keys['left'][0]) / 2
    ring, hr = r + 3, h + 3                            # the opening, as pebble.plate cuts it
    ys, ya = keys['call'][1] - 1, keys['activity'][1] - 1
    tops = sorted({pad[n][1] for n in B.PAD_KEYS})
    t0 = tops[0] - 1                                   # the groove between the plate's keys and the number keys
    assert cy - hr > ys + g and cy + hr < t0 - g and abs(cx - W / 2) < 1e-9
    e = B.INNER[0] - g
    c = e * B.INNER[1]
    X0, X1, Y0, Y1 = x0 + g, x1 - g, y0 + g, y1 - g
    oa = (ring * ring - hr * hr) ** .5
    arc = lambda y: (ring * ring - (y - cy) ** 2) ** .5   # half the opening's width at y
    D0 = cx - X0
    XR, XL = (lambda d: cx + d), (lambda d: cx - d)    # d: the distance from the centre line

    def soft(X):
        return _path('M', X(g), Y0, 'H', X(D0 - e), 'C', X(D0 - c), Y0, X(D0), Y0 + c, X(D0), Y0 + e, 'V', ys - g, 'H', X(g), 'Z')

    upper = _path('M', XL(D0), ys + g, 'H', XR(D0), 'V', ya - g, 'H', XR(arc(ya - g)), 'A', ring, ring, '0 0 0', XR(oa), cy - hr,
                  'H', XL(oa), 'A', ring, ring, '0 0 0', XL(arc(ya - g)), ya - g, 'H', XL(D0), 'Z')
    lower = _path('M', XL(D0), ya + g, 'H', XL(arc(ya + g)), 'A', ring, ring, '0 0 0', XL(oa), cy + hr, 'H', XR(oa),
                  'A', ring, ring, '0 0 0', XR(arc(ya + g)), ya + g, 'H', XR(D0), 'V', t0 - g, 'H', XL(D0), 'Z')
    plate = (('soft_left', soft(XL)), ('soft_right', soft(XR)), (['call', 'end'], upper), (['activity', 'clear'], lower))
    caps = [{'key': k, 'slab': 'base', 'outline': d, 'z': list(CELL_Z), 'edge': KEY_EDGE[0], 'material': 'shell'} for k, d in plate]
    caps.append({'key': ['select', 'up', 'down', 'left', 'right'], 'slab': 'base', 'outline': sign_path(cx, cy, r, h), 'z': list(COIN_Z),
                 'edge': KEY_EDGE[1], 'dome': COIN_DOME, 'material': 'spun'})
    cols = [x0, pad['2'][0], pad['3'][0], x1]
    rows = [t - 1 for t in tops] + [y1]
    for name in B.PAD_KEYS:
        i, j = tops.index(pad[name][1]), cols.index(pad[name][0])
        xa, xb = cols[j] + g, cols[j + 1] - g
        ya_, yb = rows[i] + g, rows[i + 1] - g
        if i == len(tops) - 1 and j == 0:              # the field's lower left corner
            d = _path('M', xa, ya_, 'H', xb, 'V', yb, 'H', X0 + e, 'C', X0 + c, Y1, X0, Y1 - c, X0, Y1 - e, 'Z')
        elif i == len(tops) - 1 and j == 2:            # its lower right corner
            d = _path('M', xa, ya_, 'H', xb, 'V', Y1 - e, 'C', X1, Y1 - c, X1 - c, Y1, X1 - e, Y1, 'H', xa, 'Z')
        else:
            d = _path('M', xa, ya_, 'H', xb, 'V', yb, 'H', xa, 'Z')
        caps.append({'key': name, 'slab': 'base', 'outline': d, 'z': list(CELL_Z), 'edge': KEY_EDGE[0], 'material': 'shell'})
    wells = [{'slab': 'base', 'outline': sign_path(cx, cy, ring, hr), 'depth': OPENING, 'material': 'shell'}]
    return wells, caps, grooves


CAMERA_PROUD = .5               # mm: the camera ring above the back
LENS_DEPTH = .4                 # mm: the lens under the ring's top
FLASH_PROUD = .12               # mm: the flash's window above the back
EAR_DEPTH = .6                  # mm: the earpiece's slot, from the glass down to its grille
EAR_EDGE = .2                   # mm: the round of the slot's edge


def outside3d(skin):
    """(inlays, features) of body3d, as drawn. The inlay: the glass pane of the lid's inner face (pebble.pane in lid_inner),
    flush, its outline in the closed picture (the lid's inner face turned back over the axis: open y = AXIS_O + AXIS_C - y,
    x unchanged). The features: the camera ring (pebble.lens) and the flash (pebble.flash) standing out of the base's back
    (outlines in the back's picture, seen from behind); the light window on the lid's outside (its spun ring and frosted
    window, as lid_outside draws them); the earpiece's slot in the pane (pebble.earpiece); the USB-C receptacle in the
    base's free end (pebble.port)."""
    vo = next(v for v in skin['views'] if v['id'] == skin['hinge']['open'])
    g, turn = vo['glass'], AXIS_O + AXIS_C
    px, py, below, inset = PANE
    pb = g[1] + g[3] + below
    inlays = [{'slab': 'lid', 'face': 'back', 'outline': B.soft_rect(px, turn - pb, W - px, turn - py, B.CORNER[0] - inset, B.CORNER[1]), 'material': 'glass'}]
    cx, cy, r = LENS
    camera = {'id': 'camera', 'look': 'back', 'at': [cx, cy], 'r': r, 'outline': sign_path(cx, cy, r, r * .846), 'proud': CAMERA_PROUD,
              'lens': {'r': round(r * .56, 4), 'bevel': 1.5, 'depth': LENS_DEPTH}}
    fw, fh = 12, 4.6
    flash = {'id': 'flash', 'look': 'back', 'at': list(FLASH), 'size': [fw, fh], 'outline': round_rect_path(FLASH[0] - fw / 2, FLASH[1] - fh / 2, fw, fh, fh / 2),
             'proud': FLASH_PROUD, 'material': 'frost'}
    lamp = {'id': 'lamp', 'look': 'front', 'slab': 'lid', 'at': list(LAMP), 'r': LAMP_RING, 'outline': circle_path(LAMP[0], LAMP[1], LAMP_RING),
            'window': LAMP_WINDOW, 'proud': LAMP_PROUD, 'ring': 'pin', 'material': 'jewel', 'cut': 'jewel'}
    lamp.update(JEWEL)
    ex, ey, ew, eh = B.earpiece(py)
    ear = {'id': 'earpiece', 'look': 'inner', 'slab': 'lid', 'outline': round_rect_path(ex, turn - ey - eh, ew, eh, eh / 2), 'depth': EAR_DEPTH,
           'edge': EAR_EDGE, 'material': 'mesh', 'wall': 'mesh'}
    k = skin['body3d']['px_per_mm']
    usb = {'id': 'usb_c', 'side': 'bottom', 'slab': 'base', 'x': [round(W / 2 - USB_C[0] * k / 2, 3), round(W / 2 + USB_C[0] * k / 2, 3)],
           'z': [round(USB_Z - USB_C[1] / 2, 3), round(USB_Z + USB_C[1] / 2, 3)], 'size': list(USB_C), 'depth': USB_DEPTH,
           'shell': B.USB_SHELL, 'tongue': list(B.USB_TONGUE), 'material': 'steel', 'inside': 'tongue'}
    return inlays, [camera, flash, lamp, ear, usb]


class Depth:
    """The thickness numbers of body3d, in picture px (z from the closed phone's front face, the lid's outside)."""
    def __init__(self, skin):
        b = skin['body3d']
        k = b['px_per_mm']
        s = {x['id']: x for x in b['slabs']}
        self.k = k
        self.th = b['thickness'] * k
        self.zl = s['lid']['z'][1] * k                  # the lid's inner face
        self.zb = s['base']['z'][0] * k                 # the base's front face
        self.za = b['hinge']['pivot'][2] * k            # the hinge axis
        self.lid_part = s['lid']['bands'][0]['z'][1] * k                       # outer cover | inner cover
        self.p1, self.p2 = (x['z'][1] * k for x in s['base']['bands'][:2])     # front cover | carrier | rear shell
        self.rf = s['lid']['edges']['front']['radius'] * k
        self.ri = s['lid']['edges']['back']['radius'] * k
        self.band = s['lid']['edges']['front']['chamfer'] * k
        self.rb = s['base']['edges']['front']['radius'] * k
        self.rr = s['base']['edges']['back']['radius'] * k
        self.angle = b['hinge']['angle'][1]


def top_view(skin, which):
    """The picture of the closed or open view (skin.json views)."""
    return next(v for v in skin['views'] if v['id'] == skin['hinge'][which])['image']


def check_body3d(skin):
    """body3d and hinge in skin.json describe these drawings: their numbers must be the ones drawn here."""
    b = skin['body3d']
    y0, y1 = closed_half()
    slabs = {s['id']: s for s in b['slabs']}
    for k in ('lid', 'base'):
        if slabs[k]['outline'] != half(y0, y1, True):
            raise SystemExit('skin.json body3d: the outline of %s is not the drawn one; it is\n%s' % (k, half(y0, y1, True)))
    hg, top = b['hinge'], skin['hinge']
    za = (slabs['lid']['z'][1] + slabs['base']['z'][0]) / 2
    want = {'pivot': [W / 2, AXIS_C, za], 'radius': round(R / b['px_per_mm'], 2),
            'barrel': BARREL, 'knuckles': KNUCKLES}
    got = {'pivot': hg['pivot'], 'radius': hg['radius'], 'barrel': tuple(hg['barrel']['x']),
           'knuckles': tuple(tuple(k['x']) for k in hg['knuckles'])}
    for k, v in want.items():
        if (list(v) if k == 'pivot' else v) != got[k]:
            raise SystemExit('skin.json body3d hinge: %s is %s; the drawings have %s' % (k, got[k], v))
    vs = {v['id']: v['size'] for v in skin['views']}
    if (top['axis_y'], top['offset'], top['open_deg'], vs[top['open']][1] - vs[top['closed']][1]) != (AXIS_O, OFFSET, hg['angle'][1], OFFSET):
        raise SystemExit('skin.json hinge: axis_y, offset and open_deg must be %s, %s and the open angle of body3d, and the open '
                         'picture %s taller than the closed one' % (AXIS_O, OFFSET, OFFSET))
    wells, caps, grooves = front3d(skin)
    vo = next(v for v in skin['views'] if v['id'] == top['open'])
    ids = B._ids[0]
    drawn = front(vo, 'base')
    B._ids[0] = ids                                    # the pictures drawn after this keep their ids
    for d in grooves:
        if 'd="%s"' % d not in drawn:
            raise SystemExit('skin.json body3d: the key field is not cut as its caps are (front3d() looks for\n%s\nin the '
                             'drawing): make the caps follow the drawn grooves' % d)
    inlays, features = outside3d(skin)
    for k, v in (('wells', wells), ('caps', caps), ('inlays', inlays)):
        if b.get(k) != v:
            raise SystemExit('skin.json body3d: %s are not the drawn ones; they are\n%s' % (k, '\n'.join(json.dumps(x) for x in v)))
    have = {f['id']: f for f in b.get('features', [])}
    for f in features:
        if have.get(f['id']) != f:
            raise SystemExit('skin.json body3d: the feature %s is not the drawn one; it is\n%s' % (f['id'], json.dumps(f)))
    # the lid's outside (Ripple): its pictures and finishes, as drawn here
    lid, base = slabs['lid']['materials'], slabs['base']['materials']
    want = {'front': 'closed.albedo.svg', 'front_2d': top_view(skin, 'closed'), 'back': 'lid.svg', 'side': 'lacquer', 'front_finish': FINISH}
    if lid != want:
        raise SystemExit('skin.json body3d: the lid\'s materials are not the drawn ones; they are\n%s' % json.dumps(want))
    if base.get('back_material', 'shell') != 'shell':
        raise SystemExit('skin.json body3d: the base\'s back is the soft-touch shell, as its rear band: no "back_material"')
    for v in B.PALETTES:
        m = b['materials'][v]
        got = tuple(m.get(k, {}).get('colour') for k in ('lacquer', 'pin', 'polish', 'jewel'))
        if got != (B.PALETTES[v]['body'], METALS[v][1], METALS[v][1], WINDOW):
            raise SystemExit('skin.json body3d: the colours of the lid\'s outside in %s are %s; the drawings have %s'
                             % (v, got, (B.PALETTES[v]['body'], METALS[v][1], METALS[v][1], WINDOW)))
        if m['pin'].get('brush') != 'radial':
            raise SystemExit('skin.json body3d: the pinstripes (pin) are spun: "brush": "radial"')
    # the side keys and the receptacle sit in the middle of the base's carrier band, as the side pictures draw them
    carrier = slabs['base']['bands'][1]['z']
    zc, k = (carrier[0] + carrier[1]) / 2, b['px_per_mm']
    if abs(zc - USB_Z) > 1e-9:
        raise SystemExit('draw.py: USB_Z is %s; the middle of the carrier band is %s' % (USB_Z, zc))
    for key in b.get('keys', []):
        h = (ROCKER_H if key['key'].startswith('vol') else SHUTTER_H) / k
        if key['z'] != [round(zc - h, 2), round(zc + h, 2)]:
            raise SystemExit('skin.json body3d: the side key %s is at z %s; the drawing has %s'
                             % (key['key'], key['z'], [round(zc - h, 2), round(zc + h, 2)]))
    for v in B.PALETTES:
        m = b['materials'][v]
        if (m['shell']['colour'], m['carrier']['colour'], m['rubber']['colour']) != (
                B.PALETTES[v]['body'], B.PALETTES[v]['back'], B.PALETTES[v]['groove']):
            raise SystemExit('skin.json body3d: the colours of %s are not those of pebble.py' % v)


def rear(y_off, D):
    """The base seen from behind (closed picture coordinates, lower by y_off): the rear shell, the cover's seams, the
    camera and flash, the engraved name, the loudspeaker, the notch and the eyelet; the knuckles above it."""
    x0, x1 = SIDES
    y0, y1 = (y + y_off for y in closed_half())
    path = half(y0, y1, True)
    out = [knuckles(AXIS_C + y_off), '<path d="%s" fill="%s"/>' % (path, B.P['body'])]
    cid = B.uid('rear')
    out.append('<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)">%s</g>'
               % (cid, path, cid, B.cut('M0 %gH%d M0 %gH%d' % (SEAMS[0] + y_off, W, SEAMS[1] + y_off, W))))
    out.append(B.notch(NOTCH_X, SEAMS[1] + y_off + .7))
    out.append(B.lens(LENS[0], LENS[1] + y_off, LENS[2]))
    out.append(B.flash(FLASH[0], FLASH[1] + y_off))
    out.append(B.engraved(lambda dy, c: L.wordmark(W / 2, NAME_Y + y_off + dy, 2.6, c)))
    out.append(B.grille(GRILLE[0], GRILLE[1] + y_off, GRILLE[2]))
    out.append(B.hole(EYELET[0], EYELET[1] + y_off, 4.4, 2.4))
    return out


def extra_defs():
    return ('<filter id="rim" x="-5%" y="-5%" width="110%" height="110%"><feDropShadow dx="0" dy="0" stdDeviation=".8" '
            'flood-color="#000" flood-opacity=".42"/></filter>')


def draw_back(skin, part):
    """back.svg (closed); back_open.svg (open, the lid opened flat, seen from behind); the layer rear.svg (the base alone,
    open picture)."""
    views = {v['id']: v for v in skin['views']}
    w, h = views[skin['hinge']['closed' if part == 'closed' else 'open']]['size']
    D = Depth(skin)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">' % (w, h, w, h),
           B.defs().replace('</defs>', flip_defs() + extra_defs() + B.outside_defs() + '</defs>')]
    if part == 'closed':
        out.append(barrel(AXIS_C))
        out += rear(0, D)
    else:
        out += rear(OFFSET, D)
        if part == 'open':
            # the lid seen from behind: its outside, turned over the axis and seen from behind (closed (x, y) -> (W - x,
            # AXIS_O + AXIS_C - y)), so the light window is near the hinge end and the name upside down near the free end
            y0, y1 = lid_open()
            mirror = lambda p: (W - p[0], AXIS_O + AXIS_C - p[1])
            out += lid_outside(half(y0, y1, False), y0, y1, mirror(LAMP), mirror((W / 2, NAME_OUT)), turned=True, kind='albedo')
            out.append(barrel(AXIS_O))
    out.append('</svg>')
    return '\n'.join(x for x in out if x) + '\n'


class Side:
    """A side picture: an orthographic view of one side, exactly body length by thickness. s runs along the side (y of the
    closed picture less 4 for left and right, x less 4 for top and bottom), z from the closed front face. left: the front
    face is at the right of the picture; right: at the left; top: at the bottom; bottom: at the top (third-angle)."""
    def __init__(self, look, length, D):
        self.look, self.D = look, D
        self.size = (D.th, length) if look in ('left', 'right') else (length, D.th)
        self.defs = []

    def pt(self, s, z):
        th = self.D.th
        return {'left': (th - z, s), 'right': (z, s), 'top': (s, th - z), 'bottom': (s, z)}[self.look]

    def poly(self, pts):
        """A closed outline through (s, z, r) corners, each corner rounded by r."""
        n, d = len(pts), []
        for i, (s, z, r) in enumerate(pts):
            p, q = pts[i - 1], pts[(i + 1) % n]

            def toward(o, dist):
                ds, dz = o[0] - s, o[1] - z
                m = (ds * ds + dz * dz) ** .5
                return (s + ds / m * dist, z + dz / m * dist)
            a, b = toward(p, r), toward(q, r)
            c1 = (a[0] + (s - a[0]) * .552, a[1] + (z - a[1]) * .552)
            c2 = (b[0] + (s - b[0]) * .552, b[1] + (z - b[1]) * .552)
            f = lambda u: '%.2f %.2f' % self.pt(*u)
            d.append(('M%s' if i == 0 else 'L%s') % f(a))
            if r:
                d.append('C%s %s %s' % (f(c1), f(c2), f(b)))
        return ''.join(d) + 'Z'

    def rect(self, s0, s1, z0, z1, fill, extra=''):
        x, y, w, h = self.box(s0, s1, z0, z1)
        return '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="%s" %s/>' % (x, y, w, h, fill, extra)

    def box(self, s0, s1, z0, z1):
        (xa, ya), (xb, yb) = self.pt(s0, z0), self.pt(s1, z1)
        return min(xa, xb), min(ya, yb), abs(xb - xa), abs(yb - ya)

    def grad(self, a, b, stops):
        """A gradient from (s, z) a to b; stops: (t, colour, opacity)."""
        gid = B.uid('sg')
        (x1, y1), (x2, y2) = self.pt(*a), self.pt(*b)
        self.defs.append('<linearGradient id="%s" gradientUnits="userSpaceOnUse" x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f">%s'
                         '</linearGradient>' % (gid, x1, y1, x2, y2, ''.join(
                             '<stop offset="%.4f" stop-color="%s" stop-opacity="%g"/>' % (max(0, min(1, t)), c, o) for t, c, o in stops)))
        return 'url(#%s)' % gid

    def ends(self, s0, s1, e0, e1, z0, z1, turned=False):
        """The plan corners at the two ends of a part: the wall turns away; towards the upper end (s0, or s1 when turned)
        it turns to the light, towards the other end into shade."""
        n = s1 - s0
        lit = .14 if B.P['lit'] else .3
        if turned:
            stops = [(0, '#000', .26), (e0 / n * .9, '#000', 0), (1 - e1 / n * .9, '#fff', 0), (1, '#fff', lit)]
        else:
            stops = [(0, '#fff', lit), (e0 / n * .9, '#fff', 0), (1 - e1 / n * .9, '#000', 0), (1, '#000', .26)]
        return self.rect(s0, s1, z0, z1, self.grad((s0, z0), (s1, z0), stops))

    def zshade(self, s0, s1, z0, z1, a_lit, b_dark, lit_to, dark_from, flip=False):
        """Across the thickness: the edge at z0 catches the light (a_lit), the edge at z1 turns into shade (b_dark); flip
        exchanges the two (a part turned over)."""
        n = z1 - z0
        if flip:
            stops = [(0, '#000', b_dark), ((lit_to - z0) / n, '#000', 0), ((dark_from - z0) / n, '#fff', 0), (1, '#fff', a_lit)]
        else:
            stops = [(0, '#fff', a_lit), ((lit_to - z0) / n, '#fff', 0), ((dark_from - z0) / n, '#000', 0), (1, '#000', b_dark)]
        return self.rect(s0, s1, z0, z1, self.grad((s0, z0), (s0, z1), stops))

    def line(self, a, b, colour='#000', opacity=.38, width=.5):
        return '<path d="M%.2f %.2fL%.2f %.2f" stroke="%s" stroke-opacity="%g" stroke-width="%g" fill="none"/>' % (
            self.pt(*a) + self.pt(*b) + (colour, opacity, width))


def satin(S, s0, s1, z0, z1, length):
    return S.rect(s0, s1, z0, z1, S.grad((0, 0), (length, 0), [(0, B.P['band'][0], 1), (1, B.P['band'][1], 1)]))


def lid_wall(S, D, turned=False):
    """The lid's side wall (left or right), closed place: one shell, a part line 2 mm from the outer face, the satin
    band on both edges."""
    sh, sf = AXIS_C + R - 4, AXIS_C + R + HALF - 4
    path = S.poly([(sh, 0, D.rf), (sh, D.zl, D.ri), (sf, D.zl, D.ri), (sf, 0, D.rf)])
    cid = B.uid('sidel')
    out = ['<path d="%s" fill="%s"/>' % (path, B.P['body']),
           '<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)">' % (cid, path, cid),
           S.line((sh, D.lid_part), (sf, D.lid_part)),
           satin(S, sh, sf, 0, D.band, S.size[1] if S.look in ('left', 'right') else S.size[0]),
           satin(S, sh, sf, D.zl - D.band, D.zl, S.size[1] if S.look in ('left', 'right') else S.size[0]),
           '</g><path d="%s" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".55"/>' % path]
    return out


def base_wall(S, D, look):
    """The base's side wall: front cover, carrier band, rear shell (the cover's seams across it), and the side's parts."""
    sh, sf = AXIS_C + R - 4, AXIS_C + R + HALF - 4
    zb, p1, p2, th = D.zb, D.p1, D.p2, D.th
    path = S.poly([(sh, zb, D.rb), (sf, zb, D.rb), (sf, th, D.rr), (sh, th, D.rr)])
    cid = B.uid('sideb')
    out = ['<path d="%s" fill="%s"/>' % (path, B.P['body']),
           '<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)">' % (cid, path, cid),
           S.rect(sh, sf, p1, p2, B.P['back']),
           S.line((sh, p1), (sf, p1)), S.line((sh, p2), (sf, p2)),
           satin(S, sh, sf, zb, zb + D.band, S.size[1])]
    for sy in SEAMS:
        out.append('<path d="M%.2f %.2fL%.2f %.2f" stroke="%s" stroke-width=".9" fill="none"/>'
                   % (S.pt(sy - 4, p2) + S.pt(sy - 4, th) + (B.P['groove'],)))
    zc = (p1 + p2) / 2
    if look == 'right':
        out.append(B.side_key(*S.box(ROCKER[0] - 4, ROCKER[1] - 4, zc - ROCKER_H, zc + ROCKER_H)))
        m = (ROCKER[0] + ROCKER[1]) / 2 - 4
        out.append(B.cut('M%.2f %.2fL%.2f %.2f' % (S.pt(m, zc - 3) + S.pt(m, zc + 3))))
        out.append(B.side_key(*S.box(SHUTTER[0] - 4, SHUTTER[1] - 4, zc - SHUTTER_H, zc + SHUTTER_H), metal=True))
    else:
        x, y, w, h = S.box(CARD[0] - 4, CARD[1] - 4, p1 + 2.2, p2 - 2.2)
        out.append(B.door(x, y, w, h))
    out.append('</g><path d="%s" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".55"/>' % path)
    return out


def lid_web(S, D):
    """The web that joins the barrel to the lid's hinge end, seen from the side: set back behind the knuckle, in shade.
    It turns with the lid."""
    s, z, r = AXIS_C - 4, D.za, R
    sh = AXIS_C + R - 4
    return [S.rect(s, sh + .5, z - r * .8, D.zl, B.P['body']), S.rect(s, sh + .5, z - r * .8, D.zl, '#000', 'opacity=".45"')]


def hinge_end(S, D):
    """A hinge end seen from the side: the knuckle's round end in the body colour, its web down to the base's hinge end,
    and the cap of the hinge pin."""
    s, z, r = AXIS_C - 4, D.za, R
    sh = AXIS_C + R - 4
    cx, cy = S.pt(s, z)
    out = [S.rect(s, sh + .5, D.zb, z + r, B.P['body'], 'filter="url(#seat)"'),                                      # the knuckle's web
           S.zshade(s, sh + .5, D.zb, z + r, .1, .25, D.zb + 1, z + r - 1),
           '<circle cx="%.2f" cy="%.2f" r="%g" fill="%s" filter="url(#seat)"/>' % (cx, cy, r, B.P['body']),
           '<circle cx="%.2f" cy="%.2f" r="%g" fill="url(#disc)"/>' % (cx, cy, r),
           '<circle cx="%.2f" cy="%.2f" r="%g" fill="none" stroke="#fff" stroke-opacity="%g" stroke-width=".7"/>'
           % (cx, cy - .35, r - KNUCKLE_ROUND * .5, .12 if B.P['lit'] else .4),
           '<circle cx="%.2f" cy="%.2f" r="%g" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".5"/>' % (cx, cy, r),
           '<circle cx="%.2f" cy="%.2f" r="%g" fill="#000" opacity=".35"/>' % (cx, cy + .3, PIN + .45),
           '<circle cx="%.2f" cy="%.2f" r="%g" fill="url(#coin)"/>' % (cx, cy, PIN),
           '<circle cx="%.2f" cy="%.2f" r="%g" fill="none" stroke="#000" stroke-opacity=".3" stroke-width=".3"/>' % (cx, cy, PIN * .45)]
    return out


def open_place(D, look):
    """The open side picture: the rotation of the lid about the axis (SVG transform) and the translation that puts the
    whole in the picture, and its size."""
    a = D.angle if look == 'right' else -D.angle
    ax = D.za if look == 'right' else D.th - D.za
    ay = AXIS_C - 4
    sh, sf = AXIS_C + R - 4, AXIS_C + R + HALF - 4
    zs = (0, D.zl) if look == 'right' else (D.th - D.zl, D.th)
    pts = []
    for x in zs:
        for y in (sh, sf):
            dx, dy = x - ax, y - ay
            t = math.radians(a)
            pts.append((ax + dx * math.cos(t) - dy * math.sin(t), ay + dx * math.sin(t) + dy * math.cos(t)))
    pts += [(0, 0), (D.th, sf)]
    tx, ty = -math.floor(min(p[0] for p in pts)), -math.floor(min(p[1] for p in pts))
    w, h = math.ceil(max(p[0] for p in pts)) + tx, math.ceil(max(p[1] for p in pts)) + ty
    return 'rotate(%g %.3f %g)' % (a, ax, ay), (tx, ty), (w, h)


def side(skin, look, opened=False):
    """One side picture: left or right (closed, or open at the open angle), top (the hinge end) or bottom (the free ends)."""
    D = Depth(skin)
    lit = B.P['lit']
    length = HALF + 2 * R if look in ('left', 'right') else SIDES[1] - SIDES[0]
    S = Side(look, length, D)
    out = []
    if look in ('left', 'right'):
        sh, sf = AXIS_C + R - 4, AXIS_C + R + HALF - 4
        out += base_wall(S, D, look)
        if not opened:
            out.append(S.rect(sh, sf, D.zl - .2, D.zb + .2, '#000', 'opacity=".78"'))     # the gap between the halves
            out += lid_web(S, D) + lid_wall(S, D)
            out += hinge_end(S, D)
        else:
            turn, (tx, ty), size = open_place(D, look)
            out = (['<g transform="translate(%d %d)">' % (tx, ty)] + out
                   + ['<g transform="%s">' % turn] + lid_web(S, D) + lid_wall(S, D, turned=True) + ['</g>'] + hinge_end(S, D) + ['</g>'])
            S.size = size
    elif look == 'top':                                 # the hinge end: the halves' ends set back, the hinge in front
        zl, zb, th, za = D.zl, D.zb, D.th, D.za
        lid = S.poly([(0, 0, D.rf), (length, 0, D.rf), (length, zl, D.ri), (0, zl, D.ri)])
        base = S.poly([(0, zb, D.rb), (length, zb, D.rb), (length, th, D.rr), (0, th, D.rr)])
        for path, z0, z1, parts in ((lid, 0, zl, (D.lid_part,)), (base, zb, th, (D.p1, D.p2))):
            cid = B.uid('topend')
            out.append('<path d="%s" fill="%s"/>' % (path, B.P['body']))
            out.append('<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)">' % (cid, path, cid))
            if z0:
                out.append(S.rect(0, length, D.p1, D.p2, B.P['back']))
            out += [S.line((0, p), (length, p)) for p in parts]
            out.append('</g><path d="%s" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".55"/>' % path)
        out.append(S.rect(2, length - 2, zl - .2, zb + .2, '#000', 'opacity=".78"'))
        # the knuckles and the barrel: one cylinder seen side on, lit on its front, in shade towards the back
        shade = [(0, '#fff', .3 if not lit else .14), (.38, '#fff', 0), (.75, '#000', 0), (1, '#000', .35)]
        for xa, xb in KNUCKLES:
            s0, s1 = xa - 4, xb - 4
            ro, ri = (KNUCKLE_ROUND, .6) if xa == SIDES[0] else (.6, KNUCKLE_ROUND)
            k = S.poly([(s0, za - R, ro), (s1, za - R, ri), (s1, za + R, ri), (s0, za + R, ro)])
            out.append('<path d="%s" fill="%s" filter="url(#seat)"/>' % (k, B.P['body']))
            out.append('<path d="%s" fill="%s"/>' % (k, S.grad((0, za - R), (0, za + R), shade)))
            out.append('<path d="%s" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".5"/>' % k)
        s0, s1 = BARREL[0] - 4, BARREL[1] - 4
        for x in (KNUCKLES[0][1] - 4 + .25, KNUCKLES[1][0] - 4 - .25):
            out.append(S.rect(x - .9, x + .9, za - R + 1, za + R - 1, '#000', 'opacity=".72"'))
        bar = S.poly([(s0, za - R, .8), (s1, za - R, .8), (s1, za + R, .8), (s0, za + R, .8)])
        a, b = B.P['band']
        out.append('<path d="%s" fill="%s" stroke="#000" stroke-opacity=".3" stroke-width=".5"/>'
                   % (bar, S.grad((0, za - R), (0, za + R), [(0, b, 1), (.3, a, 1), (.78, b, 1), (1, b, 1)])))
        out.append(S.line((s0 + 3, za - R * .45), (s1 - 3, za - R * .45), '#fff', .6, .8))
    else:                                               # bottom: the free ends; the port and the lanyard slot in the base's
        zl, zb, th = D.zl, D.zb, D.th
        lid = S.poly([(0, 0, D.rf), (length, 0, D.rf), (length, zl, D.ri), (0, zl, D.ri)])
        base = S.poly([(0, zb, D.rb), (length, zb, D.rb), (length, th, D.rr), (0, th, D.rr)])
        out.append(S.rect(2, length - 2, zl - .2, zb + .2, '#000', 'opacity=".78"'))
        for path, z0, z1 in ((lid, 0, zl), (base, zb, th)):
            cid = B.uid('bot')
            out.append('<path d="%s" fill="%s"/>' % (path, B.P['body']))
            out.append('<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)">' % (cid, path, cid))
            if z0:
                out.append(S.rect(0, length, D.p1, D.p2, B.P['back']))
                out += [S.line((0, D.p1), (length, D.p1)), S.line((0, D.p2), (length, D.p2))]
                out.append(satin(S, 0, length, z0, z0 + D.band, length))
            else:
                out.append(S.line((0, D.lid_part), (length, D.lid_part)))
                out.append(satin(S, 0, length, 0, D.band, length))
                out.append(satin(S, 0, length, zl - D.band, zl, length))
            if z0:
                out.append(B.port(length / 2, USB_Z * D.k, USB_C[0] * D.k, USB_C[1] * D.k, D.k))
                out.append(B.hole(W - EYELET[0] - 4, th - 4.6, 4.4, 2.4))     # under the eyelet on the back
            out.append('</g><path d="%s" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".55"/>' % path)
    w, h = S.size
    head = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %g %g" width="%g" height="%g">' % (w, h, w, h),
            B.defs().replace('</defs>', flip_defs() + extra_defs() + B.outside_defs() + ''.join(S.defs) + '</defs>')]
    return '\n'.join(head + [x for x in out if x] + ['</svg>']) + '\n'


def outside_jobs(skin):
    """(file name, size, drawing) for every picture of body3d: the back closed and open, the base's layer, the sides."""
    jobs = []
    for v in skin['body3d']['views']:
        if v['look'] == 'back':
            part = 'rear' if v.get('layer') == 'base' else v.get('state', 'closed')
            jobs.append((v, lambda part=part: draw_back(skin, part)))
        else:
            jobs.append((v, lambda look=v['look'], opened=v.get('state') == 'open': side(skin, look, opened)))
    return jobs


def size_of(svg):
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    return [float(m.group(1)), float(m.group(2))]


def main():
    skin = json.load(open(os.path.join(HERE, 'skin.json'), encoding='utf-8'))
    views = {v['id']: v for v in skin['views']}
    hg = skin['hinge']
    jobs = [(views[hg['closed']]['image'], views[hg['closed']], 'closed'), (views[hg['open']]['image'], views[hg['open']], 'open')]
    jobs += [(hg[p], views[hg['open']], p) for p in ('base', 'lid', 'barrel')]
    lid = next(s for s in skin['body3d']['slabs'] if s['id'] == skin['body3d']['hinge']['moves'])['materials']
    jobs += [(lid['front'], views[hg['closed']], 'albedo'), (lid['front_finish']['mask'], views[hg['closed']], 'mask'),
             (lid['front_finish']['relief'], views[hg['closed']], 'relief')]
    check_body3d(skin)
    for variant in B.PALETTES:
        B.use(variant)
        colour = '' if variant == B.DEFAULT else '.' + variant
        for image, view, part in jobs:
            name = image[:-4] + colour + '.svg'
            with open(os.path.join(HERE, name), 'w', encoding='utf-8') as f:
                f.write(front(view, 'hinge' if part == 'barrel' else part))
            print('wrote', name)
        for v, make in outside_jobs(skin):
            name = v['image'][:-4] + colour + '.svg'
            svg = make()
            if [round(x, 2) for x in size_of(svg)] != [round(x, 2) for x in v['size']]:
                raise SystemExit('skin.json body3d: the view %s has size %s; the picture is %s' % (v['id'], v['size'], size_of(svg)))
            with open(os.path.join(HERE, name), 'w', encoding='utf-8') as f:
                f.write(svg)
            print('wrote', name)
    B.use(B.DEFAULT)


if __name__ == '__main__':
    main()
