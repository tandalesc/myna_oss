# SPDX-License-Identifier: MIT
"""The status-bar signs: signal bars, battery, new message, alarm. Original work of the project (MIT, as the project).

Drawn in one colour; the firmware keeps only their coverage and paints them in the theme's colour at run time. The
signal bars, the battery and the envelope are the ones of the round-2 mock-ups (ui/mock.py: bars(), battery(),
envelope()); the alarm sign is drawn in the same line style (a small clock face with two bells).
"""

INK = '#000'


def _svg(w, h, body):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">%s</svg>'
            % (w, h, w, h, body))


def signal(lit):
    """16 x 10: four rising bars, `lit` of them full, the others at 30 %."""
    return _svg(16, 10, ''.join('<rect x="%g" y="%g" width="3" height="%g" rx=".8" fill="%s" opacity="%g"/>'
                                % (i * 4.3, 10 - (3 + i * 2.33), 3 + i * 2.33, INK, 1 if i < lit else .3)
                                for i in range(4)))


BATTERY_FILL = (0, 2.9, 5.8, 8.6, 11.5, 13.2)      # inner fill width per level 0-5 (level 4 is the mock-up's)


def battery(level):
    """21 x 10: an outline with a nub and an inner bar `BATTERY_FILL[level]` wide."""
    body = ('<rect x=".6" y=".6" width="17.4" height="8.8" rx="2" fill="none" stroke="%s" stroke-width="1.2"/>'
            '<rect x="18.6" y="3" width="1.8" height="4" rx=".6" fill="%s"/>' % (INK, INK))
    if BATTERY_FILL[level] > 0:
        body += '<rect x="2.4" y="2.4" width="%g" height="5.2" rx="1" fill="%s"/>' % (BATTERY_FILL[level], INK)
    return _svg(21, 10, body)


def envelope():
    """13 x 10: a new message."""
    return _svg(13, 10, '<rect x=".6" y=".6" width="11.8" height="8.8" rx="1.4" fill="none" stroke="%s" stroke-width="1.2"/>'
                '<path d="M1.2 1.4L6.5 5.6L11.8 1.4" fill="none" stroke="%s" stroke-width="1.1"/>' % (INK, INK))


def alarm():
    """11 x 10: an alarm is set (a clock face with two bells and its hands)."""
    return _svg(11, 10, '<circle cx="5.5" cy="5.6" r="3.6" fill="none" stroke="%s" stroke-width="1.2"/>'
                '<path d="M0.7 3.1A2.2 2.2 0 0 1 3.1 0.7Z M10.3 3.1A2.2 2.2 0 0 0 7.9 0.7Z" fill="%s"/>'
                '<path d="M5.5 3.7V5.7L6.9 6.5" fill="none" stroke="%s" stroke-width="1" stroke-linecap="round" '
                'stroke-linejoin="round"/>' % (INK, INK, INK))


def lock():
    """9 x 10: the keypad is locked (a padlock: a round shackle over a solid body with a keyhole)."""
    return _svg(9, 10, '<path d="M2.4 4.6V3.2A2.1 2.1 0 0 1 6.6 3.2V4.6" fill="none" stroke="%s" stroke-width="1.2"/>'
                '<path d="M2 4.4H7A1.2 1.2 0 0 1 8.2 5.6V8.4A1.2 1.2 0 0 1 7 9.6H2A1.2 1.2 0 0 1 .8 8.4V5.6'
                'A1.2 1.2 0 0 1 2 4.4Z M4 6.1H5V8H4Z" fill="%s" fill-rule="evenodd"/>' % (INK, INK))


def silent():
    """11 x 10: the Silent profile (a bell crossed out)."""
    return _svg(11, 10, '<path d="M2.6 7.4C3.4 6.6 3.3 5.6 3.3 4.4A2.2 2.2 0 0 1 7.7 4.4C7.7 5.6 7.6 6.6 8.4 7.4Z" '
                'fill="none" stroke="%s" stroke-width="1.1" stroke-linejoin="round"/>'
                '<path d="M4.6 8.6A1 1 0 0 0 6.4 8.6" fill="none" stroke="%s" stroke-width="1"/>'
                '<path d="M1.2 1.2L9.8 9.2" stroke="%s" stroke-width="1.2" stroke-linecap="round"/>' % (INK, INK, INK))


def meeting():
    """11 x 10: the Meeting profile (a phone that vibrates: a small handset between two pairs of strokes)."""
    return _svg(11, 10, '<rect x="3.6" y=".6" width="3.8" height="8.8" rx="1" fill="none" stroke="%s" stroke-width="1.1"/>'
                '<path d="M1.8 3V7M.4 4V6M9.2 3V7M10.6 4V6" stroke="%s" stroke-width=".9" stroke-linecap="round"/>'
                % (INK, INK))


def predict():
    """12 x 10: predictive text in a text box (an open book: two pages from a spine, a line of text on each)."""
    return _svg(12, 10, '<path d="M6 2.2C4.6 1.2 2.6 1 .8 1.4V8.6C2.6 8.2 4.6 8.4 6 9.4C7.4 8.4 9.4 8.2 11.2 8.6V1.4'
                'C9.4 1 7.4 1.2 6 2.2Z" fill="none" stroke="%s" stroke-width="1.1" stroke-linejoin="round"/>'
                '<path d="M6 2.4V9.2" stroke="%s" stroke-width=".9"/>'
                '<path d="M2.4 4.2C3.2 4.1 4 4.2 4.6 4.5M7.4 4.5C8 4.2 8.8 4.1 9.6 4.2M2.4 6.2C3.2 6.1 4 6.2 4.6 6.5'
                'M7.4 6.5C8 6.2 8.8 6.1 9.6 6.2" fill="none" stroke="%s" stroke-width=".8" stroke-linecap="round"/>'
                % (INK, INK, INK))
