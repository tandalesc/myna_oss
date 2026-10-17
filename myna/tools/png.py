# SPDX-License-Identifier: MIT
"""Minimal PNG reading and writing with the standard library only (zlib), for Myna's asset pipeline and its checks.

An image is (width, height, pixels): pixels a flat list of (r, g, b, a) tuples, 8 bits each, rows top to bottom.
Reading supports what the build and the simulator write: 8-bit greyscale, grey + alpha, RGB, RGBA and palette images,
not interlaced, every filter type. Writing is always 8-bit RGBA.
"""
import struct
import zlib


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read(path):
    with open(path, 'rb') as f:
        data = f.read()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('%s: not a PNG file' % path)
    pos, idat, plte, trns = 8, [], None, None
    while pos < len(data):
        n, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b'IHDR':
            w, h, depth, ctype, _, _, interlace = struct.unpack('>IIBBBBB', body)
        elif kind == b'PLTE':
            plte = body
        elif kind == b'tRNS':
            trns = body
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            break
    if depth != 8 or interlace:
        raise ValueError('%s: only 8-bit, non-interlaced PNG is supported' % path)
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(b''.join(idat))
    stride = w * chans
    out, prev = [], bytearray(stride)
    for y in range(h):
        ft = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - chans] if i >= chans else 0
            b = prev[i]
            c = prev[i - chans] if i >= chans else 0
            if ft == 1:
                line[i] = (line[i] + a) & 255
            elif ft == 2:
                line[i] = (line[i] + b) & 255
            elif ft == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif ft == 4:
                line[i] = (line[i] + _paeth(a, b, c)) & 255
        prev = line
        for x in range(w):
            p = line[x * chans:(x + 1) * chans]
            if ctype == 0:
                out.append((p[0], p[0], p[0], 255))
            elif ctype == 2:
                out.append((p[0], p[1], p[2], 255))
            elif ctype == 3:
                i = p[0]
                alpha = trns[i] if trns and i < len(trns) else 255
                out.append((plte[3 * i], plte[3 * i + 1], plte[3 * i + 2], alpha))
            elif ctype == 4:
                out.append((p[0], p[0], p[0], p[1]))
            else:
                out.append((p[0], p[1], p[2], p[3]))
    return w, h, out


def write(path, w, h, pixels):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for r, g, b, a in pixels[y * w:(y + 1) * w]:
            raw += bytes((r, g, b, a))

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF)

    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))


def scale(w, h, pixels, k):
    """Pixels repeated k times in each direction (for looking at small images)."""
    out = []
    for y in range(h):
        row = []
        for p in pixels[y * w:(y + 1) * w]:
            row.extend([p] * k)
        for _ in range(k):
            out.extend(row)
    return w * k, h * k, out
