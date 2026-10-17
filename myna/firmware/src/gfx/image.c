/* SPDX-License-Identifier: MIT */
/* Drawing the build-time images (gfx/image.h): copies for opaque ones, blends in the RGB565 spread form for the runs
 * with alpha and for coverage masks (the method of gfx/text.c: one multiply per blended pixel). */
#include <stdint.h>

#include "gfx/gfx.h"
#include "gfx/image.h"

/* 4-bit coverage to the 0..32 scale of the blend */
static const uint8_t alpha32[16] = { 0, 2, 4, 6, 9, 11, 13, 15, 17, 19, 21, 23, 26, 28, 30, 32 };

/* the part of the surface the image may touch: its box, the clip and the surface; 0 if nothing */
static int target(const struct surface *s, const struct rect *clip, const struct image *img, int x, int y,
                  struct rect *d)
{
    struct rect all = { 0, 0, s->w, s->h }, c, box = { (int16_t)x, (int16_t)y, (int16_t)img->w, (int16_t)img->h };
    if (!rect_intersect(&c, clip ? clip : &all, &all))
        return 0;
    return rect_intersect(d, &box, &c);
}

/* the runs of one row, limited to the columns [x0, x1) of the image; returns where the next row's ops and pixels
 * start through the pointers */
static void row_runs(uint16_t *dst, int x0, int x1, int w, const uint8_t **ops, const uint16_t **pix, int draw)
{
    const uint8_t *o = *ops;
    const uint16_t *p = *pix;
    int px = 0;
    while (px < w) {
        unsigned op = *o++, kind = op >> 6, n = (op & 63) + 1;
        if (kind == RUN_END)
            break;
        if (kind == RUN_SKIP) {
            px += (int)n;
            continue;
        }
        const uint8_t *alpha = o;
        if (kind == RUN_BLEND)
            o += n;
        if (draw) {
            int a = px > x0 ? px : x0, b = px + (int)n < x1 ? px + (int)n : x1;
            if (kind == RUN_COPY) {
                if (b > a)
                    gfx_copy16(dst + a, p + (a - px), (uint32_t)(b - a));
            } else {
                for (int i = a; i < b; i++)
                    dst[i] = gfx_blend(gfx_spread(p[i - px]), gfx_spread(dst[i]), alpha[i - px]);
            }
        }
        p += n;
        px += (int)n;
    }
    *ops = o;
    *pix = p;
}

void image_draw(const struct surface *s, const struct rect *clip, const struct image *img, int x, int y,
                uint16_t colour)
{
    x += img->x;
    y += img->y;
    struct rect d;
    if (!target(s, clip, img, x, y, &d))
        return;
    int i0 = d.x - x, i1 = i0 + d.w, j0 = d.y - y, j1 = j0 + d.h;
    uint16_t *row = s->pixels + d.y * s->stride + x;      /* column 0 of the image on row j0 */
    switch (img->format) {
    case IMAGE_RGB565: {
        const uint16_t *src = img->pixels + j0 * img->w + i0;
        for (int j = j0; j < j1; j++, row += s->stride, src += img->w)
            gfx_copy16(row + i0, src, (uint32_t)d.w);
        break;
    }
    case IMAGE_PAL8: {
        const uint8_t *src = img->data + j0 * img->w;
        for (int j = j0; j < j1; j++, row += s->stride, src += img->w)
            for (int i = i0; i < i1; i++)
                row[i] = img->pixels[src[i]];
        break;
    }
    case IMAGE_MASK4: {
        int row_bytes = (img->w + 1) >> 1;
        uint32_t fg = gfx_spread(colour);
        const uint8_t *src = img->data + j0 * row_bytes;
        for (int j = j0; j < j1; j++, row += s->stride, src += row_bytes)
            for (int i = i0; i < i1; i++) {
                unsigned a = (src[i >> 1] >> ((i & 1) << 2)) & 15;
                if (a == 15)
                    row[i] = colour;
                else if (a)
                    row[i] = gfx_blend(fg, gfx_spread(row[i]), alpha32[a]);
            }
        break;
    }
    case IMAGE_RUNS: {
        const uint8_t *ops = img->data;
        const uint16_t *pix = img->pixels;
        row -= j0 * s->stride;                             /* row 0 of the image */
        for (int j = 0; j < j1; j++, row += s->stride)
            row_runs(row, i0, i1, img->w, &ops, &pix, j >= j0);
        break;
    }
    }
}

void image_expand(const struct image *img, const struct surface *out)
{
    image_draw(out, 0, img, -img->x, -img->y, 0);
}
