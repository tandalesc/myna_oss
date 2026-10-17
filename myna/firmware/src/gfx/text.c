/* SPDX-License-Identifier: MIT */
/* Anti-aliased text from the glyph atlases (gfx/gfx.h, gfx/font.h).
 *
 * A glyph pixel holds 4 bits of coverage. Blending in RGB565 uses the usual spread form: the pixel is copied into
 * both halves of a word and masked to 0x07E0F81F, which puts green in the high half and red and blue in the low half
 * with at least five spare bits above each field, so (fg - bg) x alpha / 32 + bg works on all three fields with one
 * multiply. When the background colour is known (gfx_text) the 16 possible results are made once per call and each
 * pixel is a table load and a store. */
#include <stdint.h>

#include "gfx/gfx.h"

#define SPREAD 0x07E0F81Fu

static uint32_t spread(uint16_t c)
{
    return ((uint32_t)c | (uint32_t)c << 16) & SPREAD;
}

static uint16_t blend(uint32_t fg, uint32_t bg, uint32_t a32)
{
    uint32_t v = ((((fg - bg) * a32) >> 5) + bg) & SPREAD;
    return (uint16_t)(v | v >> 16);
}

/* 4-bit coverage to the 0..32 scale of blend(): round(a x 32 / 15) */
static const uint8_t alpha32[16] = { 0, 2, 4, 6, 9, 11, 13, 15, 17, 19, 21, 23, 26, 28, 30, 32 };

const struct font_glyph *font_glyph_of(const struct font *f, uint32_t c)
{
    unsigned i = FONT_NO_GLYPH;
    if (c < 256) {
        i = f->index[c];
    } else {
        /* a few ranges (Cyrillic, the typographic signs): a short walk */
        for (unsigned r = 0; r < f->range_count; r++)
            if (c - f->ranges[r].first < f->ranges[r].count) {
                i = f->ranges[r].glyph + (c - f->ranges[r].first);
                break;
            }
    }
    if (i == FONT_NO_GLYPH)
        i = f->index['?'];
    return i == FONT_NO_GLYPH ? 0 : &f->glyphs[i * f->phases];
}

int gfx_text_width(const struct font *f, const char *text)
{
    uint32_t pen = 0;
    for (const uint8_t *p = (const uint8_t *)text; *p;) {
        const struct font_glyph *g = font_glyph_of(f, gfx_utf8_next(&p));
        if (g)
            pen += g->advance;
    }
    return (int)((pen + 8) >> 4);
}

/* One glyph whose bitmap lies wholly inside the clip: no tests per pixel. With `lut` the pixel is lut[coverage];
 * without, it is blended with the surface. */
static void glyph_fast(const struct surface *s, const uint8_t *bits, int w, int h, int x, int y, const uint16_t *lut,
                       uint32_t fg)
{
    int row_bytes = (w + 1) >> 1;
    uint16_t *row = s->pixels + y * s->stride + x;
    for (int j = 0; j < h; j++, row += s->stride, bits += row_bytes) {
        uint16_t *d = row;
        for (int i = 0; i < row_bytes; i++, d += 2) {
            uint32_t b = bits[i];
            if (!b)
                continue;                      /* two empty pixels: the common case around a letter */
            uint32_t lo = b & 15, hi = b >> 4;  /* hi is 0 past the right edge of an odd-width glyph */
            if (lut) {
                if (lo)
                    d[0] = lut[lo];
                if (hi)
                    d[1] = lut[hi];
            } else {
                if (lo)
                    d[0] = lo == 15 ? (uint16_t)(fg | fg >> 16) : blend(fg, spread(d[0]), alpha32[lo]);
                if (hi)
                    d[1] = hi == 15 ? (uint16_t)(fg | fg >> 16) : blend(fg, spread(d[1]), alpha32[hi]);
            }
        }
    }
}

/* A glyph that crosses the clip: the same, limited to the clipped part */
static void glyph_clipped(const struct surface *s, const struct rect *c, const uint8_t *bits, int w, int h, int x,
                          int y, const uint16_t *lut, uint32_t fg)
{
    int row_bytes = (w + 1) >> 1;
    int i0 = c->x > x ? c->x - x : 0, i1 = c->x + c->w < x + w ? c->x + c->w - x : w;
    int j0 = c->y > y ? c->y - y : 0, j1 = c->y + c->h < y + h ? c->y + c->h - y : h;
    for (int j = j0; j < j1; j++) {
        uint16_t *row = s->pixels + (y + j) * s->stride + x;
        const uint8_t *src = bits + j * row_bytes;
        for (int i = i0; i < i1; i++) {
            uint32_t a = (src[i >> 1] >> ((i & 1) << 2)) & 15;
            if (!a)
                continue;
            if (lut)
                row[i] = lut[a];
            else
                row[i] = a == 15 ? (uint16_t)(fg | fg >> 16) : blend(fg, spread(row[i]), alpha32[a]);
        }
    }
}

static int draw(const struct surface *s, const struct rect *clip, const struct font *f, int x, int y,
                const char *text, uint16_t fg, const uint16_t *lut)
{
    struct rect all = { 0, 0, s->w, s->h }, c;
    if (!rect_intersect(&c, clip ? clip : &all, &all))
        return x + gfx_text_width(f, text);
    uint32_t fgs = spread(fg);
    uint32_t pen = (uint32_t)x << 4;           /* 1/16 pixel: the advances are fractional */
    for (const uint8_t *p = (const uint8_t *)text; *p;) {
        const struct font_glyph *g = font_glyph_of(f, gfx_utf8_next(&p));
        if (!g)
            continue;
        /* the pen to the nearest phase: a whole pixel and the bitmap made for the fraction */
        uint32_t ph = ((pen & 15) * f->phases + 8) >> 4, px = pen >> 4;
        if (ph == f->phases) {
            ph = 0;
            px++;
        }
        pen += g->advance;
        g += ph;
        int gx = (int)px + g->x, gy = y + g->y;
        if (!g->w)
            continue;
        const uint8_t *bits = f->bitmap + g->bitmap;
        if (gx >= c.x && gy >= c.y && gx + g->w <= c.x + c.w && gy + g->h <= c.y + c.h)
            glyph_fast(s, bits, g->w, g->h, gx, gy, lut, fgs);
        else if (gx < c.x + c.w && gy < c.y + c.h && gx + g->w > c.x && gy + g->h > c.y)
            glyph_clipped(s, &c, bits, g->w, g->h, gx, gy, lut, fgs);
    }
    return (int)((pen + 8) >> 4);
}

int gfx_text(const struct surface *s, const struct rect *clip, const struct font *f, int x, int y, const char *text,
             uint16_t fg, uint16_t bg)
{
    uint16_t lut[16];
    uint32_t fgs = spread(fg), bgs = spread(bg);
    for (int a = 0; a < 16; a++)
        lut[a] = blend(fgs, bgs, alpha32[a]);
    return draw(s, clip, f, x, y, text, fg, lut);
}

int gfx_text_over(const struct surface *s, const struct rect *clip, const struct font *f, int x, int y,
                  const char *text, uint16_t fg)
{
    return draw(s, clip, f, x, y, text, fg, 0);
}
