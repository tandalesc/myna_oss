#!/usr/bin/env python3
"""Draw the pictures of this skin: the Myna P2 chin, the pebble slider whose lower half carries a chin.

    python3 -I draw.py          (from any directory: it works on the folder it is in; BRAND=name changes the wordmark)

Original work of the project, standard library only; the parts are those of the P2 family (pebble.py).

The upper slab is a little shorter than the back half. Closed, the back half's chin stays in view under it: a slim raised
end of the same moulding, in the body colour, flush with the slab, carrying only the microphone. The name is on the slab's
pane under the screen, as on the slider and the open flip. Slab and chin meet at one crisp seam: small, equal corners on
both sides of it (CHIN_CORNER, the key radius of the family), the slab's lower edge turning away into shade, the chin's
upper edge a narrow lit chamfer. The satin band runs round the whole silhouette, slab and chin, and is cut only by the
seam. The chin's outline is the back half's own outline below the seam, so its long lower corners are the body corners.

Open, the keypad appears between the slab and the chin, sunk in the deck of the back half; the slab's shadow lies on the
deck under it, the corner where the deck meets the chin's wall is in shade, and the rails show beside the slab's lower
corners. The slab's shadow on the deck is drawn in the back half's picture, at the place the slab's edge has when open,
under the slab when closed: so the flush chin never takes a shadow from the slab, and the open deck always does.
"""
import importlib.util
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('pebble', os.path.join(HERE, 'pebble.py'))
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)
L = B.L

FACE = (5.5, 4, 170.5)          # left, top, right of the slab; its bottom is CHIN + 4 above the lower edge of the closed picture
BACK = (4, 4, 172)               # left, top, right of the back half: its top flush with the slab's (as on a slider: closed,
                                # the two halves end in one top edge), 1.5 wider on each side
CHIN = 24                       # from the slab's lower edge to the lower edge of the back half (seam included)
CHIN_CORNER = (B.KEY_R, .32)    # the slab's lower corners and the chin's upper corners: small and equal, a crisp seam
SEAM = 1.2                      # the gap between the slab and the chin when closed
CHAMFER = 1.8                   # the lit facet along the chin's upper edge


def extra_defs():
    """rim: the slab's contact shadow, close round its edge (no offset, so none falls on the flush chin); castblur: the
    softness of the slab's shadow on the open deck."""
    return ('<filter id="rim" x="-5%" y="-5%" width="110%" height="110%"><feDropShadow dx="0" dy="0" stdDeviation=".8" '
            'flood-color="#000" flood-opacity=".42"/></filter>'
            '<filter id="castblur" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="1.9"/></filter>')


def _split(p, t):
    """The part [t, 1] of the cubic p (four points), by de Casteljau."""
    lerp = lambda a, b: (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    a, b, c = lerp(p[0], p[1]), lerp(p[1], p[2]), lerp(p[2], p[3])
    d, e = lerp(a, b), lerp(b, c)
    return [lerp(d, e), e, c, p[3]]


def _at_y(p, y):
    """The parameter where the cubic p (y growing with t) reaches y."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        t = (lo + hi) / 2
        u = 1 - t
        yt = u ** 3 * p[0][1] + 3 * u * u * t * p[1][1] + 3 * u * t * t * p[2][1] + t ** 3 * p[3][1]
        lo, hi = (t, hi) if yt < y else (lo, t)
    return (lo + hi) / 2


def chin_outline(x0, x1, yt, y1, inset=0, band=False):
    """The chin: the back half's outline (x0..x1, lower edge y1, body corners) below its upper edge yt, which has the small
    corners CHIN_CORNER. inset shrinks every edge by that much (for the band). band = the open line along the sides and
    the lower edge only, from the end of one upper corner to the other."""
    x0, x1, yt, y1 = x0 + inset, x1 - inset, yt + inset, y1 - inset
    eb, kb = B.CORNER[0] + B.WALL - inset, B.CORNER[1]
    cb = eb * kb
    r = CHIN_CORNER[0] - inset
    c = r * CHIN_CORNER[1]
    corner = [(x1, y1 - eb), (x1, y1 - cb), (x1 - cb, y1), (x1 - eb, y1)]        # the back half's lower right corner
    rest = _split(corner, _at_y(corner, yt + r))
    a, q = rest[0], rest[1]                                    # a: where the small corner meets the side
    dx, dy = a[0] - q[0], a[1] - q[1]
    n = (dx * dx + dy * dy) ** .5
    up = (dx / n, dy / n)                                      # along the side, upwards
    k = (a[0] + up[0] * r, yt)                                 # the corner point the small corner rounds
    mirror = lambda p: (x0 + x1 - p[0], p[1])
    pts = [(k[0] - r, yt), (k[0] - c, yt), (a[0] + up[0] * (r - c), a[1] + up[1] * (r - c)), a] + rest[1:]
    left = [mirror(p) for p in reversed(pts)]
    f = lambda p: '%.2f %.2f' % p
    d = 'M%s C%s %s %s C%s %s %s L%s C%s %s %s C%s %s %s' % tuple(f(p) for p in pts + left)
    if band:
        return d
    return 'M%s H%.2f' % (f(left[-1]), pts[0][0]) + d[d.index(' C'):] + ' Z'


def slab_band(x0, y0, x1, y1):
    """The band on the slab: round its top and sides, into its small lower corners, and no further (the seam cuts it)."""
    e, k = B.CORNER[0] - .7, B.CORNER[1]
    eb, kb = CHIN_CORNER[0] - .7, CHIN_CORNER[1]
    c, cb = e * k, eb * kb
    x0, y0, x1, y1 = x0 + .7, y0 + .7, x1 - .7, y1 - .7
    return B.band('M%g %g C%g %g %g %g %g %g V%g C%g %g %g %g %g %g H%g C%g %g %g %g %g %g V%g C%g %g %g %g %g %g'
                  % (x0 + eb, y1, x0 + cb, y1, x0, y1 - cb, x0, y1 - eb, y0 + e, x0, y0 + c, x0 + c, y0, x0 + e, y0,
                     x1 - e, x1 - c, y0, x1, y0 + c, x1, y0 + e, y1 - eb, x1, y1 - cb, x1 - cb, y1, x1 - eb, y1))


def slab_path(hc):
    x0, y0, x1 = FACE
    return B.soft_rect(x0, y0, x1, hc - 4 - CHIN, B.CORNER[0], B.CORNER[1], bottom=CHIN_CORNER)


def back(hc, pad, travel):
    x0, y0, x1 = BACK
    y1 = hc - 4
    ct = y1 - CHIN                                     # the slab's lower edge, closed
    yt = ct + SEAM                                     # the chin's upper edge
    deck = B.soft_rect(x0, y0, x1, y1, B.CORNER[0] + B.WALL, B.CORNER[1])
    tray_top = min(r[1] for r in pad.values()) - 2 - B.TRAY
    out = B.body(deck, y0, y1, fill=B.P['back'])
    out += [B.rails(9.5, B.W - 9.5, y0 + 16, tray_top - 3), B.keypad(pad)]
    # the slab's shadow on the deck, where the slab's lower edge is when open (under the slab when closed)
    se = ct - travel
    sid = B.uid('shade')
    out.append('<clipPath id="%s"><rect x="0" y="%g" width="%d" height="14"/></clipPath><g clip-path="url(#%s)">'
               '<path d="%s" fill="#000" opacity=".4" filter="url(#castblur)" transform="translate(0 %g)"/></g>'
               % (sid, se - 2, B.W, sid, slab_path(hc), 2.4 - travel))
    # the inner corner where the deck meets the chin's upper wall is in shade
    out.append('<rect x="%g" y="%g" width="%g" height="4" fill="url(#wall)" transform="rotate(180 %g %g)"/>'
               % (x0 + 5, yt - 4, x1 - x0 - 10, B.W / 2, yt - 2))
    # the chin: a raised end of the same moulding, flush with the slab; its upper edge a narrow lit chamfer
    chin = chin_outline(x0, x1, yt, y1)
    out += B.body(chin, yt, y1)
    cid = B.uid('chin')
    out.append('<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)"><rect x="0" y="%g" width="%d" height="%g" '
               'fill="#fff" opacity="%g"/><path d="M0 %gH%d" stroke="#000" stroke-opacity=".1" stroke-width=".4"/></g>'
               % (cid, chin, cid, yt, B.W, CHAMFER, .2 if B.P['lit'] else .5, yt + CHAMFER, B.W))
    out.append(B.band(chin_outline(x0, x1, yt, y1, .7, band=True)))
    out.append(B.slot(B.W / 2, (yt + y1) / 2 - 1.6))
    return out


def face(view, hc):
    keys, g = view.get('keys', {}), view['glass']
    x0, y0, x1 = FACE
    y1 = hc - 4 - CHIN
    out = B.body(slab_path(hc), y0, y1)
    out[0] = out[0].replace('url(#lift)', 'url(#rim)')
    out.append(slab_band(x0, y0, x1, y1))
    out += B.pane(g, x0 + 7.5, y0 + 8, g[1] + g[3] + 20)
    if 'soft_left' in keys:
        out += B.plate(keys)
    return out


def draw(view, skin, part='all'):
    views = {v['id']: v for v in skin['views']}
    slide = skin['slide']
    vo, vc = views[slide['open']], views[slide['closed']]
    w, h = view['size']
    hc, travel = vc['size'][1], slide['travel']
    shift = travel if view['id'] == slide['open'] else 0
    pad = {k: [r[0], r[1] - travel, r[2], r[3]] for k, r in vo['keys'].items() if k in B.PAD_KEYS}
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">' % (w, h, w, h),
           B.defs().replace('</defs>', extra_defs() + '</defs>')]
    if part in ('all', 'base'):
        out.append('<g transform="translate(0 %g)">' % shift)
        out += back(hc, pad, travel)
        out.append('</g>')
    if part in ('all', 'face'):
        out += face(view, hc)
    out.append('</svg>')
    return '\n'.join(x for x in out if x) + '\n'


# ---- the outside: the back, the slab's underside and the four sides, for the 3D view (skin.json "body3d")
#
# The phone is two slabs. The face slab (glass, screen, plate) is a soft-touch shell in the body colour with the satin band
# on its front edge, and an underside in the darker tone that carries the stainless slide plate. The back slab is a carrier
# in the darker tone (the deck the keypad sits in, the side band, the top end) and a rear shell in the body colour (the
# back with its 2 mm edge radius, the bottom end, and the chin, which is the rear shell folded round the bottom end up to
# the front). The part line between carrier and rear shell runs round the sides where the back's edge radius starts. The
# battery cover is the middle of the rear shell, between two seams straight across the back.
#
# Rear layout (closed picture, seen from behind, so the phone's left is on the right): the camera on the centre line near
# the top, the coin's metal in the coin's shape; the flash under it; the cover's seams; the name engraved low on the
# cover; at the bottom, behind the chin, the loudspeaker; a nail notch at one end of the lower seam, the lanyard eyelet at
# the other corner. Sides: volume rocker and the two-stage shutter on the right, the memory card door on the left, the
# USB-C receptacle and the lanyard slot at the bottom, a plain top.
#
# These pictures are albedo: the colours and the details of the surfaces, with no light drawn in (no shade across the
# thickness, no turning ends, no drop shadows), because the 3D view lights them itself; a light drawn in would fight its
# light and part where two pictures meet at a corner. The front pictures (the 2D page's) keep their drawn light.
LENS = (88, 48, 15)              # the camera ring: centre and radius (closed picture, seen from behind)
FLASH = (88, 71)
SEAMS = (88, 300)                # the battery cover's seams across the back
NAME_Y = 268
GRILLE = (88, 319, (9, 10, 9))
NOTCH_X = 36                     # the nail notch under the lower seam (seen from behind; the phone's right)
EYELET = (140, 329)              # the lanyard eyelet on the back (seen from behind; the phone's lower left corner)
ROCKER = (80, 124)               # right side, closed picture y: volume up (upper half) and down (lower half)
SHUTTER = (252, 280)             # right side: the two-stage shutter, satin metal
CARD = (150, 203)                # left side: the memory card door
USB_C = (8.94, 3.26)             # mm: the USB-C receptacle's opening on the bottom end (the back slab's), centred across it
USB_Z = 8.0                      # mm: the middle of the opening, from the front (in the back slab, under the chin's)
USB_DEPTH = 3.6                  # mm: how far the receptacle's shell goes in


# The keys of the fronts as solids (body3d "caps") and the recesses they sit in ("wells"), in mm from the slab's front: the
# control plate's keys stand proud of the face; the coin stands in its opening, a shallow well, and rises a little above
# the plate's keys; the number keys stand in the keypad's tray, a well in the deck, their tops a little under the deck
# (the face slab slides over it).
PLATE_Z = (-.5, 0)              # the plate's keys: top, foot
OPENING = .6                    # the coin's opening: depth
COIN_Z = (-.4, .6)              # the coin: top of its rim, foot (on the opening's floor)
COIN_DOME = .25                 # the coin's middle above its rim
TRAY_DEPTH = .9                 # the keypad's tray in the deck
PAD_Z = (.2, .9)                # the number keys: top, foot
KEY_EDGE = (.18, .25, .2)       # the round of the top edge: plate keys, coin, number keys


def _n(v):
    s = '%.2f' % v
    return s.rstrip('0').rstrip('.') if '.' in s else s


def _path(*parts):
    """A path from commands and numbers: numbers are written with at most two decimals."""
    return re.sub(r'([MHVCAZ]) ', r'\1', ' '.join(p if isinstance(p, str) else _n(p) for p in parts))


def sign_path(cx, cy, r, h):
    """The Myna sign (lettering.sign) as an outline: a circle of radius r cut flat at h above and below its centre."""
    a = (r * r - h * h) ** .5
    return _path('M', cx - a, cy - h, 'H', cx + a, 'A', r, r, '0 0 1', cx + a, cy + h, 'H', cx - a, 'A', r, r, '0 0 1', cx - a, cy - h, 'Z')


def round_rect_path(x, y, w, h, r):
    return _path('M', x + r, y, 'H', x + w - r, 'A', r, r, '0 0 1', x + w, y + r, 'V', y + h - r, 'A', r, r, '0 0 1', x + w - r, y + h,
                 'H', x + r, 'A', r, r, '0 0 1', x, y + h - r, 'V', y + r, 'A', r, r, '0 0 1', x + r, y, 'Z')


def front3d(skin):
    """(wells, caps) of body3d: the plate's six keys, cut as pebble.plate cuts them (each key the plate's surface between the
    grooves, less half a groove on each side, and less the coin's opening), the coin, the twelve number keys as
    pebble.keypad draws them, and the two recesses. Outlines in closed-view px."""
    views = {v['id']: v for v in skin['views']}
    vc, vo = views[skin['slide']['closed']], views[skin['slide']['open']]
    travel = skin['slide']['travel']
    keys = vc['keys']
    pad = {k: [r[0], r[1] - travel, r[2], r[3]] for k, r in vo['keys'].items() if k in B.PAD_KEYS}
    g = B.GROOVE / 2
    names = ('soft_left', 'soft_right', 'call', 'end', 'activity', 'clear')
    rects = [keys[n] for n in names]
    x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
    x1, y1 = max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)
    cx = B.mid(keys['select'])[0]
    top, bottom = keys['up'][1], keys['down'][1] + keys['down'][3]
    cy, h = (top + bottom) / 2, (bottom - top) / 2
    r = (keys['right'][0] + keys['right'][2] - keys['left'][0]) / 2
    ring, hr = r + 3, h + 3                            # the opening, as pebble.plate cuts it
    ys, ya = keys['call'][1] - 1, keys['activity'][1] - 1
    assert cy - hr > ys + g and cy + hr < y1 - g and abs(cx - B.W / 2) < 1e-9
    e = B.INNER[0] - g
    c = e * B.INNER[1]
    X0, Y0, Y1 = x0 + g, y0 + g, y1 - g
    oa = (ring * ring - hr * hr) ** .5
    arc = lambda y: (ring * ring - (y - cy) ** 2) ** .5   # half the opening's width at y

    # The plate's grooves, as pebble.plate cuts them: one across under the soft keys, one between the soft keys, and on each
    # side one between call and activity (end and clear) that ends at the coin's opening. Nothing cuts the plate above or
    # below the opening, so call and end are one moulding round the top of the coin, and activity and clear one round its
    # bottom, each half its own key (pressed, the moulding tips that way, as a rocker does). check_body3d() looks for
    # exactly these grooves in the drawing, so the solids cannot drift from it.
    grooves = ['M%g %gH%g M%g %gV%g M%g %gH%g M%g %gH%g' % (x0, ys, x1, cx, y0, ys, x0, ya, cx - ring, cx + ring, ya, x1),
               B.soft_rect(x0, y0, x1, y1, *B.INNER),                                    # the groove round the plate
               re.search(r' d="([^"]+)"', B.L.sign(cx, cy, ring, '#000', hr / ring)).group(1)]   # the coin's opening
    D0 = cx - X0
    XR, XL = (lambda d: cx + d), (lambda d: cx - d)    # d: the distance from the centre line

    def soft(X):
        return _path('M', X(g), Y0, 'H', X(D0 - e), 'C', X(D0 - c), Y0, X(D0), Y0 + c, X(D0), Y0 + e, 'V', ys - g, 'H', X(g), 'Z')

    upper = _path('M', XL(D0), ys + g, 'H', XR(D0), 'V', ya - g, 'H', XR(arc(ya - g)), 'A', ring, ring, '0 0 0', XR(oa), cy - hr,
                  'H', XL(oa), 'A', ring, ring, '0 0 0', XL(arc(ya - g)), ya - g, 'H', XL(D0), 'Z')
    lower = _path('M', XL(D0), ya + g, 'H', XL(arc(ya + g)), 'A', ring, ring, '0 0 0', XL(oa), cy + hr, 'H', XR(oa),
                  'A', ring, ring, '0 0 0', XR(arc(ya + g)), ya + g, 'H', XR(D0), 'V', Y1 - e, 'C', XR(D0), Y1 - c, XR(D0 - c), Y1,
                  XR(D0 - e), Y1, 'H', XL(D0 - e), 'C', XL(D0 - c), Y1, XL(D0), Y1 - c, XL(D0), Y1 - e, 'Z')
    plate = (('soft_left', soft(XL)), ('soft_right', soft(XR)), (['call', 'end'], upper), (['activity', 'clear'], lower))
    caps = [{'key': k, 'slab': 'face', 'outline': d, 'z': list(PLATE_Z), 'edge': KEY_EDGE[0], 'material': 'shell'} for k, d in plate]
    caps.append({'key': ['select', 'up', 'down', 'left', 'right'], 'slab': 'face', 'outline': sign_path(cx, cy, r, h), 'z': list(COIN_Z),
                 'edge': KEY_EDGE[1], 'dome': COIN_DOME, 'material': 'spun'})
    for name in B.PAD_KEYS:
        x, y, w, hh = pad[name]
        caps.append({'key': name, 'slab': 'back', 'outline': round_rect_path(x + 1.6, y + 2.2, w - 3.2, hh - 4.4, B.KEY_R),
                     'z': list(PAD_Z), 'edge': KEY_EDGE[2], 'material': 'key'})
    xs = sorted({pad[n][0] for n in B.PAD_KEYS})
    tx0, tx1 = xs[0] - 2, pad['3'][0] + pad['3'][2] + 2
    ty0, ty1 = min(pad[n][1] for n in B.PAD_KEYS) - 2, pad['hash'][1] + pad['hash'][3] + 2
    wells = [{'slab': 'face', 'outline': sign_path(cx, cy, ring, hr), 'depth': OPENING, 'material': 'shell'},
             {'slab': 'back', 'outline': B.soft_rect(tx0 - B.TRAY, ty0 - B.TRAY, tx1 + B.TRAY, ty1 + B.TRAY, B.INNER[0] + B.TRAY, B.INNER[1]),
              'depth': TRAY_DEPTH, 'material': 'carrier'}]
    return wells, caps, grooves


CAMERA_PROUD = .5               # mm: the camera ring above the back
LENS_DEPTH = .4                 # mm: the lens under the ring's top
FLASH_PROUD = .12               # mm: the flash's window above the back
EAR_DEPTH = .6                  # mm: the earpiece's slot, from the glass down to its grille
EAR_EDGE = .2                   # mm: the round of the slot's edge


def ports3d(skin):
    """The features of body3d that are cut into the shell, as drawn: the earpiece's slot in the pane (pebble.earpiece, the
    face slab's front) and the USB-C receptacle in the bottom end (pebble.port, the back slab's)."""
    ex, ey, ew, eh = B.earpiece(FACE[1] + 8)
    ear = {'id': 'earpiece', 'look': 'front', 'slab': 'face', 'outline': round_rect_path(ex, ey, ew, eh, eh / 2), 'depth': EAR_DEPTH,
           'edge': EAR_EDGE, 'material': 'mesh', 'wall': 'mesh'}
    k = skin['body3d']['px_per_mm']
    usb = {'id': 'usb_c', 'side': 'bottom', 'slab': 'back', 'x': [round(B.W / 2 - USB_C[0] * k / 2, 3), round(B.W / 2 + USB_C[0] * k / 2, 3)],
           'z': [round(USB_Z - USB_C[1] / 2, 3), round(USB_Z + USB_C[1] / 2, 3)], 'size': list(USB_C), 'depth': USB_DEPTH,
           'shell': B.USB_SHELL, 'tongue': list(B.USB_TONGUE), 'material': 'steel', 'inside': 'tongue'}
    return ear, usb


def outside3d(skin):
    """(inlays, camera, flash) of body3d, as drawn: the glass pane of the face (pebble.pane) and the slide plate under the
    face slab (pebble.slide_plate), flush regions of their own material (outlines in the closed view seen from the front);
    the camera ring (pebble.lens: the Myna sign, the lens and its bevel inside) and the flash (pebble.flash), standing out of
    the back (outlines in the back's picture, seen from behind)."""
    views = {v['id']: v for v in skin['views']}
    vo, vc = views[skin['slide']['open']], views[skin['slide']['closed']]
    hc, g = vc['size'][1], vo['glass']
    px, py = FACE[0] + 7.5, FACE[1] + 8
    inlays = [{'slab': 'face', 'face': 'front', 'outline': B.soft_rect(px, py, B.W - px, g[1] + g[3] + 20, B.CORNER[0] - 7.5, B.CORNER[1]),
               'material': 'glass'},
              {'slab': 'face', 'face': 'back', 'outline': B.soft_rect(30, 20, B.W - 30, hc - 4 - CHIN - 16, 8, .3), 'material': 'steel', 'brush': 'x'}]
    cx, cy, r = LENS
    camera = {'id': 'camera', 'look': 'back', 'at': [cx, cy], 'r': r, 'outline': sign_path(cx, cy, r, r * .846), 'proud': CAMERA_PROUD,
              'lens': {'r': round(r * .56, 4), 'bevel': 1.5, 'depth': LENS_DEPTH}}
    fw, fh = 12, 4.6
    flash = {'id': 'flash', 'look': 'back', 'at': list(FLASH), 'size': [fw, fh], 'outline': round_rect_path(FLASH[0] - fw / 2, FLASH[1] - fh / 2, fw, fh, fh / 2),
             'proud': FLASH_PROUD, 'material': 'frost'}
    return inlays, camera, flash


def check_body3d(skin):
    """body3d in skin.json describes these drawings: its numbers must be the ones drawn here."""
    b = skin['body3d']
    hc = next(v for v in skin['views'] if v['id'] == skin['slide']['closed'])['size'][1]
    slabs = {s['id']: s for s in b['slabs']}
    want = {'face': slab_path(hc), 'back': B.soft_rect(BACK[0], BACK[1], BACK[2], hc - 4, B.CORNER[0] + B.WALL, B.CORNER[1]),
            'chin': chin_outline(BACK[0], BACK[2], hc - 4 - CHIN + SEAM, hc - 4)}
    for k, d in want.items():
        if slabs[k]['outline'] != d:
            raise SystemExit('skin.json body3d: the outline of %s is not the drawn one; it is\n%s' % (k, d))
    wells, caps, grooves = front3d(skin)
    vo = next(v for v in skin['views'] if v['id'] == skin['slide']['open'])
    ids = B._ids[0]
    drawn = draw(vo, skin, 'face')
    B._ids[0] = ids                                    # the pictures drawn after this keep their ids
    for d in grooves:
        if 'd="%s"' % d not in drawn:
            raise SystemExit('skin.json body3d: the control plate is not cut as its caps are (front3d() looks for\n%s\nin the '
                             'drawing): make the caps follow the drawn grooves' % d)
    inlays, camera, flash = outside3d(skin)
    for k, v in (('wells', wells), ('caps', caps), ('inlays', inlays)):
        if b.get(k) != v:
            raise SystemExit('skin.json body3d: %s are not the drawn ones; they are\n%s' % (k, '\n'.join(json.dumps(x) for x in v)))
    features = {f['id']: f for f in b.get('features', [])}
    for f in (camera, flash) + ports3d(skin):
        if features.get(f['id']) != f:
            raise SystemExit('skin.json body3d: the feature %s is not the drawn one; it is\n%s' % (f['id'], json.dumps(f)))
    for v in B.PALETTES:
        m = b['materials'][v]
        if (m['shell']['colour'], m['carrier']['colour'], m['under']['colour'], m['key']['colour']) != (
                B.PALETTES[v]['body'], B.PALETTES[v]['back'], B.PALETTES[v]['back'], B.PALETTES[v]['key']):
            raise SystemExit('skin.json body3d: the colours of %s are not those of pebble.py' % v)


class Depth:
    """The thickness numbers of body3d, in picture px (z from the front face)."""
    def __init__(self, skin):
        b = skin['body3d']
        k = b['px_per_mm']
        s = {x['id']: x for x in b['slabs']}
        self.zf = s['face']['z'][1] * k                 # the face slab's back
        self.zb = s['back']['z'][0] * k                 # the back slab's front (the deck)
        self.th = b['thickness'] * k
        self.zp = b['part_line'] * k                    # carrier | rear shell
        self.rf = s['face']['edges']['front']['radius'] * k
        self.band = s['face']['edges']['front']['chamfer'] * k
        self.ri = s['face']['edges']['back']['radius'] * k
        self.rr = s['back']['edges']['back']['radius'] * k
        self.k = k


def rear(hc, D):
    """The back slab seen from behind (closed picture coordinates): the rear shell, the cover's seams, the camera and
    flash, the engraved name, the loudspeaker, the notch and the eyelet."""
    x0, y0, x1 = BACK
    y1 = hc - 4
    path = B.soft_rect(x0, y0, x1, y1, B.CORNER[0] + B.WALL, B.CORNER[1])
    out = ['<path d="%s" fill="%s"/>' % (path, B.P['body'])]
    cid = B.uid('rear')
    out.append('<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)">%s</g>'
               % (cid, path, cid, B.cut('M0 %gH%d M0 %gH%d' % (SEAMS[0], B.W, SEAMS[1], B.W))))
    out.append(B.notch(NOTCH_X, SEAMS[1] + .7))
    out.append(B.lens(*LENS))
    out.append(B.flash(*FLASH))
    out.append(B.engraved(lambda dy, c: L.wordmark(B.W / 2, NAME_Y + dy, 2.6, c)))
    out.append(B.grille(GRILLE[0], GRILLE[1], GRILLE[2]))
    out.append(B.hole(EYELET[0], EYELET[1], 4.4, 2.4))
    return out


def underside(hc):
    """The face slab's underside seen from behind: the darker moulding, the two guides that run on the deck's rails, the
    stainless slide plate with its four screws. Closed, the back slab hides it (their top ends are flush); open, its upper part
    shows."""
    x0, y0, x1 = FACE
    y1 = hc - 4 - CHIN
    path = slab_path(hc)
    out = ['<path d="%s" fill="%s"/>' % (path, B.P['back'])]
    out.append(B.rails(9.5, B.W - 9.5, 36, y1 - 10))
    out.append(B.slide_plate(30, 20, B.W - 30, y1 - 16))
    return out


def draw_back(skin, part, opened):
    """back.svg (closed), back_open.svg (open), and the layers rear.svg and under.svg (open picture, as base and face)."""
    views = {v['id']: v for v in skin['views']}
    vc, vo = views[skin['slide']['closed']], views[skin['slide']['open']]
    hc, travel = vc['size'][1], skin['slide']['travel']
    w, h = (vo if opened else vc)['size']
    D = Depth(skin)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">' % (w, h, w, h),
           B.defs().replace('</defs>', extra_defs() + B.outside_defs() + '</defs>')]
    if part in ('all', 'under'):
        out += underside(hc)
    if part in ('all', 'rear'):
        out.append('<g transform="translate(0 %g)">' % (travel if opened else 0))
        out += rear(hc, D)
        out.append('</g>')
    out.append('</svg>')
    return '\n'.join(x for x in out if x) + '\n'


class Side:
    """A side picture: an orthographic view of one side, exactly body length by thickness. s runs along the side (y of the
    front picture less 4 for left and right, x less 4 for top and bottom), z from the front face. left: the front face is
    at the right of the picture; right: at the left; top: at the bottom; bottom: at the top (third-angle projection)."""
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
        (xa, ya), (xb, yb) = self.pt(s0, z0), self.pt(s1, z1)
        return '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="%s" %s/>' % (min(xa, xb), min(ya, yb), abs(xb - xa),
                                                                                       abs(yb - ya), fill, extra)

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


def side(skin, look, opened):
    """One side picture: left or right (closed or open), top or bottom (closed)."""
    D = Depth(skin)
    views = {v['id']: v for v in skin['views']}
    vc = views[skin['slide']['closed']]
    hc, travel = vc['size'][1], skin['slide']['travel']
    sh = travel if opened else 0                       # the back slab, lower by travel when open
    th, zf, zb, zp, rf, ri, rr_, band = D.th, D.zf, D.zb, D.zp, D.rf, D.ri, D.rr, D.band
    fy0, fy1 = FACE[1] - 4, hc - 4 - CHIN - 4         # the face slab along the side (s), 0 .. 310
    by0, by1 = BACK[1] - 4 + sh, hc - 8 + sh           # the back slab, 0 .. 334 (+ travel when open)
    cy = hc - 4 - CHIN + SEAM - 4 + sh                 # the chin's upper wall
    if look in ('left', 'right'):
        length = by1 if opened else hc - 8
    else:
        length = BACK[2] - BACK[0]
    S = Side(look, length, D)
    body, back = B.P['body'], B.P['back']
    out = []
    if look in ('left', 'right'):
        face_pts = [(fy0, 0, rf), (fy0, zf, ri), (fy1, zf, ri), (fy1, 0, rf)]
        back_pts = [(by0, zb, ri), (cy, zb, 0), (cy, 0, 1.8), (by1, 0, rf), (by1, th, rr_), (by0, th, rr_)]
        fpath, bpath = S.poly(face_pts), S.poly(back_pts)
        if not opened:                                  # the seam between the face slab and the chin: its walls in shade
            out.append(S.rect(fy1, cy, .6, zb, '#000', 'opacity=".7"'))
        out.append('<path d="%s" fill="%s"/>' % (bpath, body))
        cid = B.uid('sideb')
        out.append('<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)">' % (cid, bpath, cid))
        out.append(S.rect(by0, cy, zb, zp, back))                                         # the carrier's side band
        # part lines: carrier | rear shell along the side, carrier | chin at the chin, the cover's seams across the edge
        pl = 'M%.2f %.2fL%.2f %.2f' % (S.pt(by0, zp) + S.pt(by1, zp))
        pl += ' M%.2f %.2fL%.2f %.2f' % (S.pt(cy, zb) + S.pt(cy, zp))
        out.append('<path d="%s" stroke="#000" stroke-opacity=".38" stroke-width=".5" fill="none"/>' % pl)
        for sy in SEAMS:
            out.append('<path d="M%.2f %.2fL%.2f %.2f" stroke="%s" stroke-width=".9" fill="none"/>'
                       % (S.pt(sy - 4 + sh, zp) + S.pt(sy - 4 + sh, th) + (B.P['groove'],)))
        # the satin band round the chin's front edge
        out.append(S.rect(cy, by1, 0, band, S.grad((0, 0), (length, 0), [(0, B.P['band'][0], 1), (1, B.P['band'][1], 1)])))
        # the side's own parts
        if look == 'right':
            zc = (zb + zp) / 2
            out.append(B.side_key(*S.box(ROCKER[0] - 4 + sh, ROCKER[1] - 4 + sh, zc - 4.2, zc + 4.2)))
            m = (ROCKER[0] + ROCKER[1]) / 2 - 4 + sh
            out.append(B.cut('M%.2f %.2fL%.2f %.2f' % (S.pt(m, zc - 3) + S.pt(m, zc + 3))))
            out.append(B.side_key(*S.box(SHUTTER[0] - 4 + sh, SHUTTER[1] - 4 + sh, zc - 4.4, zc + 4.4), metal=True))
        else:
            x, y, w, h = S.box(CARD[0] - 4 + sh, CARD[1] - 4 + sh, zb + 2.8, zp - 2.8)
            out.append(B.door(x, y, w, h))
        out.append('</g>')
        out.append('<path d="%s" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".55"/>' % bpath)
        # the gap between the slabs, where the face slab lies on the back slab: dark, the slide inside
        g0, g1 = max(fy0, by0), min(fy1, cy)
        if g1 > g0:
            out.append(S.rect(g0, g1, zf - .2, zb + .2, '#000', 'opacity=".78"'))
        # the face slab
        out.append('<path d="%s" fill="%s"/>' % (fpath, body))
        cid = B.uid('sidef')
        out.append('<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)">' % (cid, fpath, cid))
        if opened:                                      # the underside's darker moulding shows at the back edge
            out.append(S.rect(fy0, fy1, zf - 1.1, zf, back, 'opacity=".9"'))
        out.append(S.rect(fy0, fy1, 0, band, S.grad((0, 0), (length, 0), [(0, B.P['band'][0], 1), (1, B.P['band'][1], 1)])))
        out.append('</g><path d="%s" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".55"/>' % fpath)
    elif look == 'top':
        fs0, fs1 = FACE[0] - 4, FACE[2] - 4
        face_pts = [(fs0, 0, rf), (fs0, zf, ri), (fs1, zf, ri), (fs1, 0, rf)]
        back_pts = [(0, zb, ri), (length, zb, ri), (length, th, rr_), (0, th, rr_)]
        fpath, bpath = S.poly(face_pts), S.poly(back_pts)
        out.append('<path d="%s" fill="%s"/>' % (bpath, body))
        cid = B.uid('topb')
        out.append('<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)">' % (cid, bpath, cid))
        out.append(S.rect(0, length, zb, zp, back))
        out.append('<path d="M%.2f %.2fL%.2f %.2f" stroke="#000" stroke-opacity=".38" stroke-width=".5"/>' % (S.pt(0, zp) + S.pt(length, zp)))
        out.append('</g><path d="%s" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".55"/>' % bpath)
        out.append(S.rect(fs0 + 2, fs1 - 2, zf - .2, zb + .2, '#000', 'opacity=".78"'))
        out.append('<path d="%s" fill="%s"/>' % (fpath, body))
        cid = B.uid('topf')
        out.append('<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)">' % (cid, fpath, cid))
        out.append(S.rect(fs0, fs1, 0, band, B.P['band'][0]))
        out.append('</g><path d="%s" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".55"/>' % fpath)
    else:                                               # bottom: the chin's end, the rear shell folded round
        pts = [(0, 0, rf), (length, 0, rf), (length, th, rr_), (0, th, rr_)]
        bpath = S.poly(pts)
        out.append('<path d="%s" fill="%s"/>' % (bpath, body))
        cid = B.uid('bot')
        out.append('<clipPath id="%s"><path d="%s"/></clipPath><g clip-path="url(#%s)">' % (cid, bpath, cid))
        out.append(S.rect(0, length, 0, band, B.P['band'][1]))
        out.append(B.port(length / 2, USB_Z * D.k, USB_C[0] * D.k, USB_C[1] * D.k, D.k))
        ex = B.W - EYELET[0] - 4                         # the eyelet's slot on the end, under the one on the back
        out.append(B.hole(ex, th - 6.2, 4.4, 2.4))
        out.append('</g><path d="%s" fill="none" stroke="#000" stroke-opacity=".32" stroke-width=".55"/>' % bpath)
    w, h = S.size
    head = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %g %g" width="%g" height="%g">' % (w, h, w, h),
            B.defs().replace('</defs>', extra_defs() + B.outside_defs() + ''.join(S.defs) + '</defs>')]
    return '\n'.join(head + [x for x in out if x] + ['</svg>']) + '\n'


def outside_jobs(skin):
    """(file name, drawing) for every picture of body3d: the back closed or open, the two layers, the sides."""
    jobs = []
    for v in skin['body3d']['views']:
        opened = v.get('state') != 'closed'
        if v['look'] == 'back':
            part = {'face': 'under', 'back': 'rear'}.get(v.get('layer'), 'all')
            jobs.append((v['image'], lambda part=part, opened=opened: draw_back(skin, part, opened)))
        else:
            jobs.append((v['image'], lambda look=v['look'], opened=opened: side(skin, look, opened)))
    return jobs


def main():
    skin = json.load(open(os.path.join(HERE, 'skin.json'), encoding='utf-8'))
    for variant in B.PALETTES:
        B.use(variant)
        colour = '' if variant == B.DEFAULT else '.' + variant
        vo = next(v for v in skin['views'] if v['id'] == skin['slide']['open'])
        jobs = [(v['image'], v, 'all') for v in skin['views']] + [(skin['slide'][p], vo, p) for p in ('base', 'face')]
        for image, view, part in jobs:
            name = image[:-4] + colour + '.svg'
            with open(os.path.join(HERE, name), 'w', encoding='utf-8') as f:
                f.write(draw(view, skin, part))
            print('wrote', name)
    # the outside, after the front, so that the front pictures stay as they were (the ids count on)
    if 'body3d' in skin:
        check_body3d(skin)
        for variant in B.PALETTES:
            B.use(variant)
            colour = '' if variant == B.DEFAULT else '.' + variant
            for image, make in outside_jobs(skin):
                name = image[:-4] + colour + '.svg'
                with open(os.path.join(HERE, name), 'w', encoding='utf-8') as f:
                    f.write(make())
                print('wrote', name)
    B.use(B.DEFAULT)


if __name__ == '__main__':
    main()
