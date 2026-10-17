/* SPDX-License-Identifier: MIT */
/* Images made at build time (myna/tools/mkassets.py) from the design's vector drawings: icons, wallpapers, the
 * selection tile, status-bar signs. The phone never rasterises a vector: it copies or blends these.
 *
 * Formats:
 *   IMAGE_RGB565  opaque, w x h pixels in `pixels`, rows top to bottom.
 *   IMAGE_PAL8    opaque, one byte per pixel in `data` (w x h), indexing `pixels` (palette_size colours).
 *   IMAGE_RUNS    RGB565 with alpha, in runs within each row. `data` is the op stream: one op byte per run,
 *                 bits 7-6 the kind, bits 5-0 the length less one (1-64 pixels); a run never crosses a row:
 *                   RUN_SKIP   n transparent pixels
 *                   RUN_COPY   n opaque pixels, the next n of `pixels`
 *                   RUN_BLEND  n partly covered pixels, the next n of `pixels`, and after the op byte n alpha bytes
 *                              (1-31, on the 0-32 scale of the blend: 32 would be opaque)
 *                   RUN_END    the rest of the row is transparent (the length bits are 0); a row whose runs reach w
 *                              has no RUN_END, a wholly transparent row is one RUN_END.
 *   IMAGE_MASK4   coverage only, drawn in a colour given at run time (a status sign takes the theme's colour):
 *                 (w + 1) / 2 bytes a row, two pixels a byte, the left one in the low nibble, 0 = none, 15 = full
 *                 (the glyph bitmap format of gfx/font.h).
 *
 * x, y place the image relative to the point it is drawn at: an image with a soft shadow round it (the selection tile)
 * has negative x, y, so that the point drawn at is the corner of its box, not of its shadow. */
#ifndef MYNA_GFX_IMAGE_H
#define MYNA_GFX_IMAGE_H

#include <stdint.h>

#include "gfx/gfx.h"

enum image_format { IMAGE_RGB565, IMAGE_PAL8, IMAGE_RUNS, IMAGE_MASK4 };
enum { RUN_SKIP = 0, RUN_COPY = 1, RUN_BLEND = 2, RUN_END = 3 };

struct image {
    uint16_t w, h;
    int8_t x, y;               /* offset of the image from the point it is drawn at */
    uint8_t format;            /* enum image_format */
    uint8_t reserved;
    uint16_t palette_size;     /* IMAGE_PAL8 */
    uint16_t reserved2;
    const uint16_t *pixels;    /* RGB565: the pixels (RGB565, RUNS) or the palette (PAL8) */
    const uint8_t *data;       /* PAL8 indices, RUNS ops, MASK4 coverage */
};

/* Draw img with its offset at (x, y), limited to clip (may be 0). Opaque formats are copied, RUNS are blended with what
 * the surface holds, MASK4 is blended in `colour` (ignored by the other formats). */
void image_draw(const struct surface *s, const struct rect *clip, const struct image *img, int x, int y,
                uint16_t colour);
/* Expand an opaque image (RGB565 or PAL8) into a surface of its size, for fast copies of its parts later. */
void image_expand(const struct image *img, const struct surface *out);

#endif
