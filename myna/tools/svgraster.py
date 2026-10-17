# SPDX-License-Identifier: MIT
"""A small SVG rasteriser in standard-library Python, for Myna's asset pipeline (myna/tools/mkassets.py).

It renders the subset of SVG that the project's design scripts (myna/assets/design) write, so that the build needs no
browser and no third-party library:
  - elements: svg (width, height, viewBox), g, path, rect (rx, ry), circle, ellipse, line, polyline, polygon, defs,
    linearGradient and radialGradient (objectBoundingBox or userSpaceOnUse units, stops with stop-color and
    stop-opacity, gradientTransform), use of url(#id) as fill or stroke;
  - path commands M L H V C S Q T A Z, absolute and relative;
  - transform: matrix, translate, scale, rotate (with a centre), skewX, skewY, nested;
  - presentation attributes (inherited through g): fill, stroke, stroke-width, stroke-linecap (butt, round, square),
    stroke-linejoin (miter, round, bevel), stroke-miterlimit, fill-rule, fill-opacity, stroke-opacity; opacity
    (a group of more than one paint is drawn into a layer first, as a browser does).

Coverage is computed with 16 sub-scanlines per pixel and exact horizontal coverage on each (nonzero or even-odd
winding), which is close to what a browser's analytic anti-aliasing gives. Strokes are turned into polygons: one quad
per segment, a wedge (round, mitred or bevelled) at each join, round or square caps; all pieces have the same
orientation, so the nonzero rule gives their union. Painting is source-over in premultiplied sRGB, as browsers do.

    canvas = render(svg_text, width, height)        # a Canvas
    canvas.rgba8()                                  # [(r, g, b, a), ...] 8-bit, not premultiplied
"""
import math
import re
import xml.etree.ElementTree as ET

SUB = 16                       # sub-scanlines per pixel row
TOL = 0.04                     # flattening tolerance in device pixels

NAMED = {'black': (0, 0, 0), 'white': (255, 255, 255), 'red': (255, 0, 0), 'green': (0, 128, 0), 'blue': (0, 0, 255),
         'gray': (128, 128, 128), 'grey': (128, 128, 128), 'yellow': (255, 255, 0), 'orange': (255, 165, 0)}


# ---------------------------------------------------------------- colours and numbers

def parse_colour(s):
    """'#rgb', '#rrggbb', 'rgb()', 'rgba()' or a name -> (r, g, b, a) in 0..1, or None for 'none'."""
    s = s.strip().lower()
    if s in ('none', 'transparent', ''):
        return None
    if s.startswith('#'):
        h = s[1:]
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0, 1.0)
    m = re.match(r'rgba?\(([^)]*)\)', s)
    if m:
        parts = [p.strip() for p in m.group(1).split(',')]
        rgb = [float(p[:-1]) * 2.55 if p.endswith('%') else float(p) for p in parts[:3]]
        a = float(parts[3]) if len(parts) > 3 else 1.0
        return (rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, a)
    if s in NAMED:
        r, g, b = NAMED[s]
        return (r / 255.0, g / 255.0, b / 255.0, 1.0)
    raise ValueError('colour not supported: %r' % s)


def num(s, default=0.0, ref=1.0):
    if s is None:
        return default
    s = s.strip()
    if s.endswith('%'):
        return float(s[:-1]) / 100.0 * ref
    if s.endswith('px'):
        s = s[:-2]
    return float(s)


_NUM = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


def numbers(s):
    return [float(v) for v in _NUM.findall(s)]


# ---------------------------------------------------------------- affine transforms (a, b, c, d, e, f)

IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mul(m, n):
    """m x n: apply n first, then m."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D, a * E + c * F + e, b * E + d * F + f)


def apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def invert(m):
    a, b, c, d, e, f = m
    det = a * d - b * c
    return (d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det)


def parse_transform(s):
    m = IDENT
    for name, args in re.findall(r'(\w+)\s*\(([^)]*)\)', s or ''):
        v = numbers(args)
        if name == 'matrix':
            t = tuple(v)
        elif name == 'translate':
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == 'scale':
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == 'rotate':
            r = math.radians(v[0])
            cs, sn = math.cos(r), math.sin(r)
            t = (cs, sn, -sn, cs, 0, 0)
            if len(v) == 3:
                t = mul(mul((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
        elif name == 'skewX':
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == 'skewY':
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            raise ValueError('transform not supported: %s' % name)
        m = mul(m, t)
    return m


# ---------------------------------------------------------------- geometry: shapes to subpaths in user space
# A path is a list of subpaths; a subpath is (points, closed), points in device space after flattening. Curves are
# flattened after the transform (affine maps keep Bezier curves Bezier), so the tolerance is in device pixels.

def _cubic(out, m, p0, p1, p2, p3):
    q0, q1, q2, q3 = apply(m, *p0), apply(m, *p1), apply(m, *p2), apply(m, *p3)
    # number of segments from the second differences (Wang's formula)
    dd = max(math.hypot(q0[0] - 2 * q1[0] + q2[0], q0[1] - 2 * q1[1] + q2[1]),
             math.hypot(q1[0] - 2 * q2[0] + q3[0], q1[1] - 2 * q2[1] + q3[1]))
    n = max(1, int(math.ceil(math.sqrt(0.75 * dd / TOL))))
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        out.append((a * q0[0] + b * q1[0] + c * q2[0] + d * q3[0], a * q0[1] + b * q1[1] + c * q2[1] + d * q3[1]))


def _arc(out, m, x1, y1, rx, ry, phi, large, sweep, x2, y2):
    """SVG endpoint arc to points (SVG 1.1 appendix F.6.5)."""
    if rx == 0 or ry == 0:
        out.append(apply(m, x2, y2))
        return
    rx, ry = abs(rx), abs(ry)
    cp, sp = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        k = math.sqrt(lam)
        rx, ry = rx * k, ry * k
    num_ = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num_ / den)) if den else 0.0
    if large == sweep:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx, cy = cp * cxp - sp * cyp + (x1 + x2) / 2, sp * cxp + cp * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    scale = math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))
    r_dev = max(rx, ry) * scale
    step = 2 * math.acos(max(-1.0, 1 - TOL / r_dev)) if r_dev > TOL else math.pi / 2
    n = max(2, int(math.ceil(abs(dt) / max(step, 1e-3))))
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        out.append(apply(m, cp * ex - sp * ey + cx, sp * ex + cp * ey + cy))


def path_d(d, m):
    """Flatten a path's d attribute under transform m; also returns the user-space bounding box of its points."""
    toks = re.findall(r'[MmLlHhVvCcSsQqTtAaZz]|' + _NUM.pattern, d)
    subs, pts = [], None
    x = y = sx = sy = 0.0
    lastc = lastq = None          # reflected control points for S and T
    user = []                     # user-space points (bounding box)
    i, cmd = 0, None

    def take(n):
        nonlocal i
        v = [float(t) for t in toks[i:i + n]]
        i += n
        return v

    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in 'Zz':
                if pts is not None:
                    subs.append((pts, True))
                    pts = None
                x, y = sx, sy
                lastc = lastq = None
                continue
        elif cmd is None:
            raise ValueError('path data starts with a number')
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if c == 'M':
            nx, ny = take(2)
            x, y = nx + ox, ny + oy
            if pts is not None:
                subs.append((pts, False))
            pts = [apply(m, x, y)]
            sx, sy = x, y
            user.append((x, y))
            cmd = 'l' if rel else 'L'      # further pairs are lines
            lastc = lastq = None
            continue
        if pts is None:                    # a drawing command after Z starts at the subpath's start
            pts = [apply(m, x, y)]
        if c == 'L':
            nx, ny = take(2)
            x, y = nx + ox, ny + oy
            pts.append(apply(m, x, y))
            lastc = lastq = None
        elif c == 'H':
            x = take(1)[0] + ox
            pts.append(apply(m, x, y))
            lastc = lastq = None
        elif c == 'V':
            y = take(1)[0] + oy
            pts.append(apply(m, x, y))
            lastc = lastq = None
        elif c in 'CS':
            if c == 'C':
                x1, y1, x2, y2, nx, ny = take(6)
                x1, y1 = x1 + ox, y1 + oy
            else:
                x2, y2, nx, ny = take(4)
                x1, y1 = (2 * x - lastc[0], 2 * y - lastc[1]) if lastc else (x, y)
            x2, y2, nx, ny = x2 + ox, y2 + oy, nx + ox, ny + oy
            _cubic(pts, m, (x, y), (x1, y1), (x2, y2), (nx, ny))
            user.extend(((x1, y1), (x2, y2)))
            lastc, lastq = (x2, y2), None
            x, y = nx, ny
        elif c in 'QT':
            if c == 'Q':
                qx, qy, nx, ny = take(4)
                qx, qy = qx + ox, qy + oy
            else:
                nx, ny = take(2)
                qx, qy = (2 * x - lastq[0], 2 * y - lastq[1]) if lastq else (x, y)
            nx, ny = nx + ox, ny + oy
            _cubic(pts, m, (x, y), (x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y)),
                   (nx + 2 / 3 * (qx - nx), ny + 2 / 3 * (qy - ny)), (nx, ny))
            user.append((qx, qy))
            lastq, lastc = (qx, qy), None
            x, y = nx, ny
        elif c == 'A':
            rx, ry, phi, large, sweep, nx, ny = take(7)
            nx, ny = nx + ox, ny + oy
            _arc(pts, m, x, y, rx, ry, phi, int(large), int(sweep), nx, ny)
            # the arc's extent: sample it in user space for the bounding box
            tmp = []
            _arc(tmp, IDENT, x, y, rx, ry, phi, int(large), int(sweep), nx, ny)
            user.extend(tmp)
            x, y = nx, ny
            lastc = lastq = None
        else:
            raise ValueError('path command not supported: %s' % cmd)
        user.append((x, y))
    if pts is not None:
        subs.append((pts, False))
    return subs, user


def bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def rect_d(x, y, w, h, rx, ry):
    if rx <= 0 and ry <= 0:
        return 'M%r %rH%rV%rH%rZ' % (x, y, x + w, y + h, x)
    rx, ry = (rx or ry), (ry or rx)
    rx, ry = min(rx, w / 2), min(ry, h / 2)
    return ('M%r %rH%rA%r %r 0 0 1 %r %rV%rA%r %r 0 0 1 %r %rH%rA%r %r 0 0 1 %r %rV%rA%r %r 0 0 1 %r %rZ'
            % (x + rx, y, x + w - rx, rx, ry, x + w, y + ry, y + h - ry, rx, ry, x + w - rx, y + h, x + rx, rx, ry,
               x, y + h - ry, y + ry, rx, ry, x + rx, y))


def ellipse_d(cx, cy, rx, ry):
    return ('M%r %rA%r %r 0 0 1 %r %rA%r %r 0 0 1 %r %rA%r %r 0 0 1 %r %rA%r %r 0 0 1 %r %rZ'
            % (cx + rx, cy, rx, ry, cx, cy + ry, rx, ry, cx - rx, cy, rx, ry, cx, cy - ry, rx, ry, cx + rx, cy))


# ---------------------------------------------------------------- strokes to polygons

def _dedupe(pts):
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
            out.append(p)
    return out


def _disc(cx, cy, r):
    n = max(8, int(math.ceil(2 * math.pi / (2 * math.acos(max(-1.0, 1 - TOL / max(r, TOL)))))))
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def stroke_polys(subs, hw, cap, join, miter_limit):
    """Polygons whose union is the stroke of the subpaths, half-width hw (device pixels)."""
    polys = []
    for pts, closed in subs:
        pts = _dedupe(pts)
        if closed and len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) < 1e-9 and abs(pts[0][1] - pts[-1][1]) < 1e-9:
            pts = pts[:-1]
        if len(pts) == 1:
            if cap == 'round':
                polys.append(_disc(pts[0][0], pts[0][1], hw))
            elif cap == 'square':
                x, y = pts[0]
                polys.append([(x - hw, y - hw), (x + hw, y - hw), (x + hw, y + hw), (x - hw, y + hw)])
            continue
        segs = list(zip(pts, pts[1:] + ([pts[0]] if closed else [])))
        dirs = []
        for (x0, y0), (x1, y1) in segs:
            ln = math.hypot(x1 - x0, y1 - y0)
            dirs.append(((x1 - x0) / ln, (y1 - y0) / ln))
        for ((x0, y0), (x1, y1)), (dx, dy) in zip(segs, dirs):
            nx, ny = -dy * hw, dx * hw
            polys.append([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)])
        # joins
        joints = range(len(segs)) if closed else range(1, len(segs))
        for j in joints:
            d1, d2 = dirs[j - 1], dirs[j]
            px, py = segs[j][0]
            cross = d1[0] * d2[1] - d1[1] * d2[0]
            dot = d1[0] * d2[0] + d1[1] * d2[1]
            if abs(cross) < 1e-9 and dot > 0:
                continue
            s = -1.0 if cross > 0 else 1.0           # the outer side of the turn
            n1 = (-d1[1] * hw * s, d1[0] * hw * s)
            n2 = (-d2[1] * hw * s, d2[0] * hw * s)
            if join == 'round':
                a1, a2 = math.atan2(n1[1], n1[0]), math.atan2(n2[1], n2[0])
                da = a2 - a1
                while da > math.pi:
                    da -= 2 * math.pi
                while da < -math.pi:
                    da += 2 * math.pi
                step = 2 * math.acos(max(-1.0, 1 - TOL / max(hw, TOL)))
                n = max(1, int(math.ceil(abs(da) / step)))
                poly = [(px, py)] + [(px + hw * math.cos(a1 + da * i / n), py + hw * math.sin(a1 + da * i / n))
                                     for i in range(n + 1)]
                polys.append(poly)
            else:
                poly = [(px, py), (px + n1[0], py + n1[1])]
                if join == 'miter':
                    half = math.acos(max(-1.0, min(1.0, -dot))) / 2      # half the angle between the segments
                    if half > 1e-6 and 1 / math.sin(half) <= miter_limit:
                        # the miter tip: along the bisector of the two normals
                        bx, by = n1[0] + n2[0], n1[1] + n2[1]
                        bl = math.hypot(bx, by)
                        if bl > 1e-9:
                            k = hw / math.sin(half) / bl
                            poly.append((px + bx * k, py + by * k))
                poly.append((px + n2[0], py + n2[1]))
                polys.append(poly)
        if not closed:
            for (x, y), (dx, dy), sign in ((pts[0], dirs[0], -1), (pts[-1], dirs[-1], 1)):
                if cap == 'round':
                    polys.append(_disc(x, y, hw))
                elif cap == 'square':
                    ex, ey = dx * hw * sign, dy * hw * sign
                    nx, ny = -dy * hw, dx * hw
                    polys.append([(x + nx, y + ny), (x + nx + ex, y + ny + ey), (x - nx + ex, y - ny + ey),
                                  (x - nx, y - ny)])
    out = []
    for p in polys:
        area = 0.0
        for (x0, y0), (x1, y1) in zip(p, p[1:] + p[:1]):
            area += x0 * y1 - x1 * y0
        if abs(area) < 1e-12:
            continue
        out.append(p if area > 0 else p[::-1])
    return out


# ---------------------------------------------------------------- coverage

class Mask:
    """Coverage 0..1 over the rows y0..y1 and columns x0..x1 (exclusive) of a canvas."""
    __slots__ = ('x0', 'y0', 'x1', 'y1', 'rows')

    def __init__(self, x0, y0, x1, y1, rows):
        self.x0, self.y0, self.x1, self.y1, self.rows = x0, y0, x1, y1, rows


def coverage(polys, width, height, evenodd=False):
    """The coverage of polygons (lists of points, device space) on a width x height canvas."""
    edges = []
    for p in polys:
        n = len(p)
        for i in range(n):
            x0, y0 = p[i]
            x1, y1 = p[(i + 1) % n]
            if y0 == y1:
                continue
            if y0 < y1:
                edges.append((y0, y1, x0, (x1 - x0) / (y1 - y0), 1))
            else:
                edges.append((y1, y0, x1, (x0 - x1) / (y0 - y1), -1))
    if not edges:
        return None
    edges.sort()
    ymin = max(0, int(math.floor(edges[0][0])))
    ymax = min(height, int(math.ceil(max(e[1] for e in edges))))
    xmin = max(0, int(math.floor(min(min(e[2], e[2] + e[3] * (e[1] - e[0])) for e in edges))))
    xmax = min(width, int(math.ceil(max(max(e[2], e[2] + e[3] * (e[1] - e[0])) for e in edges))))
    if ymin >= ymax or xmin >= xmax:
        return None
    w = xmax - xmin
    fw = float(xmax)
    fx0 = float(xmin)
    rows = []
    nxt, active = 0, []
    ne = len(edges)
    inv = 1.0 / SUB
    for row in range(ymin, ymax):
        cov = [0.0] * (w + 2)
        delta = [0] * (w + 2)
        any_ink = False
        for k in range(SUB):
            y = row + (k + 0.5) * inv
            while nxt < ne and edges[nxt][0] <= y:
                active.append(edges[nxt])
                nxt += 1
            if not active:
                continue
            active = [e for e in active if e[1] > y]
            if not active:
                continue
            xs = sorted([(e[2] + (y - e[0]) * e[3], e[4]) for e in active if e[0] <= y])
            wind = 0
            start = 0.0
            for x, d in xs:
                prev = wind
                if evenodd:
                    wind ^= 1
                else:
                    wind += d
                if prev == 0 and wind != 0:
                    start = x
                elif prev != 0 and wind == 0:
                    xa = (start if start > fx0 else fx0) - fx0
                    xb = (x if x < fw else fw) - fx0
                    if xb <= xa:
                        continue
                    any_ink = True
                    ia, ib = int(xa), int(xb)
                    if ia == ib:
                        cov[ia] += xb - xa
                    else:
                        cov[ia] += ia + 1 - xa
                        delta[ia + 1] += 1
                        delta[ib] -= 1
                        cov[ib] += xb - ib
        if not any_ink:
            rows.append(None)
            continue
        run = 0
        out = [0.0] * w
        for i in range(w):
            run += delta[i]
            c = (cov[i] + run) * inv
            out[i] = c if c < 1.0 else 1.0
        rows.append(out)
    return Mask(xmin, ymin, xmax, ymax, rows)


# ---------------------------------------------------------------- paint

class Gradient:
    def __init__(self, el, defs):
        self.kind = _tag(el)
        href = el.get('{http://www.w3.org/1999/xlink}href') or el.get('href')
        base = defs.get(href[1:]) if href else None
        self.units = el.get('gradientUnits') or (base.get('gradientUnits') if base is not None else None) \
            or 'objectBoundingBox'
        self.gt = parse_transform(el.get('gradientTransform') or '')
        stops_el = list(el) or (list(base) if base is not None else [])
        self.stops = []
        for s in stops_el:
            if not s.tag.endswith('stop'):
                continue
            style = dict(kv.split(':', 1) for kv in (s.get('style') or '').split(';') if ':' in kv)
            col = parse_colour(s.get('stop-color') or style.get('stop-color', 'black').strip())
            op = float(s.get('stop-opacity') or style.get('stop-opacity', '1'))
            off = num(s.get('offset'), 0.0)
            off = min(1.0, max(off, self.stops[-1][0] if self.stops else 0.0))
            a = col[3] * op
            self.stops.append((off, col[0] * a, col[1] * a, col[2] * a, a))      # premultiplied
        g = el.get
        if self.kind == 'linearGradient':
            self.p = (num(g('x1'), 0.0), num(g('y1'), 0.0), num(g('x2'), 1.0), num(g('y2'), 0.0))
        else:
            cx, cy, r = num(g('cx'), 0.5), num(g('cy'), 0.5), num(g('r'), 0.5)
            self.p = (cx, cy, r, num(g('fx'), cx), num(g('fy'), cy))

    def colour_at(self, t):
        st = self.stops
        if t <= st[0][0]:
            return st[0][1:]
        if t >= st[-1][0]:
            return st[-1][1:]
        for i in range(1, len(st)):
            if t <= st[i][0]:
                a, b = st[i - 1], st[i]
                span = b[0] - a[0]
                u = (t - a[0]) / span if span > 0 else 1.0
                return (a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u, a[3] + (b[3] - a[3]) * u,
                        a[4] + (b[4] - a[4]) * u)
        return st[-1][1:]

    def shader(self, ctm, box):
        """A function (device x, y) -> premultiplied (r, g, b, a) for a shape with user-space bounding box `box`."""
        m = ctm
        if self.units == 'objectBoundingBox':
            bx, by, bw, bh = box
            m = mul(m, (bw or 1e-9, 0, 0, bh or 1e-9, bx, by))
        m = mul(m, self.gt)
        inv = invert(m)
        a, b, c, d, e, f = inv
        # a lookup table of the stops, so a pixel costs a few multiplications
        n = 1024
        lut = [self.colour_at(i / (n - 1)) for i in range(n)]
        if self.kind == 'linearGradient':
            x1, y1, x2, y2 = self.p
            vx, vy = x2 - x1, y2 - y1
            ll = vx * vx + vy * vy or 1e-12
            ka, kb = vx / ll, vy / ll

            def at(x, y):
                u, v = a * x + c * y + e, b * x + d * y + f
                t = (u - x1) * ka + (v - y1) * kb
                i = int(t * (n - 1) + 0.5)
                return lut[0 if i < 0 else n - 1 if i >= n else i]
        else:
            cx, cy, r, fx, fy = self.p
            if abs(fx - cx) > 1e-9 or abs(fy - cy) > 1e-9:
                raise ValueError('radial gradients with a focal point are not supported')

            def at(x, y):
                u, v = a * x + c * y + e - cx, b * x + d * y + f - cy
                t = math.sqrt(u * u + v * v) / r
                i = int(t * (n - 1) + 0.5)
                return lut[n - 1 if i >= n else i]
        return at


class Canvas:
    """Premultiplied RGBA in floats 0..1, four planes."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.r = [0.0] * (w * h)
        self.g = [0.0] * (w * h)
        self.b = [0.0] * (w * h)
        self.a = [0.0] * (w * h)

    def paint(self, mask, shade, alpha):
        """Source-over of `shade` (a constant premultiplied colour or a function of the pixel centre) through mask."""
        if mask is None:
            return
        R, G, B, A, W = self.r, self.g, self.b, self.a, self.w
        const = not callable(shade)
        if const:
            sr, sg, sb, sa = shade
        for j, row in enumerate(mask.rows):
            if row is None:
                continue
            y = mask.y0 + j
            base = y * W + mask.x0
            yc = y + 0.5
            for i, c in enumerate(row):
                if c <= 0.0:
                    continue
                if not const:
                    sr, sg, sb, sa = shade(mask.x0 + i + 0.5, yc)
                k = c * alpha
                p = base + i
                ia = 1.0 - sa * k
                R[p] = sr * k + R[p] * ia
                G[p] = sg * k + G[p] * ia
                B[p] = sb * k + B[p] * ia
                A[p] = sa * k + A[p] * ia

    def composite(self, layer, alpha):
        """Source-over of another canvas of the same size, with a group opacity."""
        R, G, B, A = self.r, self.g, self.b, self.a
        for p in range(self.w * self.h):
            la = layer.a[p] * alpha
            if la <= 0.0:
                continue
            ia = 1.0 - la
            R[p] = layer.r[p] * alpha + R[p] * ia
            G[p] = layer.g[p] * alpha + G[p] * ia
            B[p] = layer.b[p] * alpha + B[p] * ia
            A[p] = la + A[p] * ia

    def rgba8(self):
        """8-bit, not premultiplied (r, g, b, a) tuples, rows top to bottom."""
        out = []
        for r, g, b, a in zip(self.r, self.g, self.b, self.a):
            if a <= 0.0:
                out.append((0, 0, 0, 0))
                continue
            ai = int(a * 255 + 0.5)
            if ai > 255:
                ai = 255
            out.append((min(255, int(r / a * 255 + 0.5)), min(255, int(g / a * 255 + 0.5)),
                        min(255, int(b / a * 255 + 0.5)), ai))
        return out

    def alpha(self):
        return list(self.a)


# ---------------------------------------------------------------- the document

INHERITED = ('fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit', 'fill-rule',
             'fill-opacity', 'stroke-opacity')
DEFAULTS = {'fill': 'black', 'stroke': 'none', 'stroke-width': '1', 'stroke-linecap': 'butt', 'stroke-linejoin': 'miter',
            'stroke-miterlimit': '4', 'fill-rule': 'nonzero', 'fill-opacity': '1', 'stroke-opacity': '1'}


def _tag(el):
    t = el.tag
    return t.split('}', 1)[1] if '}' in t else t


def _attrs(el):
    a = dict(el.attrib)
    style = el.get('style')
    if style:
        for kv in style.split(';'):
            if ':' in kv:
                k, v = kv.split(':', 1)
                a[k.strip()] = v.strip()
    return a


class Renderer:
    def __init__(self, root, width, height):
        self.w, self.h = width, height
        self.defs = {}
        for el in root.iter():
            if el.get('id') is not None:
                self.defs[el.get('id')] = el
        vb = root.get('viewBox')
        if vb:
            vx, vy, vw, vh = numbers(vb)
        else:
            vx, vy, vw, vh = 0.0, 0.0, num(root.get('width'), width), num(root.get('height'), height)
        self.root_m = mul((width / vw, 0, 0, height / vh, 0, 0), (1, 0, 0, 1, -vx, -vy))
        self.grads = {}

    def gradient(self, gid):
        if gid not in self.grads:
            self.grads[gid] = Gradient(self.defs[gid], self.defs)
        return self.grads[gid]

    def geometry(self, el, tag, m):
        a = el.get
        if tag == 'path':
            return path_d(a('d') or '', m)
        if tag == 'rect':
            x, y, w, h = num(a('x')), num(a('y')), num(a('width')), num(a('height'))
            if w <= 0 or h <= 0:
                return [], []
            rx, ry = num(a('rx'), 0.0), num(a('ry'), 0.0)
            return path_d(rect_d(x, y, w, h, rx, ry), m)[0], [(x, y), (x + w, y + h)]
        if tag in ('circle', 'ellipse'):
            cx, cy = num(a('cx')), num(a('cy'))
            if tag == 'circle':
                rx = ry = num(a('r'))
            else:
                rx, ry = num(a('rx')), num(a('ry'))
            if rx <= 0 or ry <= 0:
                return [], []
            return path_d(ellipse_d(cx, cy, rx, ry), m)[0], [(cx - rx, cy - ry), (cx + rx, cy + ry)]
        if tag == 'line':
            x1, y1, x2, y2 = num(a('x1')), num(a('y1')), num(a('x2')), num(a('y2'))
            return [([apply(m, x1, y1), apply(m, x2, y2)], False)], [(x1, y1), (x2, y2)]
        if tag in ('polyline', 'polygon'):
            v = numbers(a('points') or '')
            pts = list(zip(v[0::2], v[1::2]))
            return [([apply(m, x, y) for x, y in pts], tag == 'polygon')], pts
        return [], []

    def shade(self, paint, opacity, m, user_pts):
        if paint.startswith('url('):
            gid = paint[paint.index('#') + 1:paint.index(')')]
            return self.gradient(gid).shader(m, bbox(user_pts)), opacity
        c = parse_colour(paint)
        if c is None:
            return None, 0
        a = c[3]
        return (c[0] * a, c[1] * a, c[2] * a, a), opacity

    def draw_shape(self, canvas, el, tag, style, m):
        subs, user = self.geometry(el, tag, m)
        if not subs:
            return
        fill, stroke = style['fill'], style['stroke']
        if fill != 'none':
            sh, op = self.shade(fill, float(style['fill-opacity']), m, user)
            if sh is not None:
                polys = [p for p, _ in subs if len(p) > 2]
                canvas.paint(coverage(polys, self.w, self.h, style['fill-rule'] == 'evenodd'), sh, op)
        if stroke != 'none':
            sh, op = self.shade(stroke, float(style['stroke-opacity']), m, user)
            if sh is not None:
                scale = math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))
                hw = num(style['stroke-width']) * scale / 2
                if hw > 0:
                    polys = stroke_polys(subs, hw, style['stroke-linecap'], style['stroke-linejoin'],
                                         float(style['stroke-miterlimit']))
                    canvas.paint(coverage(polys, self.w, self.h), sh, op)

    def walk(self, canvas, el, style, m):
        tag = _tag(el)
        if tag in ('defs', 'linearGradient', 'radialGradient', 'stop', 'title', 'desc', 'metadata', 'pattern',
                   'clipPath', 'mask', 'filter'):
            return
        a = _attrs(el)
        if a.get('display') == 'none' or a.get('visibility') == 'hidden':
            return
        style = dict(style)
        for k in INHERITED:
            if k in a:
                style[k] = a[k]
        if 'transform' in a:
            m = mul(m, parse_transform(a['transform']))
        opacity = float(a.get('opacity', '1'))
        if opacity <= 0:
            return
        if tag in ('svg', 'g'):
            kids = list(el)
            if opacity < 1 and kids:
                layer = Canvas(self.w, self.h)
                for k in kids:
                    self.walk(layer, k, style, m)
                canvas.composite(layer, opacity)
            else:
                for k in kids:
                    self.walk(canvas, k, style, m)
            return
        if tag not in ('path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon'):
            raise ValueError('element not supported: %s' % tag)
        if opacity < 1:
            both = style['fill'] != 'none' and style['stroke'] != 'none'
            if both:
                layer = Canvas(self.w, self.h)
                self.draw_shape(layer, el, tag, style, m)
                canvas.composite(layer, opacity)
                return
            style['fill-opacity'] = str(float(style['fill-opacity']) * opacity)
            style['stroke-opacity'] = str(float(style['stroke-opacity']) * opacity)
        self.draw_shape(canvas, el, tag, style, m)


def render(svg, width, height, canvas=None):
    """Render an SVG document (text) at width x height pixels; onto `canvas` if given."""
    root = ET.fromstring(svg)
    r = Renderer(root, width, height)
    canvas = canvas or Canvas(width, height)
    style = dict(DEFAULTS)
    a = _attrs(root)
    for k in INHERITED:
        if k in a:
            style[k] = a[k]
    for k in root:
        r.walk(canvas, k, style, r.root_m)
    return canvas
