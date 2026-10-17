/* SPDX-License-Identifier: MIT */
/* Glyph atlases: anti-aliased text rendered at build time (myna/tools/mkfont.c) from a TrueType file into C data.
 *
 * The phone never rasterises outlines: each size of each font is a fixed set of small 4-bit alpha bitmaps, one per
 * character, made on the build host. Sixteen levels of coverage are plenty on a 240 x 320 panel and halve the size of
 * the atlas compared with 8 bits. The build writes build/gen/fonts.c, which fills the structures below. */
#ifndef MYNA_GFX_FONT_H
#define MYNA_GFX_FONT_H

#include <stdint.h>

#define FONT_NO_GLYPH 0xFF     /* index[] value of a character the atlas does not have */

struct font_glyph {
    uint32_t bitmap;           /* byte offset of the first row in font.bitmap */
    uint8_t w, h;              /* bitmap size in pixels; 0 x 0 for a blank (space) */
    int8_t x, y;               /* top-left corner of the bitmap, from the pen on the baseline (y < 0 is above it) */
    uint16_t advance;          /* pen advance in 1/16 pixel: kept fractional so a line does not drift by rounding */
    uint16_t reserved;
};

/* a run of characters above U+00FF: first .. first + count - 1 are glyphs glyph .. glyph + count - 1 */
struct font_range {
    uint16_t first, count, glyph;
};

/* The entries of one glyph (one per phase) differ only in bitmap and box; the advance is the same.
 * Bitmap rows: (w + 1) / 2 bytes each, two pixels per byte, the left pixel in the low nibble; 0 = no ink, 15 = full. */
struct font {
    const char *name;
    uint8_t size;              /* em size in pixels */
    uint8_t ascent;            /* pixels above the baseline that the tallest letters reach (rounded up) */
    uint8_t descent;           /* pixels below it */
    uint8_t line_height;       /* baseline to baseline */
    uint8_t cap_height;        /* height of the ink of the digits (or of 'H'): what a layout centres on */
    uint8_t phases;            /* bitmaps per glyph: glyph i drawn with its pen p / phases of a pixel right of a whole
                                  pixel is glyphs[i x phases + p] (1: whole pixels only) */
    uint8_t index[256];       /* U+0000-00FF -> glyph number, or FONT_NO_GLYPH */
    uint8_t range_count;
    const struct font_range *ranges;   /* the characters above U+00FF, in ascending runs */
    uint16_t glyph_count;
    const struct font_glyph *glyphs;
    const uint8_t *bitmap;
};

#endif
