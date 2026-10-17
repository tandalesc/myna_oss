# SPDX-License-Identifier: MIT
"""The menu's selection tile of each theme: the shape under the focused icon (STYLE.md section 2, "Selection tile").

Original work of the project (MIT, as the project). Each tile is a box with a fill, an inset top light (CSS
`box-shadow: inset 0 1px <light>`: a band of 1 px along the inside of the top edge, clipped by the shape) and a soft
drop shadow (CSS `box-shadow: <dx> <dy> <blur> <colour>`, a Gaussian blur of standard deviation blur / 2). The asset
pipeline (myna/tools/mkassets.py) renders the face with face_svg(), the light and the shadow from shape_svg().

The values of Pebble are those of the round-2 mock-up (ui/mock.py); Pebble night is the dark variant of the theme.
"""

TILES = {
    'pebble': {'w': 60, 'h': 58, 'r': 15, 'top': '#e8916a', 'bottom': '#c9603e',
               'light': (255, 255, 255, .45), 'shadow': (0, 2, 5, (120, 50, 20, .35))},
    'pebble_night': {'w': 60, 'h': 58, 'r': 15, 'top': '#ee8f68', 'bottom': '#d96a45',
                     'light': (255, 255, 255, .35), 'shadow': (0, 2, 6, (0, 0, 0, .38))},
}


def _svg(w, h, body, defs=''):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d"><defs>%s</defs>%s</svg>'
            % (w, h, w, h, defs, body))


def shape_svg(t, w, h, ox, oy, fill='#fff'):
    """The tile's shape alone, its box at (ox, oy) of a w x h picture."""
    return _svg(w, h, '<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="%s"/>'
                % (ox, oy, t['w'], t['h'], t['r'], fill))


def face_svg(t, w, h, ox, oy):
    """The tile's face (its gradient), its box at (ox, oy) of a w x h picture."""
    defs = ('<linearGradient id="face" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s"/>'
            '<stop offset="1" stop-color="%s"/></linearGradient>' % (t['top'], t['bottom']))
    return _svg(w, h, '<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="url(#face)"/>'
                % (ox, oy, t['w'], t['h'], t['r']), defs)
