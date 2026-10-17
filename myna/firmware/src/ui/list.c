/* SPDX-License-Identifier: MIT */
/* The numbered list (ui/list.h). */
#include <stdint.h>

#include "drivers/display.h"
#include "drivers/keypad.h"
#include "ui/layout.h"
#include "ui/list.h"
#include "ui/theme.h"
#include "ui/ui.h"

static const uint8_t digit_key[9] = { KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9 };

#define SCROLL_W 6             /* the scroll bar's column at the right of a list longer than its area */

static int row_height(const struct list *l)
{
    return l->row_h ? l->row_h : layout.list.row_h;
}

int list_visible(const struct list *l)
{
    return l->r.h / row_height(l);
}

void list_init(struct list *l, const struct rect *r, int count)
{
    l->r = *r;
    l->count = (int16_t)count;
    l->selected = 0;
    l->top = 0;
    l->scroll = 0;
    list_touch(l);
}

void list_touch(struct list *l)
{
    l->dirty = 0xFFFFFFFFu;
    l->scroll = 0;
    ui_changed();
}

void list_touch_row(struct list *l, int row)
{
    int v = row - l->top;
    if (v >= 0 && v < list_visible(l)) {
        l->dirty |= 1u << v;
        ui_changed();
    }
}

void list_select(struct list *l, int row)
{
    if (l->count <= 0)
        return;
    row = (row % l->count + l->count) % l->count;
    if (row == l->selected)
        return;
    int vis = list_visible(l), old_top = l->top;
    list_touch_row(l, l->selected);
    l->selected = (int16_t)row;
    if (row < l->top)
        l->top = (int16_t)row;
    else if (row >= l->top + vis)
        l->top = (int16_t)(row - vis + 1);
    int moved = l->top - old_top;
    if ((moved == 1 || moved == -1) && !l->scroll && l->dirty != 0xFFFFFFFFu) {
        /* one row: the picture moves (list_paint copies it), the old selection is drawn again in its new place */
        l->dirty = moved > 0 ? l->dirty >> 1 : l->dirty << 1;
        l->scroll = (int16_t)moved;
        l->dirty |= moved > 0 ? 1u << (vis - 1) : 1u;
    } else if (moved) {
        l->dirty = 0xFFFFFFFFu;
        l->scroll = 0;
    }
    list_touch_row(l, l->selected);
    ui_changed();
}

int list_key(struct list *l, unsigned key)
{
    switch (key) {
    case KEY_UP:
        list_select(l, l->selected - 1);
        return LIST_USED;
    case KEY_DOWN:
        list_select(l, l->selected + 1);
        return LIST_USED;
    case KEY_SELECT:
        return l->count ? LIST_CHOSEN : LIST_USED;
    }
    if (l->numbered)
        for (int i = 0; i < 9; i++)
            if (key == digit_key[i] && i < l->count) {
                list_select(l, i);
                return LIST_CHOSEN;
            }
    return LIST_NONE;
}

/* the list's picture moved by one row: up (scroll 1, the rows below come up) or down */
static void move_picture(const struct list *l, const struct surface *s, int dir)
{
    int rh = row_height(l), h = (list_visible(l) - 1) * rh;
    uint16_t *base = s->pixels + l->r.y * s->stride + l->r.x;
    if (dir > 0) {
        for (int y = 0; y < h; y++)
            gfx_copy16(base + y * s->stride, base + (y + rh) * s->stride, (uint32_t)l->r.w);
    } else {
        for (int y = h - 1; y >= 0; y--)
            gfx_copy16(base + (y + rh) * s->stride, base + y * s->stride, (uint32_t)l->r.w);
    }
    struct rect all = { l->r.x, l->r.y, l->r.w, (int16_t)(h + rh) };
    display_invalidate(&all);
}

static void paint_row(const struct list *l, const struct surface *s, int row, int v)
{
    const struct theme *t = theme;
    int rh = row_height(l), pad = layout.list.pad;
    struct rect r = { l->r.x, (int16_t)(l->r.y + v * rh), l->r.w, (int16_t)rh };
    if (l->count > list_visible(l))
        r.w = (int16_t)(r.w - SCROLL_W);   /* the scroll bar's column is its own */
    int sel = row == l->selected && !l->unfocused;
    if (row >= l->count) {
        ui_backdrop(s, &r);
        display_invalidate(&r);
        return;
    }
    uint16_t bg = (uint16_t)ink.background[r.y + rh / 2];
    if (sel) {
        gfx_fill_rows(s, &r, rh == LIST_TALL_H ? ink.selection_tall : ink.selection);
    } else {
        struct rect body = { r.x, r.y, r.w, (int16_t)(rh - 1) }, rule = { r.x, (int16_t)(r.y + rh - 1), r.w, 1 };
        gfx_fill_rows(s, &body, ink.background + body.y);
        gfx_fill(s, &rule, ink.rule);
    }
    if (l->draw) {
        l->draw(s, &r, row, sel, bg);
        display_invalidate(&r);
        return;
    }
    int x = r.x + pad;
    if (l->numbered) {
        char num[4];
        int n = 0, k = row + 1;
        if (k >= 10)
            num[n++] = (char)('0' + k / 10 % 10);
        num[n++] = (char)('0' + k % 10);
        num[n] = 0;
        const struct font *f = sel ? t->number_selected : t->number;
        int y = r.y + (sel ? layout.list.number_base_sel : layout.list.number_base);
        /* a number of two digits reaches left into the margin, so that the labels stay in line */
        int nx = n > 1 ? x + layout.list.number_w - gfx_text_width(f, num) : x;
        if (sel)
            gfx_text_over(s, &r, f, nx, y, num, ink.on_accent);
        else
            gfx_text(s, &r, f, nx, y, num, ink.muted, bg);
        x += layout.list.number_w + layout.list.gap;
    }
    const char *label = l->label(row);
    const struct font *f = sel ? t->row_selected : t->row;
    int y = r.y + (sel ? layout.list.label_base_sel : layout.list.label_base);
    if (sel)
        gfx_text_over(s, &r, f, x, y, label, ink.on_accent);
    else
        gfx_text(s, &r, f, x, y, label, l->muted && l->muted(row) ? ink.muted : ink.text, bg);
    const char *value = l->value ? l->value(row) : 0;
    if (value && value[0]) {
        f = sel ? t->value_selected : t->value;
        int vx = r.x + r.w - pad - gfx_text_width(f, value);
        y = r.y + (sel ? layout.list.value_base_sel : layout.list.value_base);
        if (sel)
            gfx_text_over(s, &r, f, vx, y, value, ink.on_accent);
        else
            gfx_text(s, &r, f, vx, y, value, ink.value, bg);
    }
    display_invalidate(&r);
}

/* a list longer than its area: a thin track and a thumb that shows where the visible rows are, in a column of its own */
static void paint_scroll_bar(const struct list *l, const struct surface *s)
{
    int vis = list_visible(l), rh = row_height(l);
    if (l->count <= vis)
        return;
    struct rect col = { (int16_t)(l->r.x + l->r.w - SCROLL_W), l->r.y, SCROLL_W, (int16_t)(vis * rh) };
    gfx_fill_rows(s, &col, ink.background + col.y);
    int top = col.y + 4, h = col.h - 8;
    struct rect track = { (int16_t)(col.x + 2), (int16_t)top, 1, (int16_t)h };
    gfx_fill(s, &track, ink.rule);
    int th = h * vis / l->count;
    if (th < 14)
        th = 14;
    struct rect thumb = { (int16_t)(col.x + 1), (int16_t)(top + (h - th) * l->top / (l->count - vis)), 3,
                          (int16_t)th };
    gfx_round_rect(s, &col, &thumb, 1, ink.muted, GFX_NO_BORDER);
    display_invalidate(&col);
}

void list_paint(struct list *l, const struct surface *s)
{
    if (l->scroll) {
        move_picture(l, s, l->scroll);
        l->scroll = 0;
    }
    if (!l->dirty)
        return;
    int vis = list_visible(l);
    for (int v = 0; v < vis; v++)
        if (l->dirty & (1u << v))
            paint_row(l, s, l->top + v, v);
    l->dirty = 0;
    paint_scroll_bar(l, s);
}
