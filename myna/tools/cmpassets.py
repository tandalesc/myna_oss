# SPDX-License-Identifier: MIT
"""cmpassets: compare the asset pipeline's renders (myna/tools/mkassets.py) with the design's own pictures.

    python3 -I myna/tools/cmpassets.py DESIGN_R2 OUTDIR

DESIGN_R2 is the design round's folder (with ui/png/pebble-menu.png, ui/png/pebble-standby.png and ui/icons.png, made
by a browser from the same drawings). For each icon, the selection tile and the wallpaper it prints the mean absolute
difference per channel (0-255), the largest difference and the PSNR, twice: for the rasteriser's 8-bit output, and
for what the phone shows (the firmware formats decoded again: RGB565, 5-bit alpha, the dithered wallpaper). It writes
side-by-side pictures (design | ours | difference x 4) into OUTDIR. A development check, not part of the build.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkassets  # noqa: E402
import png  # noqa: E402

M = mkassets


def over(fg, bg):
    r, g, b, a = fg
    return tuple((fg[i] * a + bg[i] * (255 - a) + 127) // 255 for i in range(3))


def stats(a, b):
    """a, b: lists of (r, g, b): mean absolute difference per channel, max, PSNR."""
    n = len(a)
    s = sq = 0
    mx = 0
    for p, q in zip(a, b):
        for i in range(3):
            d = abs(p[i] - q[i])
            s += d
            sq += d * d
            if d > mx:
                mx = d
    mse = sq / (3.0 * n)
    return s / (3.0 * n), mx, (99.0 if mse == 0 else 10 * math.log10(255 * 255 / mse))


def fmt(st):
    return 'mean %5.2f  max %3d  PSNR %5.1f dB' % st


class Pic:
    def __init__(self, w, h, px):
        self.w, self.h, self.px = w, h, [p[:3] for p in px]

    def get(self, x, y):
        return self.px[y * self.w + x]


def compose(base, layers):
    """A copy of base.px with layers [(x, y, w, h, function(bg_rgb, i, j) -> rgb)] drawn on it."""
    out = list(base.px)
    for x0, y0, w, h, f in layers:
        for j in range(h):
            for i in range(w):
                x, y = x0 + i, y0 + j
                if 0 <= x < base.w and 0 <= y < base.h:
                    out[y * base.w + x] = f(out[y * base.w + x], i, j)
    return out


def rgba_layer(px, w):
    return lambda bg, i, j: over(px[j * w + i], bg)


def runs_layer(img):
    """What the firmware draws for an IMAGE_RUNS image over whatever is there (RGB565 blend)."""
    w = img['w']
    cells = {}
    pix, data = img['pixels'], img['data']
    pi = di = 0
    for y in range(img['h']):
        x = 0
        while x < w:
            op = data[di]
            di += 1
            k, n = op >> 6, (op & 63) + 1
            if k == M.RUN_END:
                break
            for i in range(n):
                if k == M.RUN_COPY:
                    cells[(x + i, y)] = (pix[pi + i], 32)
                elif k == M.RUN_BLEND:
                    cells[(x + i, y)] = (pix[pi + i], data[di + i])
            if k != M.RUN_SKIP:
                pi += n
            if k == M.RUN_BLEND:
                di += n
            x += n

    def f(bg, i, j):
        c = cells.get((i, j))
        if c is None:
            return bg
        return M.rgb888(M.blend565(c[0], M.rgb565(*bg), c[1]))
    return f


def region(px, w, x0, y0, rw, rh):
    return [px[(y0 + j) * w + x0 + i] for j in range(rh) for i in range(rw)]


def side_by_side(path, w, h, a, b, x0=0, y0=0, rw=None, rh=None, k=3):
    rw, rh = rw or w, rh or h
    ra, rb = region(a, w, x0, y0, rw, rh), region(b, w, x0, y0, rw, rh)
    rd = [tuple(min(255, abs(p[i] - q[i]) * 4) for i in range(3)) for p, q in zip(ra, rb)]
    W = rw * 3 + 8
    out = []
    for j in range(rh):
        row = ra[j * rw:(j + 1) * rw] + [(255, 255, 255)] * 4 + rb[j * rw:(j + 1) * rw] + [(255, 255, 255)] * 4 + \
            rd[j * rw:(j + 1) * rw]
        out.extend(p + (255,) for p in row)
    png.write(path, *png.scale(W, rh, out, k))


def best_offset(mock, layer_px, w, h, x0, y0, search=3, bgf=None):
    """The offset (dx, dy) within +-search where the RGBA render over the mock's background matches best."""
    best = None
    for dy in range(-search, search + 1):
        for dx in range(-search, search + 1):
            s = 0
            for j in range(0, h):
                for i in range(0, w):
                    x, y = x0 + dx + i, y0 + dy + j
                    p = layer_px[j * w + i]
                    q = mock.get(x, y)
                    c = over(p, bgf(x, y))
                    s += abs(c[0] - q[0]) + abs(c[1] - q[1]) + abs(c[2] - q[2])
            if best is None or s < best[0]:
                best = (s, dx, dy)
    return best[1], best[2]


def main():
    if len(sys.argv) != 3:
        sys.exit('usage: cmpassets.py DESIGN_R2 OUTDIR')
    design, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    out = M.build()
    report = []

    # (a) the menu
    menu = Pic(*png.read(os.path.join(design, 'ui', 'png', 'pebble-menu.png')))
    bg_col = [menu.get(3, y) for y in range(menu.h)]       # the background gradient, left of every icon

    def bgf(x, y):
        return bg_col[y]
    report.append('Menu icons against ui/png/pebble-menu.png (42 px, focused Photos 50 px on the tile)')
    report.append('%-10s %-8s %-44s %s' % ('icon', 'offset', 'rasteriser (8-bit RGBA)', 'phone (RGB565, 5-bit alpha)'))
    i42, i50 = M.ICON_PX.index(42), M.ICON_PX.index(50)
    raster_layers, phone_layers = [], []
    tile = M.render_tile(M.tiles.TILES['pebble'])
    totals = []
    for n, (name, label) in enumerate(M.icons.MENU):
        cx, cy = (n % 3) * 80, 46 + (n // 3) * 62
        if n == 4:
            tpx, tw, th, tox, toy = tile
            tdx, tdy = best_offset(menu, tpx, tw, th, cx + 10 + tox, cy + 2 + toy, 2, bgf)
            ipx = M.render(M.icons.icon(name, 50), 50, 50).rgba8()
            layers_r = [(cx + 10 + tox + tdx, cy + 2 + toy + tdy, tw, th, rgba_layer(tpx, tw)),
                        (cx + 15 + tdx, cy + 6 + tdy, 50, 50, rgba_layer(ipx, 50))]
            layers_p = [(cx + 10 + tox + tdx, cy + 2 + toy + tdy, tw, th, runs_layer(out['tiles']['pebble'])),
                        (cx + 15 + tdx, cy + 6 + tdy, 50, 50, runs_layer(out['icons'][(i50, name)]))]
            box = (cx + 10 + tox + tdx, max(46, cy + 2 + toy + tdy), tw, th)
            off = (tdx, tdy)
        else:
            ipx = M.render(M.icons.icon(name, 42), 42, 42).rgba8()
            dx, dy = best_offset(menu, ipx, 42, 42, cx + 19, cy + 10, 3, bgf)
            layers_r = [(cx + 19 + dx, cy + 10 + dy, 42, 42, rgba_layer(ipx, 42))]
            layers_p = [(cx + 19 + dx, cy + 10 + dy, 42, 42, runs_layer(out['icons'][(i42, name)]))]
            box = (cx + 19 + dx, cy + 10 + dy, 42, 42)
            off = (dx, dy)
        raster_layers += layers_r
        phone_layers += layers_p
        # each icon alone over the background, against the mock, in its box
        base = Pic(menu.w, menu.h, [bg_col[i // menu.w] + (255,) for i in range(menu.w * menu.h)])
        a = compose(base, layers_r)
        b = compose(base, layers_p)
        bx, by, bw, bh = box
        bh = min(bh, menu.h - 26 - by)
        m_reg = region(menu.px, menu.w, bx, by, bw, bh)
        sr, sp = stats(m_reg, region(a, menu.w, bx, by, bw, bh)), stats(m_reg, region(b, menu.w, bx, by, bw, bh))
        totals.append((sr, sp))
        report.append('%-10s %+d,%+d    %-44s %s' % (label + (' +tile' if n == 4 else ''), off[0], off[1], fmt(sr), fmt(sp)))
    report.append('%-10s          %-44s %s' % ('mean', 'mean %5.2f, PSNR %5.1f dB (mean of icons)'
                                              % (sum(t[0][0] for t in totals) / 12, sum(t[0][2] for t in totals) / 12),
                                              'mean %5.2f, PSNR %5.1f dB' % (sum(t[1][0] for t in totals) / 12,
                                                                            sum(t[1][2] for t in totals) / 12)))
    # the whole grid area, the mock with its icons replaced by ours
    base = Pic(menu.w, menu.h, [bg_col[i // menu.w] + (255,) for i in range(menu.w * menu.h)])
    grid_r = compose(base, raster_layers)
    grid_p = compose(base, phone_layers)
    side_by_side(os.path.join(outdir, 'cmp-menu-raster.png'), menu.w, menu.h, menu.px, grid_r, 0, 46, 240, 248, 2)
    side_by_side(os.path.join(outdir, 'cmp-menu-phone.png'), menu.w, menu.h, menu.px, grid_p, 0, 46, 240, 248, 2)
    side_by_side(os.path.join(outdir, 'cmp-menu-zoom.png'), menu.w, menu.h, menu.px, grid_p, 0, 46, 240, 124, 4)
    report.append('whole grid (y 46-293): rasteriser %s; phone %s'
                  % (fmt(stats(region(menu.px, 240, 0, 46, 240, 248), region(grid_r, 240, 0, 46, 240, 248))),
                     fmt(stats(region(menu.px, 240, 0, 46, 240, 248), region(grid_p, 240, 0, 46, 240, 248)))))

    # (b) the icon sheet: 96 and 48 px on the light row
    sheet = Pic(*png.read(os.path.join(design, 'ui', 'icons.png')))
    bgc = sheet.get(2, 2)
    report.append('')
    report.append('Icon sheet ui/icons.png, light row (background #%02x%02x%02x), found by search' % bgc)
    s96, s48 = [], []
    ours96, ours48 = list(sheet.px), list(sheet.px)
    for n, (name, label) in enumerate(M.icons.MENU):
        line = '%-10s' % label
        for size, ylo, yhi, acc, canvas in ((96, 8, 30, s96, ours96), (48, 100, 130, s48, ours48)):
            px = M.render(M.icons.icon(name, size), size, size).rgba8()
            # coarse search on a sparse grid of the template, then a fine one
            centre = 87 + n * 154.6
            step = 4 if size == 96 else 3
            samples = [(i, j) for j in range(0, size, step) for i in range(0, size, step) if px[j * size + i][3] > 200]
            best = None
            for y in range(ylo, yhi):
                for x in range(int(centre - size / 2 - 20), int(centre - size / 2 + 20)):
                    s = 0
                    for i, j in samples:
                        p, q = px[j * size + i], sheet.get(x + i, y + j)
                        s += abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2])
                        if best is not None and s > best[0]:
                            break
                    if best is None or s < best[0]:
                        best = (s, x, y)
            _, x, y = best
            ours = [over(px[k], bgc) for k in range(size * size)]
            st = stats(region(sheet.px, sheet.w, x, y, size, size), ours)
            acc.append(st)
            for j in range(size):
                for i in range(size):
                    canvas[(y + j) * sheet.w + x + i] = ours[j * size + i]
            line += '  %d px at %4d,%3d: %s' % (size, x, y, fmt(st))
        report.append(line)
    report.append('mean      96 px: mean %5.2f, PSNR %5.1f dB; 48 px: mean %5.2f, PSNR %5.1f dB'
                  % (sum(s[0] for s in s96) / 12, sum(s[2] for s in s96) / 12, sum(s[0] for s in s48) / 12,
                     sum(s[2] for s in s48) / 12))
    side_by_side(os.path.join(outdir, 'cmp-icons96.png'), sheet.w, sheet.h, sheet.px, ours96, 0, 0, 940, 110, 1)
    side_by_side(os.path.join(outdir, 'cmp-icons48.png'), sheet.w, sheet.h, sheet.px, ours48, 0, 100, 940, 60, 2)

    # (c) the wallpaper, where nothing covers it on the standby screen
    standby = Pic(*png.read(os.path.join(design, 'ui', 'png', 'pebble-standby.png')))
    wr = [p[:3] for p in M.render(M.wallpapers.WALLPAPERS['dunes'](), 240, 320).rgba8()]
    wp = [M.rgb888(c) for c in M.decode(out['wallpapers']['dunes'], 0)]
    rows = list(range(21, 38)) + list(range(130, 293))
    a = [standby.get(x, y) for y in rows for x in range(240)]
    report.append('')
    report.append('Wallpaper dunes against ui/png/pebble-standby.png (rows 21-37 and 130-292: no bar, clock or date)')
    report.append('rasteriser (8-bit):      %s' % fmt(stats(a, [wr[y * 240 + x] for y in rows for x in range(240)])))
    report.append('phone (dithered RGB565): %s' % fmt(stats(a, [wp[y * 240 + x] for y in rows for x in range(240)])))
    side_by_side(os.path.join(outdir, 'cmp-wallpaper.png'), 240, 320, standby.px, wp, 0, 130, 240, 163, 2)

    text = '\n'.join(report) + '\n'
    with open(os.path.join(outdir, 'cmp-report.txt'), 'w') as f:
        f.write(text)
    sys.stdout.write(text)


if __name__ == '__main__':
    main()
