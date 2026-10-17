"""Compiled pixel conversions for the display model. Plain ctypes, no unicorn import.

The display model converts every panel refresh to RGB888: 25 pictures a second during video, up to 60 a second in a Java game.
In Python that costs 1 ms (RGB565 surface) to 6 ms (4:2:0 video plane) per refresh. The two loops here do the same arithmetic
on the same tables (the tables are built by lcd_model and passed in), so the bytes are identical; lcd_model keeps its Python
code and uses it when this helper is absent (no C compiler), when LCD_NATIVE=0, and for the cases the loops do not cover.
The helper is built on first use with `cc` into run/build/ (or SIM_BUILD_DIR) like emu/native_port.py.
`python -I native/emu_lcd/lcd_native.py` compares both paths on random input.
"""
import ctypes
import hashlib
import os
import subprocess
import sys
import tempfile

SRC = r'''
#include <stdint.h>
#include <stddef.h>
#include <string.h>

/* One update of the RGB layer (lcd_model._layer). Pixel i (< n) of line j (< rows) of the update comes from the source pixel at
   byte offset off + j * dj + i * di (di and dj may be negative: a turned surface is read up its columns) and goes to
   dst + j * dpitch + 3 * i. bytes = 2: RGB565 little endian, expansion of lcd_model.rgb565_to_rgb. bytes = 3 or 4: blue, green,
   red, and `bits` is what the panel keeps of each colour: 8, 6 (18 bits a pixel) or 5 (16 bits a pixel: 5, 6, 5). */
void lcd_layer(const uint8_t *src, ptrdiff_t off, ptrdiff_t di, ptrdiff_t dj, uint32_t bytes, uint32_t bits,
               uint8_t *dst, size_t dpitch, uint32_t n, uint32_t rows) {
    uint32_t i, j;
    for (j = 0; j < rows; j++) {
        const uint8_t *s = src + off + (ptrdiff_t)j * dj; uint8_t *d = dst + (size_t)j * dpitch;
        if (bytes == 2) {
            for (i = 0; i < n; i++, s += di, d += 3) {
                uint32_t v = s[0] | ((uint32_t)s[1] << 8), r = v >> 11, g = (v >> 5) & 63, b = v & 31;
                d[0] = (uint8_t)((r << 3) | (r >> 2)); d[1] = (uint8_t)((g << 2) | (g >> 4)); d[2] = (uint8_t)((b << 3) | (b >> 2));
            }
        } else if (bits == 6) {
            for (i = 0; i < n; i++, s += di, d += 3) {
                d[0] = (uint8_t)((s[2] & 0xfc) | (s[2] >> 6)); d[1] = (uint8_t)((s[1] & 0xfc) | (s[1] >> 6)); d[2] = (uint8_t)((s[0] & 0xfc) | (s[0] >> 6));
            }
        } else if (bits == 5) {
            for (i = 0; i < n; i++, s += di, d += 3) {
                d[0] = (uint8_t)((s[2] & 0xf8) | (s[2] >> 5)); d[1] = (uint8_t)((s[1] & 0xfc) | (s[1] >> 6)); d[2] = (uint8_t)((s[0] & 0xf8) | (s[0] >> 5));
            }
        } else {
            for (i = 0; i < n; i++, s += di, d += 3) { d[0] = s[2]; d[1] = s[1]; d[2] = s[0]; }
        }
    }
}

/* lcd_model._video_plane + yuv420_to_planes: planar 4:2:0 picture ow x oh (luma lines ls bytes apart, chroma lines cs), chroma
   repeated to twice its size, written into the w x h RGB888 image at (x0, y0) wherever the image is black.
   Tables (65536 bytes each): tr[y | v << 8], tb[y | u << 8], tgo[u | v << 8], tg[y | tgo << 8]. The caller checks 2 * cs >= ow. */
void lcd_yuv_plane(const uint8_t *yp, const uint8_t *up, const uint8_t *vp, uint32_t ow, uint32_t oh, uint32_t ls, uint32_t cs,
                   const uint8_t *tr, const uint8_t *tb, const uint8_t *tgo, const uint8_t *tg,
                   uint8_t *img, uint32_t w, uint32_t x0, uint32_t y0, uint32_t vw, uint32_t vh) {
    uint32_t row, i;
    for (row = 0; row < vh; row++) {
        const uint8_t *y = yp + (size_t)row * ls, *u = up + (size_t)(row / 2) * cs, *v = vp + (size_t)(row / 2) * cs;
        uint8_t *d = img + ((size_t)(y0 + row) * w + x0) * 3;
        for (i = 0; i < vw; i++, d += 3) {
            if (!(d[0] | d[1] | d[2])) {
                uint32_t Y = y[i], U = u[i / 2], V = v[i / 2];
                d[0] = tr[Y | (V << 8)]; d[1] = tg[Y | ((uint32_t)tgo[U | (V << 8)] << 8)]; d[2] = tb[Y | (U << 8)];
            }
        }
    }
}
'''

_lib = False


def load():
    """The compiled helper (ctypes library), or None if it is switched off (LCD_NATIVE=0) or cannot be built here."""
    global _lib
    if _lib is not False:
        return _lib
    _lib = None
    if os.environ.get('LCD_NATIVE', '1') == '0':
        return None
    try:
        build = os.environ.get('SIM_BUILD_DIR') or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'run', 'build')
        tag = hashlib.sha1((SRC + sys.platform + os.uname().machine).encode()).hexdigest()[:12]
        path = os.path.join(build, 'lcd_native-%s.%s' % (tag, 'dylib' if sys.platform == 'darwin' else 'so'))
        if not os.path.exists(path):
            os.makedirs(build, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=build) as tmp:
                c = os.path.join(tmp, 'lcd_native.c'); out = os.path.join(tmp, 'out')
                with open(c, 'w') as f:
                    f.write(SRC)
                subprocess.run([os.environ.get('CC', 'cc'), '-O2', '-shared', '-fPIC', '-o', out, c], check=True, capture_output=True, timeout=120)
                os.replace(out, path)
        lib = ctypes.CDLL(path)
        u32, sz, p = ctypes.c_uint32, ctypes.c_size_t, ctypes.c_char_p
        lib.lcd_layer.argtypes = [p, ctypes.c_ssize_t, ctypes.c_ssize_t, ctypes.c_ssize_t, u32, u32, ctypes.c_void_p, sz, u32, u32]; lib.lcd_layer.restype = None
        lib.lcd_yuv_plane.argtypes = [p, p, p, u32, u32, u32, u32, p, p, p, p, ctypes.c_void_p, u32, u32, u32, u32, u32]; lib.lcd_yuv_plane.restype = None
        _lib = lib
    except Exception:
        pass
    return _lib


def _ptr(buf):
    """Address of a bytearray's storage (the bytearray must stay alive and unresized during the call)."""
    return ctypes.addressof((ctypes.c_char * len(buf)).from_buffer(buf))


def layer(src, off, di, dj, nb, bits, img, w, x0, y0, n, rows):
    """One update of the RGB layer into the RGB888 bytearray `img` (lines of w pixels) at (x0, y0): `rows` lines of `n` pixels,
    pixel i of line j from the `nb` bytes at off + j * dj + i * di of `src` (bytes). bits: see lcd_layer above.
    False = not done (no helper, or a pixel lies outside the source or the image)."""
    lib = load()
    if lib is None or rows <= 0 or n <= 0 or nb not in (2, 3, 4) or x0 < 0 or y0 < 0 or x0 + n > w:
        return False
    ends = (off, off + (n - 1) * di, off + (rows - 1) * dj, off + (n - 1) * di + (rows - 1) * dj)
    if min(ends) < 0 or max(ends) + nb > len(src) or len(img) < ((y0 + rows - 1) * w + x0 + n) * 3:
        return False
    lib.lcd_layer(src, off, di, dj, nb, bits, _ptr(img) + (y0 * w + x0) * 3, w * 3, n, rows)
    return True


def yuv_plane(yp, up, vp, ow, oh, ls, cs, tables, img, w, h, x0, y0, vw, vh):
    """Blend the 4:2:0 picture into the RGB888 bytearray `img` where it is black. False = not done."""
    lib = load()
    ch = (oh + 1) // 2
    if (lib is None or 2 * cs < ow or vw <= 0 or vh <= 0 or vw > ow or vh > oh or len(yp) < (oh - 1) * ls + ow or len(up) < cs * ch or len(vp) < cs * ch
            or x0 + vw > w or y0 + vh > h or len(img) < w * h * 3):
        return False
    lib.lcd_yuv_plane(yp, up, vp, ow, oh, ls, cs, tables[0], tables[1], tables[2], tables[3], _ptr(img), w, x0, y0, vw, vh)
    return True


def selftest():
    """Both paths of lcd_model on random surfaces and pictures: every byte equal."""
    import random
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import lcd_model
    if load() is None:
        print('lcd_native: no compiled helper here (no C compiler, or LCD_NATIVE=0): nothing to compare'); return True
    rnd = random.Random(51); n = 0

    def both(make):
        global _lib
        lib = _lib
        a = make()
        _lib = None
        try: b = make()
        finally: _lib = lib
        return a, b

    for case in range(60):
        w, h = rnd.choice([(240, 320), (240, 320), (176, 220), (17, 9)])
        ram = bytearray(rnd.randbytes(0x100000))
        if case % 3 == 0: ram[0x2000:0x2000 + 0x40000] = bytes(0x40000)          # black surface: the picture shows everywhere
        elif case % 3 == 1:
            for k in range(0x2000, 0x42000, 2):                                   # black with holes
                if rnd.random() < 0.9: ram[k] = ram[k + 1] = 0
        def make():
            d = lcd_model.XgamDisplay(read_mem=lambda a, k: bytes(ram[a - 0x4A100000:a - 0x4A100000 + k]))
            d.panel_depth = True
            r = d.regs
            r[0x404] = 0x4A1; r[0x1440] = w | h << 16; r[0x1444] = 16; r[0x1458] = 16
            out = []
            # upright: whole surface, then partial updates on top of it (wider source than the panel, odd rectangles)
            sw = w + random.Random(case).choice([0, 0, 8])
            r[0x1450] = (1 << 20) + 0x2000; r[0x1454] = sw; r[0x1448] = 0; r[0x144c] = 0
            d.start_update(); out.append(d.last_frame)
            q = random.Random(case * 7 + 1)
            for _ in range(3):
                x, y = q.randrange(w), q.randrange(h)
                r[0x1448] = x | y << 16; r[0x144c] = q.randrange(1, w + 8) | q.randrange(1, h + 8) << 16
                d.start_update(); out.append(d.last_frame)
            # 24 and 32 bits a pixel at each output depth, upright and turned, whole and partial updates
            for bpp, depth in ((24, 0x12), (32, 0x12), (24, 0x10), (24, 0x18)):
                r[0x1458] = bpp; r[0x1444] = depth
                r[0x1460] = 0; r[0x1454] = sw; r[0x145c] = 0; r[0x1448] = 0; r[0x144c] = 0
                d.start_update(); out.append(d.last_frame)
                x, y = q.randrange(w), q.randrange(h)
                r[0x1448] = x | y << 16; r[0x144c] = q.randrange(1, w + 8) | q.randrange(1, h + 8) << 16
                d.start_update(); out.append(d.last_frame)
                r[0x1460] = 5; r[0x1454] = h; r[0x145c] = (w - 1) << 16; r[0x1448] = 0; r[0x144c] = 0
                d.start_update(); out.append(d.last_frame)
                x, y = q.randrange(w), q.randrange(h)
                r[0x1448] = x | y << 16; r[0x144c] = q.randrange(1, w + 8) | q.randrange(1, h + 8) << 16; r[0x145c] = (w - 1 - x) << 16 | y
                d.start_update(); out.append(d.last_frame)
            # turned 16-bit surface: a partial update, then the whole of it with the video plane (4:2:0, chroma line length = half or more)
            r[0x1458] = 16; r[0x1444] = 16
            d.start_update(); out.append(d.last_frame)
            r[0x1448] = 0; r[0x144c] = 0
            r[0x1460] = 5; r[0x1454] = h; r[0x145c] = (w - 1) << 16; r[0x1450] = (1 << 20) + 0x2000
            ow, oh = q.choice([(w, h), (w - 16, h - 32), (w | 1, h - 1)]) if w > 20 else (w, h)
            ow = min(ow, w)
            ls = ow + q.choice([0, 0, 4]); cs = (ow + 1) // 2 + q.choice([0, 2])
            r[0x1410] = 0x300; r[0x149c] = ow | oh << 16; r[0x1490] = ls; r[0x1494] = cs
            r[0x14a0] = q.choice([0, 0, 3 | 5 << 16]) if (ow, oh) != (w, h) and ow + 3 <= w and oh + 5 <= h else 0
            if case % 10 == 7: r[0x14a0] = q.choice([1992 << 16, (h - 20) << 16, w + 5, (w - 9) | 7 << 16])      # off the panel, or cut by its edge
            r[0x1478] = (1 << 20) + 0x50000; r[0x147c] = (1 << 20) + 0x80000; r[0x1480] = (1 << 20) + 0xa0000
            d.start_update(); out.append(d.last_frame)
            return out
        a, b = both(make)
        assert a == b, ('case', case, [i for i, (x, y) in enumerate(zip(a, b)) if x != y])
        n += len(a)
    print('lcd_native ok: %d pictures (upright, partial updates, turned, 16 / 24 / 32 bits, video plane) equal to the Python conversion byte for byte' % n)
    return True


if __name__ == '__main__':
    sys.exit(0 if selftest() else 1)
