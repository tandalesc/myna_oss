# SPDX-License-Identifier: MIT
"""mkassets: Myna's image pipeline. Renders the project's design drawings (myna/assets/design: icons, wallpapers,
selection tiles, status-bar signs) with the stdlib rasteriser myna/tools/svgraster.py and converts them into the
firmware's image formats (myna/firmware/src/gfx/image.h) as C source.

    python3 -I myna/tools/mkassets.py OUTDIR

writes OUTDIR/assets.c, OUTDIR/assets.h and OUTDIR/preview/*.png (what the phone will show: the generated data decoded
again, blended as the firmware blends). Standard library only; no browser. Run by myna/firmware/Makefile.

Conversions:
  - colours to RGB565 by rounding each component (a wallpaper first gets a 4 x 4 ordered dither, so its gradients do
    not band);
  - alpha to the 0-32 scale of the firmware's blend: 0 is skipped, 32 copied, the rest blended (IMAGE_RUNS); the
    transparent end of a row is one RUN_END;
  - an opaque picture with at most 256 colours after quantising is IMAGE_PAL8, else IMAGE_RGB565;
  - a one-colour sign keeps only its coverage, 4 bits a pixel (IMAGE_MASK4).
"""
import importlib.util
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DESIGN = os.path.join(os.path.dirname(HERE), 'assets', 'design')
sys.path.insert(0, HERE)
import png  # noqa: E402
import svgraster  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location('myna_design_' + name, os.path.join(DESIGN, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


icons = load('icons')
wallpapers = load('wallpapers')
tiles = load('tiles')
status = load('status')

ICON_IDS = ['MESSAGES', 'CONTACTS', 'CALLS', 'CAMERA', 'PHOTOS', 'MUSIC', 'RADIO', 'ALARM', 'CALENDAR', 'NOTES', 'WEB',
            'SETTINGS']
ICON_PX = (24, 42, 46, 50, 64)
WALLPAPERS = ('dunes', 'dunes_night')
LIVE = ('dunes', 'dunes_night')                 # the animated standby of these
TILES = ('pebble', 'pebble_night')

RUN_SKIP, RUN_COPY, RUN_BLEND, RUN_END = 0, 1, 2, 3
BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
ALPHA32 = (0, 2, 4, 6, 9, 11, 13, 15, 17, 19, 21, 23, 26, 28, 30, 32)       # 4-bit coverage -> 0..32 (gfx/text.c)


# ---------------------------------------------------------------- rendering

def render(svg, w, h):
    return svgraster.render(svg, w, h)


def blur(plane, w, h, sigma):
    """Separable Gaussian blur of a w x h plane of floats."""
    r = int(math.ceil(3 * sigma))
    k = [math.exp(-(i * i) / (2 * sigma * sigma)) for i in range(-r, r + 1)]
    s = sum(k)
    k = [v / s for v in k]
    tmp = [0.0] * (w * h)
    for y in range(h):
        row = plane[y * w:(y + 1) * w]
        for x in range(w):
            acc = 0.0
            for i, kv in enumerate(k):
                xx = x + i - r
                if 0 <= xx < w:
                    acc += row[xx] * kv
            tmp[y * w + x] = acc
    out = [0.0] * (w * h)
    for x in range(w):
        for y in range(h):
            acc = 0.0
            for i, kv in enumerate(k):
                yy = y + i - r
                if 0 <= yy < h:
                    acc += tmp[yy * w + x] * kv
            out[y * w + x] = acc
    return out


def render_tile(t):
    """A selection tile with its shadow: (rgba8 pixels, w, h, ox, oy), the box at (ox, oy) of the picture."""
    dx, dy, b, (sr, sg, sb, sa) = t['shadow']
    sigma = b / 2.0
    m = int(math.ceil(3 * sigma)) + max(abs(dx), abs(dy))
    w, h = t['w'] + 2 * m, t['h'] + 2 * m
    shape = render(tiles.shape_svg(t, w, h, m, m), w, h).alpha()
    moved = render(tiles.shape_svg(t, w, h, m + dx, m + dy), w, h).alpha()
    shadow = blur(moved, w, h, sigma)
    c = svgraster.Canvas(w, h)
    for p in range(w * h):
        a = shadow[p] * sa * (1.0 - shape[p])       # a box shadow is not drawn under its box
        c.r[p], c.g[p], c.b[p], c.a[p] = sr / 255.0 * a, sg / 255.0 * a, sb / 255.0 * a, a
    svgraster.render(tiles.face_svg(t, w, h, m, m), w, h, canvas=c)
    lr, lg, lb, la = t['light']
    down = render(tiles.shape_svg(t, w, h, m, m + 1), w, h).alpha()
    for p in range(w * h):
        a = max(0.0, shape[p] - down[p]) * la
        if a > 0:
            ia = 1 - a
            c.r[p] = lr / 255.0 * a + c.r[p] * ia
            c.g[p] = lg / 255.0 * a + c.g[p] * ia
            c.b[p] = lb / 255.0 * a + c.b[p] * ia
            c.a[p] = a + c.a[p] * ia
    return c.rgba8(), w, h, -m, -m


# ---------------------------------------------------------------- conversions

def rgb565(r, g, b):
    return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)


def a32(a):
    return (a * 32 + 127) // 255


def encode_runs(px, w, h, colours=None):
    """IMAGE_RUNS: (pixels, data). colours: the RGB565 value of each pixel (a dithered picture), else rounded."""
    pixels, data = [], bytearray()
    for y in range(h):
        row = px[y * w:(y + 1) * w]
        kinds = []
        for r, g, b, a in row:
            v = a32(a)
            kinds.append(RUN_SKIP if v == 0 else RUN_COPY if v >= 32 else RUN_BLEND)
        last = max((x for x in range(w) if kinds[x] != RUN_SKIP), default=-1)
        x = 0
        while x <= last:
            k = kinds[x]
            n = 1
            while x + n <= last and kinds[x + n] == k and n < 64:
                n += 1
            data.append(k << 6 | (n - 1))
            if k == RUN_BLEND:
                data.extend(a32(row[x + i][3]) for i in range(n))
            if k == RUN_COPY and colours:
                pixels.extend(colours[y * w + x + i] for i in range(n))
            elif k != RUN_SKIP:
                pixels.extend(rgb565(*row[x + i][:3]) for i in range(n))
            x += n
        if last < w - 1:
            data.append(RUN_END << 6)
    return pixels, bytes(data)


def dither565(px, w, h, y0=0):
    """4 x 4 ordered dither to RGB565; y0: the screen row of the first row (a strip keeps the screen's pattern)"""
    out = []
    for y in range(h):
        brow = BAYER[(y + y0) & 3]
        for x in range(w):
            r, g, b, _ = px[y * w + x]
            t = (brow[x & 3] + 0.5) / 16.0
            r5 = min(31, int(r * 31 / 255.0 + t))
            g6 = min(63, int(g * 63 / 255.0 + t))
            b5 = min(31, int(b * 31 / 255.0 + t))
            out.append(r5 << 11 | g6 << 5 | b5)
    return out


def encode_mask4(px, w, h):
    data = bytearray()
    for y in range(h):
        for x in range(0, w, 2):
            lo = (px[y * w + x][3] * 15 + 127) // 255
            hi = (px[y * w + x + 1][3] * 15 + 127) // 255 if x + 1 < w else 0
            data.append(lo | hi << 4)
    return bytes(data)


# ---------------------------------------------------------------- decoding (what the phone shows), for previews and checks

def rgb888(c):
    r, g, b = c >> 11, (c >> 5) & 63, c & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def blend565(fg, bg, a):
    """The firmware's blend (gfx/text.c): bg + (fg - bg) x a / 32 on each field, a in 0..32."""
    out = 0
    for shift, mask in ((11, 31), (5, 63), (0, 31)):
        f, b = (fg >> shift) & mask, (bg >> shift) & mask
        out |= ((b + (((f - b) * a) >> 5)) & mask) << shift
    return out


def decode(img, bg565, colour=0):
    """An image as RGB565 values over a uniform background bg565 (a list of w x h)."""
    w, h, fmt = img['w'], img['h'], img['format']
    if fmt == 'IMAGE_RGB565':
        return list(img['pixels'])
    if fmt == 'IMAGE_PAL8':
        pal = img['pixels']
        return [pal[i] for i in img['data']]
    out = [bg565] * (w * h)
    if fmt == 'IMAGE_MASK4':
        d = img['data']
        rb = (w + 1) // 2
        for y in range(h):
            for x in range(w):
                v = (d[y * rb + x // 2] >> (4 * (x & 1))) & 15
                if v:
                    out[y * w + x] = blend565(colour, bg565, ALPHA32[v])
        return out
    pix, data = img['pixels'], img['data']
    pi = di = 0
    for y in range(h):
        x = 0
        while x < w:
            op = data[di]
            di += 1
            k, n = op >> 6, (op & 63) + 1
            if k == RUN_END:
                break
            if k == RUN_COPY:
                for i in range(n):
                    out[y * w + x + i] = pix[pi + i]
                pi += n
            elif k == RUN_BLEND:
                for i in range(n):
                    out[y * w + x + i] = blend565(pix[pi + i], out[y * w + x + i], data[di + i])
                pi += n
                di += n
            x += n
    return out


# ---------------------------------------------------------------- the images

def image_runs(px, w, h, ox=0, oy=0):
    pixels, data = encode_runs(px, w, h)
    return {'w': w, 'h': h, 'x': ox, 'y': oy, 'format': 'IMAGE_RUNS', 'pixels': pixels, 'data': data}


def image_opaque(px, w, h, y0=0):
    v = dither565(px, w, h, y0)
    pal = sorted(set(v))
    if len(pal) <= 256:
        index = {c: i for i, c in enumerate(pal)}
        return {'w': w, 'h': h, 'x': 0, 'y': 0, 'format': 'IMAGE_PAL8', 'pixels': pal, 'data': bytes(index[c] for c in v)}
    return {'w': w, 'h': h, 'x': 0, 'y': 0, 'format': 'IMAGE_RGB565', 'pixels': v, 'data': b''}


def image_mask(svg, w, h):
    px = render(svg, w, h).rgba8()
    return {'w': w, 'h': h, 'x': 0, 'y': 0, 'format': 'IMAGE_MASK4', 'pixels': [], 'data': encode_mask4(px, w, h)}


def size_of(img):
    return 2 * len(img['pixels']) + len(img['data'])


def build():
    t0 = time.time()
    out = {'icons': {}, 'wallpapers': {}, 'tiles': {}, 'status': {}}
    for si, s in enumerate(ICON_PX):
        for name, _ in icons.MENU:
            px = render(icons.icon(name, s), s, s).rgba8()
            out['icons'][(si, name)] = image_runs(px, s, s)
    t1 = time.time()
    for name in WALLPAPERS:
        px = render(wallpapers.WALLPAPERS[name](), 240, 320).rgba8()
        out['wallpapers'][name] = image_opaque(px, 240, 320)
    t2 = time.time()
    for name in TILES:
        px, w, h, ox, oy = render_tile(tiles.TILES[name])
        out['tiles'][name] = image_runs(px, w, h, ox, oy)
    for lit in range(5):
        out['status'][('signal', lit)] = image_mask(status.signal(lit), 16, 10)
    for level in range(6):
        out['status'][('battery', level)] = image_mask(status.battery(level), 21, 10)
    out['status'][('message', 0)] = image_mask(status.envelope(), 13, 10)
    out['status'][('alarm', 0)] = image_mask(status.alarm(), 11, 10)
    for kind, w in (('lock', 9), ('silent', 11), ('meeting', 11), ('predict', 12)):
        out['status'][(kind, 0)] = image_mask(getattr(status, kind)(), w, 10)
    t3 = time.time()
    out['live'] = {name: build_live(name) for name in LIVE}
    out['times'] = (t1 - t0, t2 - t1, t3 - t2, time.time() - t3)
    return out


def build_live(name):
    """The animated standby (wallpapers.live): the sky alone over the rows that move, then each dune band as a strip
    of rows 240 px wide that repeats sideways (IMAGE_RUNS, its opaque pixels dithered as the still picture's). A band's
    strip ends where the next band covers every column, the last one at the soft-key bar (wallpapers.LIVE_BOTTOM)."""
    art = wallpapers.live(name)
    tops = [int(math.floor(lo)) for lo, _ in art['edges']]
    solids = [int(math.ceil(hi)) for _, hi in art['edges']]
    top, bottom = min(int(math.floor(art['still_top'])), tops[0]), wallpapers.LIVE_BOTTOM
    sky = render(art['sky'], 240, 320).rgba8()
    out = {'top': top, 'bottom': bottom, 'sky': image_opaque(sky[top * 240:solids[0] * 240], 240, solids[0] - top, top),
           'layers': [], 'layer_top': tops}
    for k, svg in enumerate(art['layers']):
        a, b = tops[k], solids[k + 1] if k + 1 < len(tops) else bottom
        px = render(svg, 240, 320).rgba8()[a * 240:b * 240]
        pixels, data = encode_runs(px, 240, b - a, dither565(px, 240, b - a, a))
        out['layers'].append({'w': 240, 'h': b - a, 'x': 0, 'y': 0, 'format': 'IMAGE_RUNS', 'pixels': pixels,
                              'data': data})
    return out


# ---------------------------------------------------------------- C output

def c_array(ctype, name, values, per_line=16, fmt='0x%02x', aligned=False):
    attr = ' __attribute__((aligned(4)))' if aligned else ''
    lines = []
    for i in range(0, len(values), per_line):
        lines.append('    ' + ', '.join(fmt % v for v in values[i:i + per_line]) + ',')
    return 'static const %s %s[]%s = {\n%s\n};\n' % (ctype, name, attr, '\n'.join(lines))


def c_image(img, cname):
    """(definitions of the arrays, the struct initialiser)"""
    defs = ''
    pix = data = '0'
    if img['pixels']:
        defs += c_array('uint16_t', cname + '_px', img['pixels'], 12, '0x%04x', aligned=True)
        pix = cname + '_px'
    if img['data']:
        defs += c_array('uint8_t', cname + '_data', list(img['data']))
        data = cname + '_data'
    init = ('{ .w = %d, .h = %d, .x = %d, .y = %d, .format = %s, .palette_size = %d, .pixels = %s, .data = %s }'
            % (img['w'], img['h'], img['x'], img['y'], img['format'],
               len(img['pixels']) if img['format'] == 'IMAGE_PAL8' else 0, pix, data))
    return defs, init


HEADER = '''/* SPDX-License-Identifier: MIT */
/* Generated by myna/tools/mkassets.py from the drawings in myna/assets/design: do not edit. */
#ifndef MYNA_GEN_ASSETS_H
#define MYNA_GEN_ASSETS_H

#include <stdint.h>

#include "gfx/image.h"

enum icon_id { ICON_MESSAGES, ICON_CONTACTS, ICON_CALLS, ICON_CAMERA, ICON_PHOTOS, ICON_MUSIC, ICON_RADIO,
               ICON_ALARM, ICON_CALENDAR, ICON_NOTES, ICON_WEB, ICON_SETTINGS, ICON_COUNT };   /* keypad order */
enum icon_size { ICON_24, ICON_42, ICON_46, ICON_50, ICON_64, ICON_SIZES };
extern const uint8_t icon_px[ICON_SIZES];                         /* 24, 42, 46, 50, 64 */
extern const struct image icon_images[ICON_SIZES][ICON_COUNT];    /* IMAGE_RUNS, x = y = 0, w = h = the size */
extern const struct image wallpaper_dunes, wallpaper_dunes_night; /* 240 x 320, opaque (IMAGE_PAL8 or IMAGE_RGB565) */
extern const struct image tile_pebble, tile_pebble_night;         /* IMAGE_RUNS with the shadow: drawn at (X, Y), the
                                                                     60 x 58 box is at (X, Y) */
extern const struct image status_signal[5];   /* IMAGE_MASK4 16 x 10: 0-4 bars lit, the others at 30 % */
extern const struct image status_battery[6];  /* IMAGE_MASK4 21 x 10: empty to full */
extern const struct image status_message;     /* IMAGE_MASK4 13 x 10: a new message */
extern const struct image status_alarm;       /* IMAGE_MASK4 11 x 10: an alarm is set */
extern const struct image status_lock;        /* IMAGE_MASK4 9 x 10: the keypad is locked */
extern const struct image status_silent;      /* IMAGE_MASK4 11 x 10: the Silent profile */
extern const struct image status_meeting;     /* IMAGE_MASK4 11 x 10: the Meeting profile (vibration) */
extern const struct image status_predict;     /* IMAGE_MASK4 12 x 10: predictive text, in a text box */

/* The animated standby of a wallpaper (src/ui/livewall.c): rows top..bottom of the screen move. The sky alone (`sky`,
 * opaque, rows top to top + sky->h: down to where the first band covers every column), over which each dune band is
 * copied at its own sideways offset, far to near. A band is an
 * IMAGE_RUNS strip 240 px wide whose picture repeats every 240 px, from row layer_top[k]; it ends where the next band
 * covers every column (the last one at `bottom`, where the soft-key bar starts). */
#define LIVEWALL_LAYERS 4
struct livewall_art {
    const struct image *sky;
    const struct image *layer[LIVEWALL_LAYERS];
    int16_t layer_top[LIVEWALL_LAYERS];
    int16_t top, bottom;
};
extern const struct livewall_art livewall_dunes, livewall_dunes_night;

#endif
'''


def write_c(out, outdir):
    parts = ['/* SPDX-License-Identifier: MIT */\n'
             '/* Generated by myna/tools/mkassets.py from the drawings in myna/assets/design: do not edit. */\n'
             '#include <stdint.h>\n\n#include "assets.h"\n#include "gfx/image.h"\n\n']
    parts.append('const uint8_t icon_px[ICON_SIZES] = { %s };\n\n' % ', '.join(str(s) for s in ICON_PX))
    inits = []
    for si, s in enumerate(ICON_PX):
        row = []
        for (name, _), cid in zip(icons.MENU, ICON_IDS):
            d, init = c_image(out['icons'][(si, name)], 'icon_%s_%d' % (name, s))
            parts.append(d)
            row.append('        [ICON_%s] = %s,' % (cid, init))
        inits.append('    [ICON_%d] = {\n%s\n    },' % (s, '\n'.join(row)))
    parts.append('\nconst struct image icon_images[ICON_SIZES][ICON_COUNT] = {\n%s\n};\n\n' % '\n'.join(inits))
    for name in WALLPAPERS:
        d, init = c_image(out['wallpapers'][name], 'wallpaper_%s' % name)
        parts.append(d + 'const struct image wallpaper_%s = %s;\n\n' % (name, init))
    for name in TILES:
        d, init = c_image(out['tiles'][name], 'tile_%s' % name)
        parts.append(d + 'const struct image tile_%s = %s;\n\n' % (name, init))
    for kind, count in (('signal', 5), ('battery', 6)):
        row = []
        for i in range(count):
            d, init = c_image(out['status'][(kind, i)], 'status_%s_%d' % (kind, i))
            parts.append(d)
            row.append('    ' + init + ',')
        parts.append('const struct image status_%s[%d] = {\n%s\n};\n\n' % (kind, count, '\n'.join(row)))
    for kind in ('message', 'alarm', 'lock', 'silent', 'meeting', 'predict'):
        d, init = c_image(out['status'][(kind, 0)], 'status_%s' % kind)
        parts.append(d + 'const struct image status_%s = %s;\n\n' % (kind, init))
    for name in LIVE:
        lv = out['live'][name]
        d, init = c_image(lv['sky'], 'live_%s_sky' % name)
        parts.append(d + 'static const struct image live_%s_sky = %s;\n' % (name, init))
        inits = []
        for k, img in enumerate(lv['layers']):
            d, init = c_image(img, 'live_%s_%d' % (name, k))
            parts.append(d)
            inits.append('    ' + init + ',')
        parts.append('static const struct image live_%s_layers[%d] = {\n%s\n};\n' % (name, len(inits), '\n'.join(inits)))
        parts.append('const struct livewall_art livewall_%s = {\n    .sky = &live_%s_sky,\n    .layer = { %s },\n'
                     '    .layer_top = { %s },\n    .top = %d, .bottom = %d,\n};\n\n'
                     % (name, name, ', '.join('&live_%s_layers[%d]' % (name, k) for k in range(len(inits))),
                        ', '.join(str(t) for t in lv['layer_top']), lv['top'], lv['bottom']))
    tmp = os.path.join(outdir, 'assets.c.tmp')
    with open(tmp, 'w') as f:
        f.write(''.join(parts))
    os.replace(tmp, os.path.join(outdir, 'assets.c'))
    with open(os.path.join(outdir, 'assets.h'), 'w') as f:
        f.write(HEADER)


# ---------------------------------------------------------------- previews

def sheet(path, tiles_, bgs, gap=6, scale=1):
    """tiles_: list of rows; each row a list of (w, h, rgb565 list over bg index) callables(bg565) -> (w, h, list)."""
    rows = []
    for bg in bgs:
        for row in tiles_:
            items = [f(bg) for f in row]
            rows.append((bg, items))
    W = max(sum(w for w, _, _ in items) + gap * (len(items) + 1) for _, items in rows)
    H = sum(max(h for _, h, _ in items) + gap for _, items in rows) + gap
    canvas = [None] * (W * H)
    y = gap
    for bg, items in rows:
        rh = max(h for _, h, _ in items)
        for p in range(y - gap, y + rh):
            for xx in range(W):
                canvas[p * W + xx] = bg
        x = gap
        for w, h, v in items:
            for j in range(h):
                for i in range(w):
                    canvas[(y + j) * W + x + i] = v[j * w + i]
            x += w + gap
        y += rh + gap
    for p in range(len(canvas)):
        if canvas[p] is None:
            canvas[p] = bgs[-1]
    px = [rgb888(c) + (255,) for c in canvas]
    if scale > 1:
        W, H, px = png.scale(W, H, px, scale)
    png.write(path, W, H, px)


def previews(out, outdir):
    d = os.path.join(outdir, 'preview')
    os.makedirs(d, exist_ok=True)
    light, dark = rgb565(0xf4, 0xef, 0xe6), rgb565(0x1d, 0x21, 0x29)

    def item(img, colour=0):
        return lambda bg: (img['w'], img['h'], decode(img, bg, colour))
    sheet(os.path.join(d, 'icons.png'),
          [[item(out['icons'][(si, n)]) for n, _ in icons.MENU] for si in range(len(ICON_PX))], [light, dark])
    sheet(os.path.join(d, 'wallpapers.png'), [[item(out['wallpapers'][n]) for n in WALLPAPERS]], [light])

    def tile_with_icon(name):
        t = out['tiles'][name]
        ic = out['icons'][(ICON_PX.index(50), 'photos')]

        def f(bg):
            w, h = t['w'], t['h']
            v = decode(t, bg)
            ox, oy = -t['x'] + 5, -t['y'] + 4
            # the icon over the tile, as the firmware draws it: run by run
            pix, data = ic['pixels'], ic['data']
            pi = di = 0
            for y in range(50):
                x = 0
                while x < 50:
                    op = data[di]
                    di += 1
                    k, n = op >> 6, (op & 63) + 1
                    if k == RUN_END:
                        break
                    for i in range(n):
                        p = (oy + y) * w + ox + x + i
                        if k == RUN_COPY:
                            v[p] = pix[pi + i]
                        elif k == RUN_BLEND:
                            v[p] = blend565(pix[pi + i], v[p], data[di + i])
                    if k != RUN_SKIP:
                        pi += n
                    if k == RUN_BLEND:
                        di += n
                    x += n
            return w, h, v
        return f
    sheet(os.path.join(d, 'tiles.png'), [[tile_with_icon(n) for n in TILES]], [rgb565(0xf6, 0xf1, 0xe9), dark], scale=2)
    ink, accent = rgb565(0x3b, 0x2e, 0x26), rgb565(0xc9, 0x60, 0x3e)
    signs = [out['status'][('signal', i)] for i in range(5)] + [out['status'][('battery', i)] for i in range(6)]
    for name in LIVE:
        lv, still = out['live'][name], out['wallpapers'][name]
        frames = [lambda bg, o=o: (240, 320, live_frame(lv, still, o)) for o in ((0, 0, 0, 0), (20, 40, 70, 110))]
        sheet(os.path.join(d, 'live_%s.png' % name), [[lambda bg: (240, 320, decode(still, 0))] + frames], [light])
    sheet(os.path.join(d, 'status.png'),
          [[item(s, ink) for s in signs] + [item(out['status'][('message', 0)], accent),
                                            item(out['status'][('alarm', 0)], ink)]
           + [item(out['status'][(k, 0)], ink) for k in ('lock', 'silent', 'meeting', 'predict')]],
          [rgb565(0xfb, 0xf6, 0xee)], scale=4)


def live_frame(lv, still, offsets):
    """a frame of the animated standby as the firmware composes it (RGB565 list of 240 x 320): the still picture, the
    sky over the rows that move, each band at its offset (its picture moved left by it)"""
    v = decode(still, 0)
    top, sky = lv['top'], lv['sky']
    v[top * 240:(top + sky['h']) * 240] = decode(sky, 0)
    for img, y0, off in zip(lv['layers'], lv['layer_top'], offsets):
        w, h = img['w'], img['h']
        pix, data = img['pixels'], img['data']
        pi = di = 0
        for y in range(h):
            if y0 + y >= lv['bottom']:
                break
            x = 0
            while x < w:
                op = data[di]
                di += 1
                k, n = op >> 6, (op & 63) + 1
                if k == RUN_END:
                    break
                for i in range(n):
                    p = (y0 + y) * 240 + (x + i - off) % 240
                    if k == RUN_COPY:
                        v[p] = pix[pi + i]
                    elif k == RUN_BLEND:
                        v[p] = blend565(pix[pi + i], v[p], data[di + i])
                if k != RUN_SKIP:
                    pi += n
                if k == RUN_BLEND:
                    di += n
                x += n
    return v


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: mkassets.py OUTDIR')
    outdir = sys.argv[1]
    os.makedirs(outdir, exist_ok=True)
    t0 = time.time()
    out = build()
    write_c(out, outdir)
    previews(out, outdir)
    groups = (('icons', out['icons'].values()), ('wallpapers', out['wallpapers'].values()),
              ('tiles', out['tiles'].values()), ('status signs', out['status'].values()),
              ('live', [i for lv in out['live'].values() for i in [lv['sky']] + lv['layers']]))
    total = 0
    for name, imgs in groups:
        imgs = list(imgs)
        n = sum(size_of(i) for i in imgs)
        total += n
        sys.stderr.write('mkassets: %-12s %3d images, %7d bytes\n' % (name, len(imgs), n))
    for name in WALLPAPERS:
        w = out['wallpapers'][name]
        sys.stderr.write('mkassets: wallpaper %s: %s, %d colours\n' % (name, w['format'], len(w['pixels'])))
    for name in LIVE:
        lv = out['live'][name]
        sys.stderr.write('mkassets: live %s: rows %d-%d, sky %s, bands from rows %s\n'
                         % (name, lv['top'], lv['bottom'], lv['sky']['format'], lv['layer_top']))
    sys.stderr.write('mkassets: total %d bytes; %.1f s (icons %.1f, wallpapers %.1f, tiles and signs %.1f, live %.1f)\n'
                     % (total, time.time() - t0, *out['times']))


if __name__ == '__main__':
    main()
