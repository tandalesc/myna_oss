# SPDX-License-Identifier: MIT
"""The Myna menu icons, round 2: twelve small objects with depth, one family, drawn for this project on a 48 x 48 grid.

Family rules (STYLE.md):
  - one light from the upper left: every face runs from a lighter top to a darker bottom (a linear gradient of one hue);
  - a one-pixel outline in a darker tone of the object's own hue, so the shape holds at 40-56 px on a 165 ppi screen;
  - one thin highlight along the top edge of the main face, never a mirror reflection or a gloss sweep;
  - a soft contact shadow under the object;
  - the object fills a 36 x 36 live area centred in the 48 grid, and sits on a common baseline (y = 41).
The order is the keypad's: 1-9, then *, 0, #. Original work of the project (MIT, as the project).
"""
import importlib.util
import math
import os

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('myna_lettering', os.path.join(_here, 'lettering.py'))
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

MENU = [('messages', 'Messages'), ('contacts', 'Contacts'), ('calls', 'Calls'),
        ('camera', 'Camera'), ('photos', 'Photos'), ('music', 'Music'),
        ('radio', 'Radio'), ('alarm', 'Alarms'), ('calendar', 'Calendar'),
        ('notes', 'Notes'), ('web', 'Web'), ('settings', 'Settings')]
KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#']


class Ink:
    """Collects the gradients of one icon under a unique prefix."""

    def __init__(self, pid):
        self.pid, self.defs, self.n = pid, [], 0

    def lin(self, top, bottom, x1=0, y1=0, x2=0, y2=1):
        self.n += 1
        gid = '%s-g%d' % (self.pid, self.n)
        self.defs.append('<linearGradient id="%s" x1="%g" y1="%g" x2="%g" y2="%g"><stop offset="0" stop-color="%s"/>'
                         '<stop offset="1" stop-color="%s"/></linearGradient>' % (gid, x1, y1, x2, y2, top, bottom))
        return 'url(#%s)' % gid

    def rad(self, inner, outer, cx=.35, cy=.3, r=.8):
        self.n += 1
        gid = '%s-g%d' % (self.pid, self.n)
        self.defs.append('<radialGradient id="%s" cx="%g" cy="%g" r="%g"><stop offset="0" stop-color="%s"/>'
                         '<stop offset="1" stop-color="%s"/></radialGradient>' % (gid, cx, cy, r, inner, outer))
        return 'url(#%s)' % gid


def shadow(cx=24, w=15):
    return '<ellipse cx="%g" cy="42.3" rx="%g" ry="2.1" fill="#000" opacity=".16"/>' % (cx, w)


def face(d, fill, line, extra=''):
    return '<path d="%s" fill="%s" stroke="%s" stroke-width="1" stroke-linejoin="round" %s/>' % (d, fill, line, extra)


def rect(x0, y0, x1, y1, r):
    return ('M%g %gH%gA%g %g 0 0 1 %g %gV%gA%g %g 0 0 1 %g %gH%gA%g %g 0 0 1 %g %gV%gA%g %g 0 0 1 %g %gZ'
            % (x0 + r, y0, x1 - r, r, r, x1, y0 + r, y1 - r, r, r, x1 - r, y1, x0 + r, r, r, x0, y1 - r, y0 + r, r, r, x0 + r, y0))


def circle(cx, cy, r):
    return 'M%g %gA%g %g 0 1 0 %g %gA%g %g 0 1 0 %g %gZ' % (cx - r, cy, r, r, cx + r, cy, r, r, cx - r, cy)


def top_light(x0, x1, y, opacity=.7):
    """The thin highlight along the top edge of a face."""
    return '<path d="M%g %gH%g" stroke="#fff" stroke-opacity="%g" stroke-width="1" stroke-linecap="round"/>' % (x0, y, x1, opacity)


def messages(k):
    # an envelope with a round seal
    o = [shadow(), face(rect(7, 13, 41, 39, 3.5), k.lin('#fffaf0', '#e4d8bf'), '#a8987a'),
         '<path d="M8.5 15.5L24 28L39.5 15.5" fill="none" stroke="#a8987a" stroke-width="1.1" stroke-linejoin="round"/>',
         '<path d="M8.5 37.5L19.5 25.5M39.5 37.5L28.5 25.5" fill="none" stroke="#c9bb9c" stroke-width="1"/>',
         top_light(11, 37, 14.2), face(circle(24, 28.5, 4.6), k.lin('#ec6a4c', '#b8391f'), '#8f2a15'),
         '<circle cx="22.8" cy="27.2" r="1.3" fill="#fff" opacity=".45"/>']
    return o


def contacts(k):
    # an address card with a portrait and three lines
    o = [shadow(), face(rect(7, 10, 41, 39, 3.5), k.lin('#ffffff', '#dfe5eb'), '#94a2b0'), top_light(11, 37, 11.2),
         face(rect(10.5, 14, 25.5, 34, 2.5), k.lin('#cfe3f6', '#9fc0e2'), '#7b9cbf'),
         face('M18 17.5A3.6 3.6 0 1 1 18 24.7A3.6 3.6 0 1 1 18 17.5Z', k.lin('#4f7fbf', '#2f5c99'), '#244a7d'),
         face('M12 33.5C12 29 14.6 26.6 18 26.6C21.4 26.6 24 29 24 33.5Z', k.lin('#4f7fbf', '#2f5c99'), '#244a7d'),
         '<rect x="28.5" y="17" width="9" height="2.2" rx="1.1" fill="#9aa8b6"/>',
         '<rect x="28.5" y="22.5" width="9" height="2.2" rx="1.1" fill="#b9c4cf"/>',
         '<rect x="28.5" y="28" width="6" height="2.2" rx="1.1" fill="#b9c4cf"/>']
    return o


def calls(k):
    # a handset and two waves of sound
    hand = ('M13.2 9.5C14.3 8.4 16 8.4 17.1 9.5L20.6 13C21.7 14.1 21.7 15.8 20.6 16.9L18.3 19.2C19.9 22.9 22.8 25.8 26.5 27.4'
            'L28.8 25.1C29.9 24 31.6 24 32.7 25.1L36.2 28.6C37.3 29.7 37.3 31.4 36.2 32.5L33.6 35.1C31.4 37.3 28 37.9 25.3 36.4'
            'C18.6 32.7 13 27.1 9.3 20.4C7.8 17.7 8.4 14.3 10.6 12.1Z')
    o = [shadow(23, 13), face(hand, k.lin('#6fd17f', '#2c8a43', 0, 0, .3, 1), '#1f6b33'),
         '<path d="M12.3 11.6L14.6 9.4" stroke="#fff" stroke-opacity=".6" stroke-width="1.2" stroke-linecap="round"/>',
         '<path d="M27 9.8A11 11 0 0 1 37.4 20.2M26.5 15A6 6 0 0 1 32.2 20.7" fill="none" stroke="#2c8a43" '
         'stroke-width="2.2" stroke-linecap="round"/>']
    return o


def camera(k):
    # a compact camera: graphite body, silver lens ring, dark glass, a flash window
    o = [shadow(), face(rect(15, 10, 27, 16, 2), k.lin('#646a72', '#3a3f45'), '#22262b'),
         face(rect(6, 14, 42, 39, 5), k.lin('#5f656d', '#272b30'), '#1a1d21'), top_light(10, 38, 15.2, .45),
         face(circle(24, 27, 9.6), k.lin('#eef1f4', '#9aa2ab'), '#5d656e'),
         face(circle(24, 27, 6.6), k.rad('#3c6c9a', '#081420', .35, .3, .9), '#05090e'),
         '<circle cx="21.6" cy="24.6" r="1.7" fill="#fff" opacity=".55"/>',
         face(rect(32, 17.5, 38.5, 21.5, 1), k.lin('#fffbe6', '#e3dcb6'), '#8f8a6d')]
    return o


def photos(k):
    # two prints, the front one a landscape
    o = [shadow(),
         '<g transform="rotate(-9 22 25)">%s</g>' % face(rect(8, 10, 34, 34, 1.5), '#f3f4f6', '#a3abb3'),
         face(rect(13, 14, 41, 39, 1.5), k.lin('#ffffff', '#e9edf0'), '#97a1ab'),
         face(rect(15.5, 16.5, 38.5, 33.5, .5), k.lin('#7fc0ef', '#d6ecfb'), '#7fa7c7'),
         '<path d="M15.5 33.5V27.5L22 22.5L28 27L31.5 24.5L38.5 29.5V33.5Z" fill="%s" stroke="#3f7d3a" stroke-width=".8" '
         'stroke-linejoin="round"/>' % k.lin('#79c46a', '#3f8f3a'),
         '<circle cx="33" cy="21" r="2.6" fill="%s"/>' % k.lin('#ffe07a', '#f5b52e')]
    return o


def music(k):
    # a disc with a coloured label and a note on it
    o = [shadow(),
         face(circle(24, 24.5, 16), k.lin('#f4f6f9', '#b2bbc6', 0, 0, 1, 1), '#7c8794'),
         '<path d="M14 14.5A14 14 0 0 1 30 11.4" fill="none" stroke="#fff" stroke-opacity=".8" stroke-width="1.2" stroke-linecap="round"/>',
         '<path d="M36.5 31A14 14 0 0 1 22 38.4" fill="none" stroke="#c9b6e8" stroke-opacity=".9" stroke-width="1.6" stroke-linecap="round"/>',
         face(circle(24, 24.5, 8.6), k.lin('#9a6ae0', '#5c34a6'), '#46257f'),
         '<circle cx="24" cy="24.5" r="2.2" fill="#e9edf1" stroke="#7c8794" stroke-width=".8"/>',
         '<path d="M26.4 19V25.2" stroke="#fff" stroke-width="1.2"/><path d="M26.4 19C27.8 19.3 28.8 20.1 29.2 21.4" fill="none" '
         'stroke="#fff" stroke-width="1.1" stroke-linecap="round"/><circle cx="25.3" cy="25.6" r="1.4" fill="#fff"/>']
    return o


def radio(k):
    # a small transistor radio: red body, grille, tuning dial, antenna
    dots = ''.join('<circle cx="%g" cy="%g" r="1" fill="#6e1d14" opacity=".75"/>' % (11.5 + 3.4 * i, 22.5 + 3.4 * j)
                   for i in range(4) for j in range(4))
    o = [shadow(),
         '<path d="M13 15L8.5 5.5" stroke="#8d969f" stroke-width="1.6" stroke-linecap="round"/><circle cx="8.5" cy="5.5" r="1.6" fill="#b9c0c7"/>',
         face(rect(6, 15, 42, 39, 5), k.lin('#ef6b57', '#b73527'), '#86231a'), top_light(10, 38, 16.2, .55),
         face(rect(9.5, 19.5, 24.5, 35.5, 2), k.lin('#c9483a', '#a52d21'), '#86231a'), dots,
         face(circle(33.5, 27.5, 5.6), k.lin('#f2f4f6', '#a3abb4'), '#69727c'),
         '<path d="M33.5 27.5L36.2 24.6" stroke="#3a4048" stroke-width="1.3" stroke-linecap="round"/>']
    return o


def alarm(k):
    # a two-bell alarm clock
    o = [shadow(),
         face('M8.5 15A6 6 0 0 1 17.5 7.4Z', k.lin('#f6d36c', '#c99328'), '#94681a'),
         face('M39.5 15A6 6 0 0 0 30.5 7.4Z', k.lin('#f6d36c', '#c99328'), '#94681a'),
         '<path d="M15 39L12.5 42M33 39L35.5 42" stroke="#2c6f6a" stroke-width="2" stroke-linecap="round"/>',
         face(circle(24, 26, 14), k.lin('#4fbcb4', '#227a74'), '#185853'),
         face(circle(24, 26, 10.4), k.lin('#ffffff', '#e6ecee'), '#8fa3a6'),
         ''.join('<path d="M%g %gL%g %g" stroke="#7b8d90" stroke-width="1"/>' % (
             24 + 8.8 * math.sin(a), 26 - 8.8 * math.cos(a), 24 + 7.4 * math.sin(a), 26 - 7.4 * math.cos(a))
             for a in [i * math.pi / 6 for i in range(12)]),
         '<path d="M24 26V19.5M24 26L28.6 28.4" stroke="#263236" stroke-width="1.6" stroke-linecap="round"/>',
         '<circle cx="24" cy="26" r="1.3" fill="#d9483a"/>']
    return o


def calendar(k):
    # a tear-off block: red band, two rings, the day
    o = [shadow(), face(rect(7, 10, 41, 40, 4), k.lin('#ffffff', '#e1e6ea'), '#93a0ab'),
         '<path d="M7 18V14A4 4 0 0 1 11 10H37A4 4 0 0 1 41 14V18Z" fill="%s" stroke="#902a1f" stroke-width="1"/>' % k.lin('#ef6656', '#c23a2c'),
         top_light(11, 37, 11.2, .5),
         face(rect(13.5, 6.5, 17, 13.5, 1.5), k.lin('#545b63', '#2a2f35'), '#1c2025'),
         face(rect(31, 6.5, 34.5, 13.5, 1.5), k.lin('#545b63', '#2a2f35'), '#1c2025'),
         L.line('14', 24, 35.6, 12.5, '#2b3640', 0.75, 'middle', 1.2)]
    return o


def notes(k):
    # a yellow pad and a pencil
    lines = ''.join('<path d="M13 %gH33" stroke="#c99a2a" stroke-width=".8" opacity=".75"/>' % y for y in (19, 23.5, 28, 32.5))
    pencil = ('<g transform="rotate(-38 31 31)"><path d="M21 28.5H38.5V33.5H21Z" fill="%s" stroke="#a65e12" stroke-width=".8"/>'
              '<path d="M38.5 28.5H41.5V33.5H38.5Z" fill="#e7a0a0" stroke="#a65e12" stroke-width=".8"/>'
              '<path d="M21 28.5L16.5 31L21 33.5Z" fill="#f2d7a8" stroke="#a65e12" stroke-width=".8" stroke-linejoin="round"/>'
              '<path d="M17.8 30.3L16.5 31L17.8 31.7Z" fill="#33302b"/></g>') % k.lin('#ffb84d', '#e98a1c')
    o = [shadow(), face(rect(9, 9, 37, 40, 2.5), k.lin('#fff1a6', '#f4cf4c'), '#b58a1e'),
         '<path d="M9 14V11.5A2.5 2.5 0 0 1 11.5 9H34.5A2.5 2.5 0 0 1 37 11.5V14Z" fill="%s" stroke="#5a5048" stroke-width="1"/>' % k.lin('#7d746b', '#4d453e'),
         lines, pencil]
    return o


def web(k):
    # a globe on a small stand
    o = [shadow(24, 10),
         '<path d="M17 41H31" stroke="#6b737c" stroke-width="2.2" stroke-linecap="round"/><path d="M24 36V41" stroke="#6b737c" stroke-width="2"/>',
         face(circle(24, 22, 14), k.lin('#69b8f1', '#2a6cc0'), '#1d4f8f'),
         '<path d="M15.5 14.5C18 13 21 14.5 21.5 17C22 19.5 19 20.5 19.5 23C20 25.5 17.5 27.5 15 26.5C13 25 12.5 18 15.5 14.5Z" '
         'fill="%s" stroke="#2f6f2a" stroke-width=".7"/>' % k.lin('#88d07a', '#3f913a'),
         '<path d="M27 26C29.5 24.5 33 25.5 34 28C33 31.5 29.5 34.5 26.5 34C25.5 31.5 25 27.5 27 26Z" fill="%s" stroke="#2f6f2a" '
         'stroke-width=".7"/>' % k.lin('#88d07a', '#3f913a'),
         '<path d="M10.5 22H37.5M24 8.2C20 12 20 32 24 35.8M24 8.2C28 12 28 32 24 35.8" fill="none" stroke="#fff" stroke-opacity=".35" stroke-width=".8"/>',
         '<path d="M15.5 12.5A11.5 11.5 0 0 1 24 9.2" fill="none" stroke="#fff" stroke-opacity=".6" stroke-width="1.2" stroke-linecap="round"/>']
    return o


def settings(k):
    # a steel gear
    teeth, r0, r1, cx, cy = 8, 11.2, 15, 24, 24.5
    pts = []
    for i in range(teeth):
        a = 2 * math.pi * i / teeth
        for da, r in ((-0.2, r1), (0.2, r1), (0.27, r0), (2 * math.pi / teeth - 0.27, r0)):
            pts.append((cx + r * math.sin(a + da), cy - r * math.cos(a + da)))
    gear = 'M' + 'L'.join('%.2f %.2f' % p for p in pts) + 'Z'
    o = [shadow(), face(gear, k.lin('#d9dee3', '#7c858f', 0, 0, .4, 1), '#535b64'),
         face(circle(cx, cy, 7.4), k.lin('#9aa3ac', '#cfd5da'), '#5b636c'),
         face(circle(cx, cy, 3.4), k.lin('#3a4048', '#5d656e'), '#2a2f35')]
    return o


DRAW = {'messages': messages, 'contacts': contacts, 'calls': calls, 'camera': camera, 'photos': photos, 'music': music,
        'radio': radio, 'alarm': alarm, 'calendar': calendar, 'notes': notes, 'web': web, 'settings': settings}
_count = [0]


def icon(name, size=48):
    """One icon as an inline SVG, size pixels square."""
    _count[0] += 1
    k = Ink('i%d%s' % (_count[0], name[:3]))
    body = ''.join(DRAW[name](k))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%g" height="%g" viewBox="0 0 48 48"><defs>%s</defs>%s</svg>'
            % (size, size, ''.join(k.defs), body))
