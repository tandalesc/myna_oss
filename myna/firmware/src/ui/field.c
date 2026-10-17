/* SPDX-License-Identifier: MIT */
/* The editable number field and its screen (ui/field.h). */
#include <stdint.h>

#include "drivers/display.h"
#include "drivers/keypad.h"
#include "lib/mem.h"
#include "ui/field.h"
#include "ui/layout.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

static const uint8_t digit_keys[10] = { KEY_0, KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9 };

static int digits_total(const struct field *f)
{
    int n = 0;
    for (int g = 0; g < f->groups; g++)
        n += f->width[g];
    return n;
}

/* the group and the digit (from the left of the group) of cursor position c */
static void locate(const struct field *f, int c, int *group, int *digit)
{
    int g = 0;
    while (g < f->groups - 1 && c >= f->width[g])
        c -= f->width[g++];
    *group = g;
    *digit = c;
}

static int pow10i(int n)
{
    int p = 1;
    while (n-- > 0)
        p *= 10;
    return p;
}

void field_touch(struct field *f)
{
    f->dirty = 1;
    ui_changed();
}

int field_key(struct field *f, unsigned key)
{
    int g, d, total = digits_total(f);
    locate(f, f->cursor, &g, &d);
    int span = f->max[g] - f->min[g] + 1;
    switch (key) {
    case KEY_LEFT:
        f->cursor = (uint8_t)((f->cursor + total - 1) % total);
        break;
    case KEY_RIGHT:
        f->cursor = (uint8_t)((f->cursor + 1) % total);
        break;
    case KEY_UP:
        f->value[g] = (int16_t)(f->min[g] + (f->value[g] - f->min[g] + 1) % span);
        break;
    case KEY_DOWN:
        f->value[g] = (int16_t)(f->min[g] + (f->value[g] - f->min[g] + span - 1) % span);
        break;
    default: {
        int digit = -1;
        for (int i = 0; i < 10; i++)
            if (key == digit_keys[i])
                digit = i;
        if (digit < 0)
            return 0;
        int p = pow10i(f->width[g] - 1 - d);
        int v = f->value[g] - (f->value[g] / p % 10) * p + digit * p;
        if (v > f->max[g])
            v = f->max[g];
        if (v < f->min[g])
            v = f->min[g];
        f->value[g] = (int16_t)v;
        if (f->cursor + 1 < total)
            f->cursor++;
    }
    }
    field_touch(f);
    return 1;
}

static int cell_w(const struct font *f)
{
    int w = 0;
    for (char c = '0'; c <= '9'; c++) {
        const struct font_glyph *g = font_glyph_of(f, (uint8_t)c);
        if (g && g->advance > w)
            w = g->advance;
    }
    return (w + 15) >> 4;
}

void field_paint(struct field *f, const struct surface *s)
{
    if (!f->dirty)
        return;
    f->dirty = 0;
    ui_backdrop(s, &f->r);
    const struct font *font = f->font;
    int cw = cell_w(font);
    const struct font_glyph *sg = font_glyph_of(font, (uint8_t)f->sep);
    int sw = f->sep && sg ? (sg->advance + 15) >> 4 : 0;
    int total = digits_total(f), width = total * cw + (f->groups - 1) * sw;
    int x = f->r.x + (f->r.w - width) / 2, pos = 0;
    for (int g = 0; g < f->groups; g++) {
        if (g) {
            char sep[2] = { f->sep, 0 };
            gfx_text_over(s, &f->r, font, x, f->base, sep, ink.text);
            x += sw;
        }
        for (int d = 0; d < f->width[g]; d++, pos++) {
            char c[2] = { (char)('0' + f->value[g] / pow10i(f->width[g] - 1 - d) % 10), 0 };
            const struct font_glyph *gl = font_glyph_of(font, (uint8_t)c[0]);
            int gx = x + (cw - (gl ? (gl->advance + 8) >> 4 : 0)) / 2;
            gfx_text_over(s, &f->r, font, gx, f->base, c, pos == f->cursor ? ink.accent : ink.text);
            if (pos == f->cursor) {
                struct rect u = { (int16_t)(x + 2), (int16_t)(f->base + 6), (int16_t)(cw - 4), 3 };
                gfx_round_rect(s, &f->r, &u, 1, ink.accent, GFX_NO_BORDER);
            }
            x += cw;
        }
    }
    display_invalidate(&f->r);
}

/* ---- the field's screen ---- */

static struct field_request req;
static struct label help;

static void enter(int fresh)
{
    (void)fresh;
    ui_title(req.title);
    ui_soft_keys("", "Save", "Back");
    const struct rect *c = &layout.content;
    req.field.r = (struct rect){ c->x, (int16_t)(c->y + 30), c->w, 84 };
    req.field.base = (int16_t)(c->y + 30 + 62);
    req.field.font = theme->clock_font;
    field_touch(&req.field);
    help = (struct label){ .r = { c->x, (int16_t)(c->y + 124), c->w, 20 }, .font = theme->body, .fg = ink.muted,
                           .over = 1, .align = ALIGN_CENTRE, .base = (int16_t)(c->y + 138), .dirty = 1 };
    label_set(&help, req.help);
}

static void paint(const struct surface *fb)
{
    field_paint(&req.field, fb);
    label_paint(&help, fb);
}

static int key(unsigned k)
{
    if (k == KEY_SELECT || k == KEY_SOFT_LEFT) {
        if (req.save)
            req.save(&req.field);
        ui_pop();
        return 1;
    }
    if (k == KEY_SOFT_RIGHT) {
        ui_pop();
        return 1;
    }
    return field_key(&req.field, k);
}

static const struct screen field_screen = {
    .name = "field",
    .flags = SCREEN_TITLE,
    .enter = enter,
    .paint = paint,
    .key = key,
};

void field_screen_open(const struct field_request *r)
{
    req = *r;
    req.field.cursor = 0;
    ui_push(&field_screen);
}
