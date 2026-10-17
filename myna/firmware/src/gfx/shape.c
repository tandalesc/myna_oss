/* SPDX-License-Identifier: MIT */
/* Colour helpers, fills by row, translucent fills and anti-aliased rounded rectangles (gfx/gfx.h). */
#include <stdint.h>

#include "gfx/gfx.h"

#define MAX_RADIUS 16

uint16_t rgb565(uint32_t c)
{
    unsigned r = (c >> 16) & 255, g = (c >> 8) & 255, b = c & 255;
    r = (r * 31 + 127) / 255;
    g = (g * 63 + 127) / 255;
    b = (b * 31 + 127) / 255;
    return (uint16_t)(r << 11 | g << 5 | b);
}

uint32_t rgb_mix(uint32_t a, uint32_t b, unsigned t)
{
    uint32_t out = 0;
    for (int sh = 0; sh <= 16; sh += 8) {
        int ca = (int)((a >> sh) & 255), cb = (int)((b >> sh) & 255);
        out |= (uint32_t)((ca * 256 + (cb - ca) * (int)t + 128) >> 8) << sh;
    }
    return out;
}

static int clip_to(const struct surface *s, const struct rect *r, struct rect *c)
{
    struct rect all = { 0, 0, s->w, s->h };
    return rect_intersect(c, r, &all);
}

uint32_t rgb565_pair(uint32_t c, int y)
{
    /* thresholds of the 2 x 2 pattern, in quarters: row 0: 0 2, row 1: 3 1 */
    static const uint8_t t[2][2] = { { 0, 2 }, { 3, 1 } };
    uint32_t px[2];
    for (int x = 0; x < 2; x++) {
        unsigned th = t[y & 1][x];
        unsigned r = (c >> 16) & 255, g = (c >> 8) & 255, b = c & 255;
        /* level = floor(v x max / 255 + (th + 0.5) / 4), in integers */
        r = (r * 31 * 8 + (2 * th + 1) * 255) / (255 * 8);
        g = (g * 63 * 8 + (2 * th + 1) * 255) / (255 * 8);
        b = (b * 31 * 8 + (2 * th + 1) * 255) / (255 * 8);
        px[x] = r << 11 | g << 5 | b;
    }
    return px[0] | px[1] << 16;
}

void gfx_fill_rows(const struct surface *s, const struct rect *r, const uint32_t *pairs)
{
    struct rect c;
    if (!clip_to(s, r, &c))
        return;
    uint16_t *row = s->pixels + c.y * s->stride + c.x;
    pairs += c.y - r->y;
    for (int y = 0; y < c.h; y++, row += s->stride)
        gfx_fill32(row, (uint32_t)c.w, pairs[y]);
}

void gfx_blend_fill(const struct surface *s, const struct rect *r, uint16_t colour, unsigned a32)
{
    struct rect c;
    if (!clip_to(s, r, &c))
        return;
    if (a32 >= 32) {
        gfx_fill(s, &c, colour);
        return;
    }
    uint32_t fg = gfx_spread(colour);
    uint16_t *row = s->pixels + c.y * s->stride + c.x;
    for (int y = 0; y < c.h; y++, row += s->stride)
        for (int x = 0; x < c.w; x++)
            row[x] = gfx_blend(fg, gfx_spread(row[x]), a32);
}

/* Coverage of the pixels of a corner, 0..16 (4 x 4 samples), for a quarter disc of radius R whose centre is at (R, R)
 * of the R x R corner square (row j, column i, the corner's outer point at 0, 0); `inner` is the same for the disc of
 * radius R - 1 round the same centre (inside a 1 px border). Made once per radius. */
static uint8_t cov_outer[MAX_RADIUS + 1][MAX_RADIUS * MAX_RADIUS];
static uint8_t cov_inner[MAX_RADIUS + 1][MAX_RADIUS * MAX_RADIUS];
static uint8_t cov_made[MAX_RADIUS + 1];

static void make_corner(int R)
{
    int ro = 8 * R, ri = 8 * (R - 1);
    for (int j = 0; j < R; j++)
        for (int i = 0; i < R; i++) {
            int o = 0, n = 0;
            for (int sj = 0; sj < 4; sj++)
                for (int si = 0; si < 4; si++) {
                    int dx = ro - (8 * i + 2 * si + 1), dy = ro - (8 * j + 2 * sj + 1);
                    int d2 = dx * dx + dy * dy;
                    o += d2 <= ro * ro;
                    n += d2 <= ri * ri;
                }
            cov_outer[R][j * R + i] = (uint8_t)o;
            cov_inner[R][j * R + i] = (uint8_t)n;
        }
    cov_made[R] = 1;
}

static uint16_t corner_pixel(uint16_t under, int co, int ci, uint16_t fill, uint32_t border)
{
    if (border == GFX_NO_BORDER)
        return co >= 16 ? fill : gfx_blend(gfx_spread(fill), gfx_spread(under), (uint32_t)co * 2);
    uint16_t p = co >= 16 ? (uint16_t)border : gfx_blend(gfx_spread((uint16_t)border), gfx_spread(under), (uint32_t)co * 2);
    if (ci)
        p = gfx_blend(gfx_spread(fill), gfx_spread(p), (uint32_t)(ci * 32 / co));
    return p;
}

void gfx_round_rect(const struct surface *s, const struct rect *clip, const struct rect *r, int radius, uint16_t fill,
                    uint32_t border)
{
    struct rect all = { 0, 0, s->w, s->h }, c, d;
    if (!rect_intersect(&c, clip ? clip : &all, &all) || !rect_intersect(&d, r, &c))
        return;
    int R = radius;
    if (R > MAX_RADIUS)
        R = MAX_RADIUS;
    if (R > r->w / 2)
        R = r->w / 2;
    if (R > r->h / 2)
        R = r->h / 2;
    if (R > 0 && !cov_made[R])
        make_corner(R);
    int has_border = border != GFX_NO_BORDER;
    int cx0 = d.x, cx1 = d.x + d.w;                    /* clipped columns */
    for (int y = d.y; y < d.y + d.h; y++) {
        uint16_t *row = s->pixels + y * s->stride;
        int j = y - r->y;
        int qj = j < R ? j : j >= r->h - R ? r->h - 1 - j : -1;
        int edge_row = has_border && (j == 0 || j == r->h - 1);
        int m0 = r->x, m1 = r->x + r->w;               /* the middle span of this row */
        if (qj >= 0) {
            const uint8_t *co = &cov_outer[R][qj * R], *ci = &cov_inner[R][qj * R];
            for (int i = 0; i < R; i++) {
                int xl = r->x + i, xr = r->x + r->w - 1 - i;
                if (co[i]) {
                    if (xl >= cx0 && xl < cx1)
                        row[xl] = corner_pixel(row[xl], co[i], ci[i], fill, border);
                    if (xr >= cx0 && xr < cx1)
                        row[xr] = corner_pixel(row[xr], co[i], ci[i], fill, border);
                }
            }
            m0 += R;
            m1 -= R;
        } else if (has_border) {
            if (m0 >= cx0 && m0 < cx1)
                row[m0] = (uint16_t)border;
            if (m1 - 1 >= cx0 && m1 - 1 < cx1)
                row[m1 - 1] = (uint16_t)border;
            m0++;
            m1--;
        }
        if (m0 < cx0)
            m0 = cx0;
        if (m1 > cx1)
            m1 = cx1;
        if (m1 > m0)
            gfx_fill16(row + m0, (uint32_t)(m1 - m0), edge_row ? (uint16_t)border : fill);
    }
}
