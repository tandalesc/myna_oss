/* SPDX-License-Identifier: MIT */
/* 2D drawing into RGB565 surfaces with the CPU: rectangles, copies, anti-aliased text.
 *
 * Every call clips to the surface and to an optional clip rectangle, then works a row at a time with word stores
 * (gfx/blit_arm.S); there is no per-pixel function call anywhere. Text comes from the glyph atlases of gfx/font.h. */
#ifndef MYNA_GFX_GFX_H
#define MYNA_GFX_GFX_H

#include <stdint.h>

#include "gfx/font.h"

struct rect {
    int16_t x, y, w, h;
};

struct surface {
    uint16_t *pixels;          /* RGB565, little-endian, rows top to bottom */
    int16_t w, h;
    int16_t stride;            /* pixels from one row to the next */
};

/* 8-bit components to RGB565 (red 15:11, green 10:5, blue 4:0) */
#define RGB565(r, g, b) ((uint16_t)((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | ((b) >> 3)))

/* Colours of the design are 0xRRGGBB (themes keep them so, for exact gradients and mixes). To RGB565, rounded. */
uint16_t rgb565(uint32_t rgb);
/* The colour c on row y as a pair of pixels for gfx_fill_rows: a 2 x 2 ordered dither between the two RGB565 colours
 * nearest to it, so that a slow gradient has no bands. */
uint32_t rgb565_pair(uint32_t c, int y);
/* a + (b - a) x t / 256, per component: t = 0 gives a, 256 gives b */
uint32_t rgb_mix(uint32_t a, uint32_t b, unsigned t);

/* Blending in the RGB565 spread form (gfx/text.c): a pixel copied into both halves of a word and masked, so that each
 * field has spare bits above it and (fg - bg) x a / 32 + bg works on all three at once. a is 0..32. */
#define GFX_SPREAD 0x07E0F81Fu
static inline uint32_t gfx_spread(uint16_t c)
{
    return ((uint32_t)c | (uint32_t)c << 16) & GFX_SPREAD;
}
static inline uint16_t gfx_blend(uint32_t fg, uint32_t bg, uint32_t a32)
{
    uint32_t v = ((((fg - bg) * a32) >> 5) + bg) & GFX_SPREAD;
    return (uint16_t)(v | v >> 16);
}

/* r = a ∩ b; returns 0 when empty */
int rect_intersect(struct rect *r, const struct rect *a, const struct rect *b);
/* the smallest rectangle holding both (an empty one counts as nothing) */
struct rect rect_union(const struct rect *a, const struct rect *b);
static inline int rect_empty(const struct rect *r)
{
    return r->w <= 0 || r->h <= 0;
}

void gfx_fill(const struct surface *s, const struct rect *r, uint16_t colour);
/* A fill whose colour changes by row: row r->y + i takes pairs[i] (a vertical gradient made once). A pair is two
 * RGB565 pixels: the low half for even x, the high half for odd x, so that a gradient can be dithered (rgb565_pair). */
void gfx_fill_rows(const struct surface *s, const struct rect *r, const uint32_t *pairs);
/* a translucent fill: colour blended over what the surface holds, a32 = 0..32 */
void gfx_blend_fill(const struct surface *s, const struct rect *r, uint16_t colour, unsigned a32);
/* A rectangle with round corners of radius `radius` (0-16), anti-aliased over what the surface holds, filled with
 * `fill` and, if `border` is not GFX_NO_BORDER, edged with a 1 px line of that colour. Limited to clip (may be 0). */
#define GFX_NO_BORDER 0xFFFFFFFFu
void gfx_round_rect(const struct surface *s, const struct rect *clip, const struct rect *r, int radius, uint16_t fill,
                    uint32_t border);
/* copy `src_r` of `src` to (x, y) of `dst`, clipped to `dst` */
void gfx_copy(const struct surface *dst, int x, int y, const struct surface *src, const struct rect *src_r);

/* Text is UTF-8. One character at *p (a string ended by 0), and *p moved past it: a malformed sequence gives U+FFFD
 * and moves one byte (it never reads past the 0, which is no continuation byte). */
static inline uint32_t gfx_utf8_next(const uint8_t **p)
{
    const uint8_t *s = *p;
    uint32_t c = s[0];
    if (c < 0x80) {
        *p = s + 1;
        return c;
    }
    if (c >= 0xC2 && c < 0xE0 && (s[1] & 0xC0) == 0x80) {
        *p = s + 2;
        return (c & 0x1F) << 6 | (s[1] & 0x3F);
    }
    if (c >= 0xE0 && c < 0xF0 && (s[1] & 0xC0) == 0x80 && (s[2] & 0xC0) == 0x80) {
        uint32_t u = (c & 0x0F) << 12 | (uint32_t)(s[1] & 0x3F) << 6 | (s[2] & 0x3F);
        if (u >= 0x800 && (u < 0xD800 || u > 0xDFFF)) {
            *p = s + 3;
            return u;
        }
    } else if (c >= 0xF0 && c < 0xF5 && (s[1] & 0xC0) == 0x80 && (s[2] & 0xC0) == 0x80 && (s[3] & 0xC0) == 0x80) {
        uint32_t u = (c & 0x07) << 18 | (uint32_t)(s[1] & 0x3F) << 12 | (uint32_t)(s[2] & 0x3F) << 6 | (s[3] & 0x3F);
        if (u >= 0x10000 && u <= 0x10FFFF) {
            *p = s + 4;
            return u;
        }
    }
    *p = s + 1;
    return 0xFFFD;
}

/* Draw `text` (UTF-8) with its baseline at y, starting at x. Glyph pixels are blended between `fg` and `bg` by
 * their coverage, and pixels without ink are left alone: the caller fills the background first, with `bg`.
 * `clip` (may be 0) limits the drawing. Returns the pen position after the text, in pixels. */
int gfx_text(const struct surface *s, const struct rect *clip, const struct font *f, int x, int y, const char *text,
             uint16_t fg, uint16_t bg);
/* the same over any background: each pixel is blended with what the surface holds (slower) */
int gfx_text_over(const struct surface *s, const struct rect *clip, const struct font *f, int x, int y,
                  const char *text, uint16_t fg);

/* width of `text` in pixels (pen advance, rounded) */
int gfx_text_width(const struct font *f, const char *text);
/* the glyph of character c (a code point), the font's '?' for one it does not have, or 0 */
const struct font_glyph *font_glyph_of(const struct font *f, uint32_t c);

/* row loops, gfx/blit_arm.S */
void gfx_fill16(uint16_t *dst, uint32_t count, uint32_t colour);
void gfx_fill32(uint16_t *dst, uint32_t count, uint32_t pair);
void gfx_copy16(uint16_t *dst, const uint16_t *src, uint32_t count);

#endif
