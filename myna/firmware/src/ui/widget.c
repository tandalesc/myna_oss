/* SPDX-License-Identifier: MIT */
/* Label and digit widgets, text helpers (ui/widget.h). */
#include <stdint.h>

#include "drivers/clock.h"
#include "drivers/display.h"
#include "lib/mem.h"
#include "services/settings.h"
#include "ui/ui.h"
#include "ui/widget.h"

static int continuation(char c)
{
    return ((uint8_t)c & 0xC0) == 0x80;
}

void copy_text(char *dst, const char *src, unsigned size)
{
    unsigned i = 0;
    for (; src[i] && i + 1 < size; i++)
        dst[i] = src[i];
    if (src[i])
        while (i > 0 && continuation(src[i]))
            i--;               /* cut: not inside a character */
    dst[i] = 0;
}

int text_prev(const char *text, int i)
{
    do
        i--;
    while (i > 0 && continuation(text[i]));
    return i;
}

int text_next(const char *text, int i)
{
    do
        i++;
    while (continuation(text[i]));
    return i;
}

int text_chars(const char *text, int len)
{
    int n = 0;
    for (int i = 0; i < len; i++)
        n += !continuation(text[i]);
    return n;
}

int format_uint(char *out, unsigned v)
{
    char tmp[12];
    int n = 0, k = 0;
    do
        tmp[n++] = (char)('0' + v % 10);
    while ((v /= 10) != 0);
    while (n)
        out[k++] = tmp[--n];
    out[k] = 0;
    return k;
}

int text_width_n(const struct font *f, const char *text, int len)
{
    uint32_t pen = 0;
    const uint8_t *p = (const uint8_t *)text, *end = p + len;
    while (p < end) {
        const struct font_glyph *g = font_glyph_of(f, gfx_utf8_next(&p));
        if (g)
            pen += g->advance;
    }
    return (int)((pen + 8) >> 4);
}

/* a piece of text[0..len) that fits buf (size bytes with the 0), ending at a character's start */
static int piece(const char *text, int len, int size)
{
    if (len < size)
        return len;
    int n = size - 1;
    while (n > 0 && continuation(text[n]))
        n--;
    return n;
}

void text_draw_n(const struct surface *s, const struct rect *clip, const struct font *f, int x, int y,
                 const char *text, int len, uint16_t fg)
{
    char buf[64];
    while (len > 0) {
        int n = piece(text, len, (int)sizeof buf);
        memcpy(buf, text, (size_t)n);
        buf[n] = 0;
        x = gfx_text_over(s, clip, f, x, y, buf, fg);
        text += n;
        len -= n;
    }
}

void text_draw_n_on(const struct surface *s, const struct rect *clip, const struct font *f, int x, int y,
                    const char *text, int len, uint16_t fg, uint16_t bg)
{
    char buf[64];
    while (len > 0) {
        int n = piece(text, len, (int)sizeof buf);
        memcpy(buf, text, (size_t)n);
        buf[n] = 0;
        x = gfx_text(s, clip, f, x, y, buf, fg, bg);
        text += n;
        len -= n;
    }
}

int text_wrap(const struct font *f, const char *text, int len, int width, uint16_t *starts, int max)
{
    int lines = 0, i = 0;
    starts[lines++] = 0;
    uint32_t pen = 0, limit = (uint32_t)width << 4;
    int line_start = 0, last_space = -1;
    while (i < len) {
        char c = text[i];
        if (c == '\n') {
            if (lines == max)
                break;
            starts[lines++] = (uint16_t)(i + 1);
            line_start = i + 1;
            last_space = -1;
            pen = 0;
            i++;
            continue;
        }
        const uint8_t *p = (const uint8_t *)text + i;
        const struct font_glyph *g = font_glyph_of(f, gfx_utf8_next(&p));
        uint32_t adv = g ? g->advance : 0;
        if (pen + adv > limit && c != ' ' && i > line_start) {
            if (lines == max)
                break;
            int brk = last_space >= line_start ? last_space + 1 : i;
            starts[lines++] = (uint16_t)brk;
            line_start = brk;
            last_space = -1;
            pen = 0;
            i = brk;
            continue;
        }
        if (c == ' ')
            last_space = i;
        pen += adv;
        i = (int)(p - (const uint8_t *)text);
    }
    return lines;
}

int text_centre_base(const struct rect *r, const struct font *f)
{
    return r->y + (r->h + f->cap_height) / 2;
}

void format_time(char *out, uint32_t seconds, int ampm)
{
    struct civil_time c;
    clock_civil(seconds, &c);
    int n = 0, h = c.hour;
    int h24 = settings_get(SET_TIME_24H);
    if (!h24) {
        h = h % 12 ? h % 12 : 12;
        if (h >= 10)
            out[n++] = '1';
    } else {
        out[n++] = (char)('0' + h / 10);
    }
    out[n++] = (char)('0' + h % 10);
    out[n++] = ':';
    out[n++] = (char)('0' + c.minute / 10);
    out[n++] = (char)('0' + c.minute % 10);
    if (!h24 && ampm) {
        out[n++] = ' ';
        out[n++] = c.hour < 12 ? 'A' : 'P';
        out[n++] = 'M';
    }
    out[n] = 0;
}

void label_set(struct label *l, const char *text)
{
    if (strcmp(l->text, text) == 0)
        return;
    copy_text(l->text, text, sizeof l->text);
    l->dirty = 1;
}

void label_touch(struct label *l)
{
    l->dirty = 1;
}

void label_paint(struct label *l, const struct surface *s)
{
    if (!l->dirty)
        return;
    l->dirty = 0;
    if (l->over)
        ui_backdrop(s, &l->r);
    else if (l->bg_rows)
        gfx_fill_rows(s, &l->r, l->bg_rows);
    else
        gfx_fill(s, &l->r, l->bg);
    if (l->text[0]) {
        int w = gfx_text_width(l->font, l->text);
        int x = l->align == ALIGN_LEFT ? l->r.x + l->pad
              : l->align == ALIGN_RIGHT ? l->r.x + l->r.w - l->pad - w
              : l->r.x + (l->r.w - w) / 2;
        int y = l->base ? l->base : text_centre_base(&l->r, l->font);
        if (l->over || l->bg_rows)
            gfx_text_over(s, &l->r, l->font, x, y, l->text, l->fg);
        else
            gfx_text(s, &l->r, l->font, x, y, l->text, l->fg, l->bg);
    }
    display_invalidate(&l->r);
}

/* ---- digits ---- */

static int digit_cell(const struct font *f)
{
    int w = 0;
    for (char c = '0'; c <= '9'; c++) {
        const struct font_glyph *g = font_glyph_of(f, (uint8_t)c);
        if (g && g->advance > w)
            w = g->advance;
    }
    return (w + 15) >> 4;
}

static int cell_width(const struct digits *d, char c, int digit_w)
{
    if (c >= '0' && c <= '9')
        return digit_w + d->tracking;
    const struct font_glyph *g = font_glyph_of(d->font, (uint8_t)c);
    return (g ? (g->advance + 15) >> 4 : 0) + d->tracking;
}

void digits_set(struct digits *d, const char *text)
{
    copy_text(d->text, text, sizeof d->text);
}

void digits_touch(struct digits *d)
{
    d->shown[0] = 0;
}

int digits_dirty(const struct digits *d)
{
    return strcmp(d->text, d->shown) != 0;
}

int digits_text_width(const struct digits *d)
{
    int dw = digit_cell(d->font), total = 0;
    for (const char *p = d->text; *p; p++)
        total += cell_width(d, *p, dw);
    return total - d->tracking;
}

int digits_left(const struct digits *d)
{
    return d->r.x + (d->r.w - digits_text_width(d)) / 2;
}

/* every glyph of the text, each centred in its cell, limited to clip */
static void draw_cells(const struct digits *d, const struct surface *s, const struct rect *clip, int x, int dw)
{
    for (int i = 0; d->text[i]; i++) {
        char c = d->text[i];
        int w = cell_width(d, c, dw);
        const struct font_glyph *g = font_glyph_of(d->font, (uint8_t)c);
        int gx = x + (w - d->tracking - (g ? (g->advance + 8) >> 4 : 0)) / 2;
        if (gx < clip->x + clip->w && gx + w + 4 > clip->x) {
            char one[2] = { c, 0 };
            gfx_text_over(s, clip, d->font, gx, d->base, one, d->fg);
        }
        x += w;
    }
}

void digits_paint(struct digits *d, const struct surface *s)
{
    if (!digits_dirty(d))
        return;
    /* a different length moves every cell: start from a clean box */
    if (strlen(d->text) != strlen(d->shown)) {
        ui_backdrop(s, &d->r);
        display_invalidate(&d->r);
        d->shown[0] = 0;
    }
    int dw = digit_cell(d->font), left = digits_left(d);
    int full = d->shown[0] == 0;
    if (full) {
        struct rect all = d->r;
        draw_cells(d, s, &all, left, dw);
    } else {
        int x = left;
        for (int i = 0; d->text[i]; i++) {
            int w = cell_width(d, d->text[i], dw);
            if (d->shown[i] != d->text[i]) {
                /* the cell, widened a little: a glyph may reach past its advance, so the neighbours' glyphs are
                   drawn again inside it */
                struct rect cell = { (int16_t)(x - 2), d->r.y, (int16_t)(w + 4), d->r.h };
                ui_backdrop(s, &cell);
                draw_cells(d, s, &cell, left, dw);
                display_invalidate(&cell);
            }
            x += w;
        }
    }
    copy_text(d->shown, d->text, sizeof d->shown);
}
