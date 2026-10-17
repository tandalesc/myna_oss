"""The parts of the Myna P2 family (slider, candybar, flip), drawn for this project. Standard library only.

Every P2 body is built from the same parts, so the three models read as one family:
  - a matte soft-touch body with long smooth corners, a shade darker where the back half shows;
  - a thin satin-metal band that traces the face (the one bright line of the object);
  - one dark glass pane: earpiece slit, screen, the name printed under the screen; a faint sheen, its top edge caught;
  - a control plate in the body colour, cut by grooves into keys, each key gently domed;
  - the jewel: a spun-metal coin, a solid circle with a flat cut at its top and bottom, as the navigation key, with four
    small engraved chevrons for its directions;
  - a keypad of domed keys with satin ridges between the rows; on the dark colours the legends are printed warm white;
  - on the flip, plate and number keys are one key field: one surface, cut by grooves into domed keys.
The same file is in each P2 skin folder (with lettering.py). Original work of the project (MIT, as the project).
"""
import importlib.util
import os

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('myna_lettering', os.path.join(_here, 'lettering.py'))
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

W = 176
# Radii relate as on moulded parts. The face (upper slab) has the body corner; the back half is the same outline grown by
# WALL; the pane is the face outline shrunk by its inset (same curve, smaller reach), so it is concentric with the face.
# Inner parts (control plate, keypad sheet) share one smaller corner; the tray round the sheet is that corner grown by
# its wall; a key's radius is the sheet's corner less its inset.
CORNER = (40, 0.2)
WALL = 1.5
INNER = (12, 0.3)
TRAY = 2.2
KEY_R = 6
GROOVE = 1.3
PAD_KEYS = ('1', '2', '3', '4', '5', '6', '7', '8', '9', 'star', '0', 'hash')
LETTERS = {'1': '', '2': 'ABC', '3': 'DEF', '4': 'GHI', '5': 'JKL', '6': 'MNO', '7': 'PQRS', '8': 'TUV', '9': 'WXYZ',
           '0': '+', 'star': '', 'hash': ''}
FIGURE = {'star': '*', 'hash': '#'}

#   body/back   the face, the back half          sheet/key   keypad sheet, key faces      groove  cuts between keys
#   ink         legends; lit = drawn as light    coin        the spun metal (light, dark) band    satin band (light, dark)
#   pane        the glass                        print       the name on the pane         slot    microphone, earpiece
#   edge        fall-off of the matte shape      dome        (top light, bottom shade) opacities of a domed key
PALETTES = {
    'stone': {'body': '#d5d0c6', 'back': '#b2ab9e', 'sheet': '#c9c3b7', 'key': '#d8d3ca', 'groove': '#9d968a',
              'ink': '#47423b', 'lit': False, 'coin': ('#fbfaf8', '#aaa69e'), 'band': ('#fbfaf7', '#a39f97'),
              'pane': '#141517', 'print': '#77736c', 'slot': '#3a3732', 'edge': .07, 'dome': (.35, .07), 'swatch': '#d5d0c6'},
    'ink':   {'body': '#2c2f35', 'back': '#1b1d21', 'sheet': '#22252a', 'key': '#2f3239', 'groove': '#121316',
              'ink': '#fff3e2', 'lit': True, 'coin': ('#f1f2f4', '#868b93'), 'band': ('#e4e6e9', '#6a6f77'),
              'pane': '#0d0e10', 'print': '#666a72', 'slot': '#08090a', 'edge': .18, 'dome': (.07, .22), 'swatch': '#2c2f35'},
    'ember': {'body': '#a8462f', 'back': '#7a3120', 'sheet': '#953c27', 'key': '#ad4b34', 'groove': '#64261a',
              'ink': '#fff1e3', 'lit': True, 'coin': ('#fbf4ec', '#b3a291'), 'band': ('#f7ece0', '#a8937c'),
              'pane': '#130e0d', 'print': '#7c6a63', 'slot': '#3e180f', 'edge': .14, 'dome': (.12, .16), 'swatch': '#a8462f'},
}
LABELS = {'stone': 'Stone', 'ink': 'Ink', 'ember': 'Ember'}
DEFAULT = 'stone'
P = dict(PALETTES[DEFAULT])


def use(name):
    P.clear()
    P.update(PALETTES[name])


def soft_rect(x0, y0, x1, y1, e, k, bottom=None):
    """A rectangle with soft corners: each reaches e along both edges, its controls k * e from the corner. bottom = (e, k)
    for the two lower corners if they differ."""
    eb, kb = bottom or (e, k)
    c, cb = k * e, kb * eb
    return ('M%g %g H%g C%g %g %g %g %g %g V%g C%g %g %g %g %g %g H%g C%g %g %g %g %g %g V%g C%g %g %g %g %g %g Z'
            % (x0 + e, y0, x1 - e, x1 - c, y0, x1, y0 + c, x1, y0 + e, y1 - eb, x1, y1 - cb, x1 - cb, y1, x1 - eb, y1,
               x0 + eb, x0 + cb, y1, x0, y1 - cb, x0, y1 - eb, y0 + e, x0, y0 + c, x0 + c, y0, x0 + e, y0))


def rr(x, y, w, h, r, fill, extra=''):
    return '<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="%s" %s/>' % (x, y, w, h, r, fill, extra)


def mid(r):
    return r[0] + r[2] / 2, r[1] + r[3] / 2


def defs():
    e = P['edge']
    top, shade = P['dome']
    return ('<defs>'
            '<linearGradient id="fall" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#000" stop-opacity="%g"/>'
            '<stop offset=".1" stop-color="#000" stop-opacity="0"/><stop offset=".9" stop-color="#000" stop-opacity="0"/>'
            '<stop offset="1" stop-color="#000" stop-opacity="%g"/></linearGradient>'
            '<linearGradient id="underside" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity="0"/>'
            '<stop offset="1" stop-color="#000" stop-opacity=".22"/></linearGradient>'
            '<linearGradient id="wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity=".38"/>'
            '<stop offset="1" stop-color="#000" stop-opacity="0"/></linearGradient>'
            '<filter id="cast" x="-8%%" y="-5%%" width="116%%" height="115%%"><feDropShadow dx="0" dy="2.2" stdDeviation="1.8" '
            'flood-color="#000" flood-opacity=".38"/></filter>'
            '<filter id="seat" x="-20%%" y="-20%%" width="140%%" height="140%%"><feDropShadow dx="0" dy=".8" stdDeviation=".6" '
            'flood-color="#000" flood-opacity=".35"/></filter>'
            '<linearGradient id="satin" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient>'
            '<linearGradient id="dome" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="%g"/>'
            '<stop offset=".3" stop-color="#fff" stop-opacity="0"/><stop offset=".75" stop-color="#000" stop-opacity="0"/>'
            '<stop offset="1" stop-color="#000" stop-opacity="%g"/></linearGradient>'
            '<radialGradient id="coin" cx=".38" cy=".3" r=".85"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></radialGradient>'
            '<filter id="lift" x="-5%%" y="-5%%" width="110%%" height="110%%"><feDropShadow dx="0" dy="1.2" stdDeviation="1.1" '
            'flood-color="#000" flood-opacity=".3"/></filter>'
            '<filter id="glow" x="-50%%" y="-50%%" width="200%%" height="200%%"><feGaussianBlur stdDeviation=".9" result="b"/>'
            '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
            '</defs>' % (e, e, P['band'][0], P['band'][1], top, shade, P['coin'][0], P['coin'][1]))


def line(d, colour, width=GROOVE, extra=''):
    return '<path d="%s" fill="none" stroke="%s" stroke-width="%g" stroke-linecap="round" %s/>' % (d, colour, width, extra)


def cut(d, extra=''):
    """A groove: the dark cut and, just under it, the lit lower wall of the cut."""
    return (line(d, '#fff', .6, 'stroke-opacity="%g" transform="translate(0 .85)" %s' % (.18 if P['lit'] else .5, extra))
            + line(d, P['groove'], GROOVE, extra))


def legend(svg):
    """Legends: printed, sharp, on every colour (light ink on the dark ones)."""
    return svg


# ---- signs on the face keys
def handset(cx, cy, down=False):
    t = ' transform="rotate(180 %g %g)"' % (cx, cy) if down else ''
    return ('<path d="M%g %g C%g %g %g %g %g %g" fill="none" stroke="%s" stroke-width="1.7" stroke-linecap="round"%s/>'
            % (cx - 4, cy + 1.2, cx - 3, cy - 2.5, cx + 3, cy - 2.5, cx + 4, cy + 1.2, P['ink'], t))


def dots(cx, cy):
    return ''.join('<circle cx="%g" cy="%g" r=".85" fill="%s"/>' % (cx + dx, cy + dy, P['ink']) for dx in (-1.7, 1.7) for dy in (-1.7, 1.7))


def back_arrow(cx, cy):
    return line('M%g %g H%g M%g %g L%g %g L%g %g' % (cx + 3, cy, cx - 3, cx - 0.9, cy - 2.1, cx - 3.1, cy, cx - 0.9, cy + 2.1),
                P['ink'], 1, 'stroke-linejoin="round"')


def dash(cx, cy):
    return line('M%g %g H%g' % (cx - 3.5, cy, cx + 3.5), P['ink'], 1.2)


# ---- parts
def band(path, width=1.4):
    """The satin band along an outline: the one bright line of the object."""
    return '<path d="%s" fill="none" stroke="url(#satin)" stroke-width="%g"/>' % (path, width)


_ids = [0]


def uid(stem):
    _ids[0] += 1
    return '%s%d' % (stem, _ids[0])


def body(path, y0, y1, upper=False, fill=None):
    """A moulded part seen from the front: its top face, the fall-off where the face turns into the sides, a light where
    its upper edge turns, the shade of its lower wall, and a dark seam line round it. upper = the slab that lies over
    another part: it casts a shadow on it."""
    cid = uid('part')
    return ['<path d="%s" fill="%s" filter="url(#%s)"/>' % (path, fill or P['body'], 'cast' if upper else 'lift'),
            '<path d="%s" fill="url(#fall)"/>' % path,
            '<clipPath id="%s"><path d="%s"/></clipPath>' % (cid, path),
            '<g clip-path="url(#%s)"><path d="%s" fill="none" stroke="#fff" stroke-opacity="%g" stroke-width="1.6" '
            'transform="translate(0 .9)"/><rect x="0" y="%g" width="%d" height="3.2" fill="url(#underside)"/></g>'
            % (cid, path, .16 if P['lit'] else .55, y1 - 3.2, W),
            '<path d="%s" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".55"/>' % path]


EAR = (22, 2.2, 8)              # the earpiece's slit in the pane: width, height, and how far under the pane's top edge


def earpiece(py):
    """The earpiece's slit in a pane whose top edge is at py: (x, y, w, h), a stadium (its ends round)."""
    return W / 2 - EAR[0] / 2, py + EAR[2], EAR[0], EAR[1]


def pane(g, px, py, pb, corner=CORNER, inset=7.5, name=True):
    """The dark glass, set into the face: its corners are the face's corners less its inset (concentric), a fine dark seat
    round it, its top edge catching the light; flat glass, so no sheen. A slit for the earpiece, the screen, the name."""
    path = soft_rect(px, py, W - px, pb, corner[0] - inset, corner[1])
    ex, ey, ew, eh = earpiece(py)
    out = ['<path d="%s" fill="%s" stroke="#000" stroke-opacity=".55" stroke-width=".7"/>' % (path, P['pane']),
           '<path d="M%g %g H%g" stroke="#fff" stroke-opacity=".16" stroke-width=".7" stroke-linecap="round"/>' % (px + 26, py + .7, W - px - 26),
           rr(ex, ey, ew, eh, eh / 2, '#000', 'stroke="#2c2d30" stroke-width=".5"'),
           rr(g[0], g[1], g[2], g[3], 0.5, '#000')]
    if name:
        out.append(L.wordmark(W / 2, pb - 6.5, 2.7, P['print']))
    return out


def tray(x0, y0, x1, y1):
    """The recess the keypad sheet sits in: its floor in shadow, its upper wall dark, its lower wall lit."""
    t = soft_rect(x0 - TRAY, y0 - TRAY, x1 + TRAY, y1 + TRAY, INNER[0] + TRAY, INNER[1])
    cid = uid('tray')
    return ('<path d="%s" fill="%s"/><path d="%s" fill="#000" opacity=".3"/><clipPath id="%s"><path d="%s"/></clipPath>'
            '<g clip-path="url(#%s)"><rect x="0" y="%g" width="%d" height="4" fill="url(#wall)"/>'
            '<path d="%s" fill="none" stroke="#fff" stroke-opacity="%g" stroke-width="1" transform="translate(0 -.8)"/></g>'
            % (t, P['back'], t, cid, t, cid, y0 - TRAY, W, t, .1 if P['lit'] else .35))


def rails(x_left, x_right, y0, y1):
    """The two slide rails in their channels at the sides of the back half: visible only where the upper slab leaves the
    back half bare (when open, beside its rounded lower corners and in the gap above the keypad)."""
    out = ''
    for x in (x_left, x_right):
        out += (rr(x - 1.5, y0, 3, y1 - y0, 1.5, '#000', 'opacity=".45"')
                + '<path d="M%g %gV%g" stroke="url(#satin)" stroke-width="1.1"/>' % (x, y0 + 1.5, y1 - 1.5))
    return out


MARK_R = 19.2                   # the tips of the four direction marks on the coin, from its centre
MARK = (2.8, 1.9)               # a mark's half width and depth


def marks(cx, cy):
    """Four small chevrons engraved in the coin at up, down, left and right, pointing outwards, their tips on one circle
    concentric with the spun rings: well outside the centre (select) and inside the flat cuts. Each is a fine V-cut: a
    dark line and, just under it, the lit lower wall of the cut, the same on every colour (the coin is the same metal)."""
    w, d = MARK
    t = MARK_R
    v = ('M%g %gL%g %gL%g %g' % (cx - w, cy - t + d, cx, cy - t, cx + w, cy - t + d))           # up; the others turn it
    paths = ''.join('<path d="%s" transform="rotate(%d %g %g)"/>' % (v, a, cx, cy) for a in (0, 90, 180, 270))
    return ('<g fill="none" stroke-linecap="round" stroke-linejoin="round">'
            '<g stroke="#fff" stroke-opacity=".85" stroke-width=".8" transform="translate(0 .55)">%s</g>'
            '<g stroke="#2a2826" stroke-opacity=".7" stroke-width=".95">%s</g></g>' % (paths, paths))


def coin(cx, cy, r, h):
    """The jewel: a spun-metal disc with a flat cut at its top and bottom, fine concentric rings, and four engraved
    direction marks."""
    ring = ''.join('<circle cx="%g" cy="%g" r="%g" fill="none" stroke="%s" stroke-opacity="%g" stroke-width=".35"/>'
                   % (cx, cy, rr_, '#fff' if i % 2 else '#000', .35 if i % 2 else .07, ) for i, rr_ in enumerate(range(3, int(r), 2)))
    ring += marks(cx, cy)
    cid = 'coinclip%d' % int(cx * 10 + cy)
    shape = L.sign(cx, cy, r, 'url(#coin)', h / r)
    clip = '<clipPath id="%s">%s</clipPath>' % (cid, L.sign(cx, cy, r, '#000', h / r))
    return (clip + shape.replace('/>', ' stroke="%s" stroke-width=".6" filter="url(#seat)"/>' % P['groove'])
            + '<g clip-path="url(#%s)">%s<path d="M%g %g A%g %g 0 0 1 %g %g" fill="none" stroke="#fff" stroke-opacity=".7" '
            'stroke-width=".8"/></g>' % (cid, ring, cx - r * .62, cy - h + 1.2, r, r, cx + r * .2, cy - h + .3))


def plate(keys, pad=None):
    """The control plate: one surface cut by grooves into soft keys, call and end, activity and back, each key gently domed,
    the coin in an opening of its own shape in the middle. With pad (the twelve number keys, in rows under the plate), the
    same surface goes on down as one key field: the number keys are cells of it, domed like the plate's keys, cut apart by
    the same grooves and nothing else (the flip)."""
    names = ('soft_left', 'soft_right', 'call', 'end', 'activity', 'clear')
    rects = [keys[n] for n in names] + [pad[n] for n in PAD_KEYS] if pad else [keys[n] for n in names]
    x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    cx = mid(keys['select'])[0]
    top, bottom = keys['up'][1], keys['down'][1] + keys['down'][3]
    cy, h = (top + bottom) / 2, (bottom - top) / 2
    r = (keys['right'][0] + keys['right'][2] - keys['left'][0]) / 2
    ring = r + 3
    edge = soft_rect(x0, y0, x1, y1, *INNER)
    out = ['<clipPath id="plateclip"><path d="%s"/></clipPath>' % edge]
    opening = L.sign(cx, cy, ring, P['body'], (h + 3) / ring)
    out.append('<mask id="ringcut"><rect width="%d" height="900" fill="#fff"/>%s</mask>' % (W, opening.replace(P['body'], '#000')))
    # each key domed: a soft light at its top, a shade at its bottom, inside its own rectangle
    rows = [keys[n] for n in names] + [[keys['call'][0] + keys['call'][2], keys[n][1], keys['end'][0] - keys['call'][0] - keys['call'][2],
                                           keys[n][3]] for n in ('call', 'activity')]       # the plate between the columns
    if pad:
        rows += [pad[n] for n in PAD_KEYS]
    shade = ''.join('<rect x="%g" y="%g" width="%g" height="%g" fill="url(#dome)"/>' % tuple(r) for r in rows)
    out.append('<g clip-path="url(#plateclip)" mask="url(#ringcut)">%s</g>' % shade)
    out.append(cut(edge))
    ys, ya = keys['call'][1] - 1, keys['activity'][1] - 1
    cuts = 'M%g %gH%g M%g %gV%g M%g %gH%g M%g %gH%g' % (x0, ys, x1, cx, y0, ys, x0, ya, cx - ring, cx + ring, ya, x1)
    if pad:                                            # the rows and the columns of the number keys
        tops = sorted({pad[n][1] for n in PAD_KEYS})
        cuts += ''.join(' M%g %gH%g' % (x0, t - 1, x1) for t in tops)
        cuts += ''.join(' M%g %gV%g' % (pad[n][0], tops[0] - 1, y1) for n in ('2', '3'))
    out.append(cut(cuts, 'mask="url(#ringcut)"'))
    if pad:                                            # where four keys meet, their small corners leave the cut a little wider
        out.append(''.join('<circle cx="%g" cy="%g" r="1.15" fill="%s"/>' % (pad[n][0], t - 1, P['groove'])
                           for n in ('2', '3') for t in tops[1:]))
    # the opening is a shallow recess: its floor darker, its upper wall in shade
    oid = uid('open')
    out.append(opening.replace('fill="%s"' % P['body'], 'fill="%s"' % P['groove']).replace('/>', ' opacity=".55"/>'))
    out.append('<clipPath id="%s">%s</clipPath><g clip-path="url(#%s)"><rect x="0" y="%g" width="%d" height="4" fill="url(#wall)"/></g>'
               % (oid, opening, oid, cy - h - 3, W))
    out.append(coin(cx, cy, r, h))
    signs = (dash(*mid(keys['soft_left'])) + dash(*mid(keys['soft_right'])) + handset(*mid(keys['call']))
             + handset(*mid(keys['end']), down=True) + dots(*mid(keys['activity'])) + back_arrow(*mid(keys['clear'])))
    if pad:
        signs += pad_legends(pad)
    out.append(legend(signs))
    return out


def keypad(pad):
    """A sheet with twelve domed keys; satin ridges between the rows so that the rows can be found by feel."""
    xs = sorted({pad[n][0] for n in PAD_KEYS})
    ys = sorted({pad[n][1] for n in PAD_KEYS})
    x0, x1 = xs[0] - 2, pad['3'][0] + pad['3'][2] + 2
    y0, y1 = ys[0] - 2, pad['hash'][1] + pad['hash'][3] + 2
    out = [tray(x0, y0, x1, y1), '<path d="%s" fill="%s"/>' % (soft_rect(x0, y0, x1, y1, *INNER), P['sheet'])]
    for name in PAD_KEYS:
        x, y, w, h = pad[name]
        k = (x + 1.6, y + 2.2, w - 3.2, h - 4.4)
        out.append(rr(k[0], k[1], k[2], k[3], KEY_R, P['key'], 'stroke="%s" stroke-width=".6" filter="url(#seat)"' % P['groove']))
        out.append(rr(k[0], k[1], k[2], k[3], KEY_R, 'url(#dome)'))
    for y in ys[1:]:                                   # a satin ridge between two rows
        out.append('<path d="M%g %gH%g" stroke="url(#satin)" stroke-width="1.1"/>' % (x0 + 4, y, x1 - 4))
    out.append(legend(pad_legends(pad)))
    return ''.join(out)


def pad_legends(pad):
    """The figure of each number key and, under it, its letters."""
    leg = ''
    for name in PAD_KEYS:
        cx, cy = mid(pad[name])
        letters = LETTERS[name]
        leg += L.line(FIGURE.get(name, name), cx, cy + (2.4 if letters else 3.4), 6.8, P['ink'], 0.6, 'middle')
        if letters:
            leg += L.line(letters, cx, cy + 7.4, 2.3, P['ink'], 0.8, 'middle', 1.6)
    return leg


def slot(cx, y, w=12):
    return rr(cx - w / 2, y, w, 2.2, 1.1, P['slot'])


# ---- the outside: the back and the sides (the pictures of the 3D view). The same light as the front: from above and a
# little to the left, so an upper edge catches the light and a lower wall is in shade; every cut is a dark line with its
# lit lower wall. The back shows the coin's metal once more, as the camera.
def outside_defs():
    """The gradients and filters of the back and side pictures (added to defs())."""
    return ('<radialGradient id="lensglass" cx=".4" cy=".36" r=".72"><stop offset="0" stop-color="#3b4468"/>'
            '<stop offset=".5" stop-color="#161b2e"/><stop offset="1" stop-color="#05060a"/></radialGradient>'
            '<linearGradient id="bevel" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3a3936"/>'
            '<stop offset=".55" stop-color="%s"/><stop offset="1" stop-color="#ffffff"/></linearGradient>'
            '<linearGradient id="frost" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fbf9f4"/>'
            '<stop offset="1" stop-color="#d9d3c6"/></linearGradient>'
            '<radialGradient id="led" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#f2d27a" stop-opacity=".95"/>'
            '<stop offset="1" stop-color="#f2d27a" stop-opacity="0"/></radialGradient>'
            '<linearGradient id="steel" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#8a8e94"/>'
            '<stop offset=".35" stop-color="#a7abb0"/><stop offset=".65" stop-color="#9da1a6"/><stop offset="1" stop-color="#83878d"/></linearGradient>'
            '<linearGradient id="steelv" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d3d6da"/>'
            '<stop offset="1" stop-color="#868a90"/></linearGradient>'
            '<pattern id="brush" width="1.3" height="40" patternUnits="userSpaceOnUse"><rect width=".45" height="40" fill="#fff" '
            'opacity=".1"/></pattern>'
            '<filter id="roll" x="-5%%" y="-5%%" width="110%%" height="110%%"><feGaussianBlur stdDeviation="2.4"/></filter>'
            '<filter id="soft" x="-50%%" y="-50%%" width="200%%" height="200%%"><feGaussianBlur stdDeviation=".45"/></filter>'
            % P['coin'][1])


def rolloff(path, reach, opacity):
    """Where a face turns into a wide edge radius (the back's 2 mm edge): a soft shade inside the outline, reach wide."""
    cid = uid('roll')
    return ('<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)"><path d="%s" fill="none" stroke="#000" '
            'stroke-opacity="%g" stroke-width="%g" filter="url(#roll)"/></g>' % (cid, path, cid, path, opacity, reach * 2))


def lens(cx, cy, r, cut=0.846):
    """The camera, the jewel of the back: the coin's spun metal in the coin's shape (the Myna sign), with the coin's rings
    and seat, and in it the lens under a flat cover glass: a polished bevel going down to the glass, the coated element,
    the aperture, and two small lights on the glass."""
    g = r * .56
    cid = uid('lens')
    n = int((r - g - 2) / 1.5) + 1
    rings = ''.join('<circle cx="%g" cy="%g" r="%g" fill="none" stroke="%s" stroke-opacity="%g" stroke-width=".35"/>'
                    % (cx, cy, g + 2 + i * 1.5, '#fff' if i % 2 else '#000', .35 if i % 2 else .07) for i in range(n))
    out = ('<clipPath id="%s">%s</clipPath>' % (cid, L.sign(cx, cy, r, '#000', cut))
           + L.sign(cx, cy, r, 'url(#coin)', cut).replace('/>', ' stroke="%s" stroke-width=".6" filter="url(#seat)"/>' % P['groove'])
           + '<g clip-path="url(#%s)">%s<path d="M%g %g A%g %g 0 0 1 %g %g" fill="none" stroke="#fff" stroke-opacity=".7" '
             'stroke-width=".8"/></g>' % (cid, rings, cx - r * .62, cy - r * cut + 1.1, r, r, cx + r * .2, cy - r * cut + .3))
    out += ('<circle cx="%g" cy="%g" r="%g" fill="none" stroke="url(#bevel)" stroke-width="1.5"/>' % (cx, cy, g + .75)
            + '<circle cx="%g" cy="%g" r="%g" fill="#07080b"/>' % (cx, cy, g)
            + '<circle cx="%g" cy="%g" r="%g" fill="url(#lensglass)"/>' % (cx, cy, g * .74)
            + '<circle cx="%g" cy="%g" r="%g" fill="none" stroke="#6b7390" stroke-opacity=".5" stroke-width=".3"/>' % (cx, cy, g * .5)
            + '<circle cx="%g" cy="%g" r="%g" fill="#020203"/>' % (cx, cy, g * .26)
            + '<path d="M%g %g A%g %g 0 0 1 %g %g" fill="none" stroke="#a9b4e0" stroke-opacity=".35" stroke-width=".6" '
              'stroke-linecap="round"/>' % (cx - g * .62, cy + g * .1, g * .63, g * .63, cx - g * .1, cy - g * .62)
            + '<ellipse cx="%g" cy="%g" rx="%g" ry="%g" fill="#fff" opacity=".55" filter="url(#soft)"/>'
            % (cx - g * .42, cy - g * .45, g * .2, g * .13)
            + '<circle cx="%g" cy="%g" r="%g" fill="#fff" opacity=".22"/>' % (cx + g * .38, cy + g * .4, g * .07))
    return out


def flash(cx, cy, w=12, h=4.6):
    """The flash: a small frosted window set into the surface (its upper wall in shade, its fine Fresnel lines), the LED a
    warm spot behind the frost."""
    x, y = cx - w / 2, cy - h / 2
    cid = uid('flash')
    lines = ''.join('<path d="M%g %gV%g" stroke="#fff" stroke-opacity=".35" stroke-width=".25"/>' % (x + i * 1.2, y, y + h)
                    for i in range(1, int(w / 1.2)))
    return (rr(x - .5, y - .5, w + 1, h + 1, h / 2 + .5, '#000', 'opacity=".35"')
            + rr(x, y, w, h, h / 2, 'url(#frost)')
            + '<ellipse cx="%g" cy="%g" rx="%g" ry="%g" fill="url(#led)"/>' % (cx, cy + .1, w * .22, h * .38)
            + '<clipPath id="%s">%s</clipPath><g clip-path="url(#%s)"><rect x="%g" y="%g" width="%g" height="1.6" fill="url(#wall)"/>'
              '%s</g>' % (cid, rr(x, y, w, h, h / 2, '#000'), cid, x, y, w, lines)
            + rr(x, y, w, h, h / 2, 'none', 'stroke="#000" stroke-opacity=".45" stroke-width=".4"'))


def grille(cx, cy, counts, pitch=3.5, row=3.1, r=.8):
    """A loudspeaker grille: rows of small drilled holes on a staggered grid (counts = holes per row), each a dark hole
    with its lit lower lip."""
    out = []
    n = len(counts)
    for i, c in enumerate(counts):
        y = cy + (i - (n - 1) / 2) * row
        for j in range(c):
            x = cx + (j - (c - 1) / 2) * pitch
            out.append('<circle cx="%g" cy="%g" r="%g" fill="#fff" opacity="%g"/><circle cx="%g" cy="%g" r="%g" fill="%s"/>'
                       % (x, y + .45, r, .14 if P['lit'] else .5, x, y, r, P['slot']))
    return ''.join(out)


def engraved(svg_at, opacity=.75):
    """Lettering cut into the surface. svg_at(dy, colour) draws it lower by dy: the cut is dark, its lower wall lit just
    under it. Never lit from inside (the back has no light)."""
    return ('<g opacity="%g">%s</g><g opacity="%g">%s</g>'
            % (.18 if P['lit'] else .6, svg_at(.42, '#fff'), opacity, svg_at(0, P['groove'])))


def notch(cx, y, w=12, d=3):
    """A nail notch under a seam: a shallow half-round recess, its floor a little darker, its upper wall in shade."""
    p = ('M%g %g H%g A%g %g 0 0 1 %g %g H%g A%g %g 0 0 1 %g %g Z'
         % (cx - w / 2, y, cx + w / 2, d, d, cx + w / 2 - d, y + d, cx - w / 2 + d, d, d, cx - w / 2, y))
    cid = uid('notch')
    return ('<path d="%s" fill="#000" opacity=".16"/><clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)">'
            '<rect x="%g" y="%g" width="%g" height="1.8" fill="url(#wall)"/></g>'
            '<path d="M%g %g H%g" fill="none" stroke="#fff" stroke-opacity="%g" stroke-width=".5"/>'
            % (p, cid, p, cid, cx - w / 2, y, w, cx - w / 2 + d, y + d + .3, cx + w / 2 - d, .12 if P['lit'] else .4))


def hole(cx, cy, w, h):
    """A small opening (the lanyard eyelet): dark, with its lit lower lip."""
    r = min(w, h) / 2
    return (rr(cx - w / 2, cy - h / 2 + .45, w, h, r, '#fff', 'opacity="%g"' % (.14 if P['lit'] else .5))
            + rr(cx - w / 2, cy - h / 2, w, h, r, P['slot']))


def screw(cx, cy, r=2):
    """A small stainless screw with a six-lobe recess, in its counterbore."""
    import math
    star = ' '.join('%.2f,%.2f' % (cx + (r * .5 if i % 2 else r * .28) * math.cos(i * math.pi / 6),
                                    cy + (r * .5 if i % 2 else r * .28) * math.sin(i * math.pi / 6)) for i in range(12))
    return ('<circle cx="%g" cy="%g" r="%g" fill="#000" opacity=".4"/>' % (cx, cy + .3, r + .5)
            + '<circle cx="%g" cy="%g" r="%g" fill="url(#steelv)"/>' % (cx, cy, r)
            + '<polygon points="%s" fill="#2a2b2e"/>' % star)


def side_key(x, y, w, h, metal=False):
    """A key in a side wall, seen square on: in its slot (a dark seat), a little proud, gently domed, its upper end lit.
    metal: the coin's spun metal (the shutter, kin to the camera); else the body colour."""
    r = min(w, h) / 2
    cid = uid('skey')
    return (rr(x - .7, y - .7, w + 1.4, h + 1.4, r + .7, '#000', 'opacity=".5"')
            + rr(x, y, w, h, r, 'url(#coin)' if metal else P['body'], 'filter="url(#seat)"')
            + '<clipPath id="%s">%s</clipPath><g clip-path="url(#%s)">%s'
              '<path d="M%g %gH%g" stroke="#fff" stroke-opacity="%g" stroke-width=".8"/></g>'
            % (cid, rr(x, y, w, h, r, '#000'), cid, rr(x - 1, y, w + 2, h, r, 'url(#dome)'), x, y + .5, x + w,
               .75 if metal or not P['lit'] else .25)
            + rr(x, y, w, h, r, 'none', 'stroke="#000" stroke-opacity=".35" stroke-width=".4"'))


USB_SHELL = .2                  # mm: the USB-C receptacle's steel shell, seen end on round its mouth
USB_TONGUE = (6.69, .7)         # mm: the tongue across the middle of the mouth


def port(cx, cy, w, h, k=3.5):
    """The USB-C receptacle (charging and data), seen end on in a side wall, w by h picture px (8.94 x 3.26 mm at true
    size; k px a mm): a stadium opening cut straight into the shell, the receptacle's steel shell round its mouth, the dark
    mouth, and the tongue across the middle, dark and matte. No countersink: the 3D view cuts the same opening."""
    t, tw, th = USB_SHELL * k, USB_TONGUE[0] * k, USB_TONGUE[1] * k
    return ''.join([
        rr(cx - w / 2, cy - h / 2, w, h, h / 2, 'url(#steelv)'),
        rr(cx - w / 2 + t, cy - h / 2 + t, w - 2 * t, h - 2 * t, h / 2 - t, '#060607'),
        rr(cx - tw / 2, cy - th / 2, tw, th, th * .45, '#1b1c1f'),
        rr(cx - w / 2, cy - h / 2, w, h, h / 2, 'none', 'stroke="#000" stroke-opacity=".45" stroke-width=".3"')])


def door(x, y, w, h):
    """A small flush door (the memory card) in a side wall: a fine cut round it, a nail notch at its lower end."""
    r = min(w, h) * .3
    return (cut(soft_rect(x, y, x + w, y + h, r, .45))
            + '<ellipse cx="%g" cy="%g" rx="%g" ry="1.2" fill="#000" opacity=".3"/>' % (x + w / 2, y + h + .2, w * .22))


def slide_plate(x0, y0, x1, y1):
    """The slide plate on the slab's underside: stainless, brushed along the slide, in a shallow seat, with four screws."""
    p = soft_rect(x0, y0, x1, y1, 8, .3)
    cid = uid('plate')
    out = ('<path d="%s" fill="#000" opacity=".4" transform="translate(0 .6)" filter="url(#soft)"/>' % p
           + '<path d="%s" fill="url(#steel)"/>' % p
           + '<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)"><rect x="%g" y="%g" width="%g" height="%g" '
             'fill="url(#brush)"/><rect x="0" y="%g" width="%d" height="3" fill="url(#wall)" opacity=".5"/></g>'
           % (cid, p, cid, x0, y0, x1 - x0, y1 - y0, y0, W)
           + '<path d="%s" fill="none" stroke="#fff" stroke-opacity=".6" stroke-width=".5" transform="translate(0 .5)"/>' % p
           + '<path d="%s" fill="none" stroke="#000" stroke-opacity=".45" stroke-width=".5"/>' % p)
    for sx in (x0 + 7, x1 - 7):
        for sy in (y0 + 8, y1 - 8):
            out += screw(sx, sy, 1.8)
    return out
