/* SPDX-License-Identifier: MIT */
/* Rectangles, fills and copies (gfx/gfx.h). */
#include <stdint.h>

#include "gfx/gfx.h"

static int max(int a, int b) { return a > b ? a : b; }
static int min(int a, int b) { return a < b ? a : b; }

int rect_intersect(struct rect *r, const struct rect *a, const struct rect *b)
{
    int x0 = max(a->x, b->x), y0 = max(a->y, b->y);
    int x1 = min(a->x + a->w, b->x + b->w), y1 = min(a->y + a->h, b->y + b->h);
    if (x1 <= x0 || y1 <= y0) {
        *r = (struct rect){ 0, 0, 0, 0 };
        return 0;
    }
    *r = (struct rect){ (int16_t)x0, (int16_t)y0, (int16_t)(x1 - x0), (int16_t)(y1 - y0) };
    return 1;
}

struct rect rect_union(const struct rect *a, const struct rect *b)
{
    if (rect_empty(a))
        return *b;
    if (rect_empty(b))
        return *a;
    int x0 = min(a->x, b->x), y0 = min(a->y, b->y);
    int x1 = max(a->x + a->w, b->x + b->w), y1 = max(a->y + a->h, b->y + b->h);
    return (struct rect){ (int16_t)x0, (int16_t)y0, (int16_t)(x1 - x0), (int16_t)(y1 - y0) };
}

void gfx_fill(const struct surface *s, const struct rect *r, uint16_t colour)
{
    struct rect all = { 0, 0, s->w, s->h }, c;
    if (!rect_intersect(&c, r, &all))
        return;
    uint16_t *row = s->pixels + c.y * s->stride + c.x;
    for (int y = 0; y < c.h; y++, row += s->stride)
        gfx_fill16(row, (uint32_t)c.w, colour);
}

void gfx_copy(const struct surface *dst, int x, int y, const struct surface *src, const struct rect *src_r)
{
    /* clip the source rectangle to the source, then its image at (x, y) to the destination */
    struct rect src_all = { 0, 0, src->w, src->h }, sr;
    if (!rect_intersect(&sr, src_r, &src_all))
        return;
    x += sr.x - src_r->x;
    y += sr.y - src_r->y;
    struct rect dst_all = { 0, 0, dst->w, dst->h }, want = { (int16_t)x, (int16_t)y, sr.w, sr.h }, dr;
    if (!rect_intersect(&dr, &want, &dst_all))
        return;
    const uint16_t *from = src->pixels + (sr.y + dr.y - y) * src->stride + sr.x + dr.x - x;
    uint16_t *to = dst->pixels + dr.y * dst->stride + dr.x;
    for (int i = 0; i < dr.h; i++, from += src->stride, to += dst->stride)
        gfx_copy16(to, from, (uint32_t)dr.w);
}
