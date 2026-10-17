/* SPDX-License-Identifier: MIT */
/* Message blocks (ui/convo.h). Geometry from the design's conversation mock-up: a block is a rounded box (the theme's
 * block radius) with a 1 px edge, 4 px above the header, a 14 px header line, 16 px text lines, 6 px below, 5 px
 * between blocks, and a soft shade of two rows under it.
 *
 * Positions are kept from the bottom of the content: the newest block's lower edge is 0, each older block lies a gap
 * above the one after it. The view shows [off, off + view height); scrolling moves off. */
#include <stdint.h>

#include "drivers/display.h"
#include "drivers/keypad.h"
#include "lib/mem.h"
#include "ui/convo.h"
#include "ui/layout.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

#define MAX_LINES 64           /* of one block; a longer text is cut */
#define NOTE_H    15           /* the note's line under the text */

void convo_touch(struct convo *c)
{
    c->dirty = 1;
    ui_changed();
}

static int text_w(const struct convo *c)
{
    return c->r.w - 2 - 2 * layout.convo.pad_x;
}

static int wrap(const struct convo *c, const struct convo_msg *m, uint16_t *starts)
{
    return text_wrap(theme->body, m->text, (int)strlen(m->text), text_w(c), starts, MAX_LINES);
}

/* height of a block of n text lines */
static int block_h(int lines, int note)
{
    return 2 + layout.convo.pad_top + layout.convo.head_h + lines * layout.convo.line_h + (note ? NOTE_H : 0) +
           layout.convo.pad_bottom;
}

static void measure(struct convo *c)
{
    uint16_t starts[MAX_LINES];
    for (int i = 0; i < c->count; i++)
        c->h[i] = (int16_t)block_h(wrap(c, &c->msgs[i], starts), c->msgs[i].note != 0);
}

/* the window: content positions [off, off + view) are shown, a gap from the area's top and bottom */
static int view_h(const struct convo *c)
{
    return c->r.h - 2 * layout.convo.gap - c->below;
}

/* the lower edge of block i, from the content's bottom */
static int bottom_of(const struct convo *c, int i)
{
    int b = 0;
    for (int j = c->count - 1; j > i; j--)
        b += c->h[j] + layout.convo.gap;
    return b;
}

void convo_set(struct convo *c, const struct convo_msg *msgs, int count)
{
    c->msgs = msgs;
    c->count = (int16_t)(count > CONVO_MAX ? CONVO_MAX : count);
    if (count > CONVO_MAX)
        c->msgs += count - CONVO_MAX;      /* the newest */
    c->off = 0;
    measure(c);
    convo_touch(c);
}

void convo_refresh(struct convo *c)
{
    measure(c);
    int top = c->count ? bottom_of(c, 0) + c->h[0] : 0, most = top - view_h(c);
    if (c->off > most)
        c->off = (int16_t)(most > 0 ? most : 0);
    convo_touch(c);
}

int convo_focus(const struct convo *c)
{
    for (int i = c->count - 1, b = 0; i >= 0; b += c->h[i] + layout.convo.gap, i--)
        if (b + c->h[i] > c->off)
            return i;
    return c->count - 1;
}

int convo_key(struct convo *c, unsigned key)
{
    if (key != KEY_UP && key != KEY_DOWN)
        return 0;
    int vh = view_h(c), cap = vh - 2 * layout.convo.line_h, off = c->off, target = -1;
    if (key == KEY_UP) {
        /* the newest block whose top is above the window: its top to the window's top */
        for (int i = c->count - 1, b = 0; i >= 0; b += c->h[i] + layout.convo.gap, i--)
            if (b + c->h[i] > off + vh) {
                target = b + c->h[i] - vh;
                break;
            }
        if (target > off + cap)
            target = off + cap;
    } else if (off > 0) {
        /* the oldest block whose lower edge is below the window: that edge to the window's bottom */
        for (int i = 0; i < c->count; i++) {
            int b = bottom_of(c, i);
            if (b < off) {
                target = b;
                break;
            }
        }
        if (target < off - cap)
            target = off - cap;
    }
    if (target >= 0 && target != off) {
        c->off = (int16_t)target;
        convo_touch(c);
    }
    return 1;
}

static void paint_block(const struct convo *c, const struct surface *s, const struct convo_msg *m, int top,
                        const uint16_t *starts, int lines, int focused)
{
    const struct theme *t = theme;
    struct rect b = { c->r.x, (int16_t)top, c->r.w, (int16_t)block_h(lines, m->note != 0) };
    uint16_t fill = m->out ? ink.outgoing : ink.surface;    /* the text is drawn on it: the cheaper way */
    gfx_round_rect(s, &c->r, &b, t->block_radius, fill, focused ? ink.accent : ink.rule);
    /* the shade under it */
    struct rect sh = { (int16_t)(b.x + t->block_radius / 2), (int16_t)(b.y + b.h), (int16_t)(b.w - t->block_radius),
                       1 }, x;
    if (rect_intersect(&x, &sh, &c->r))
        gfx_blend_fill(s, &x, 0, 3);
    sh.y++;
    sh.x = (int16_t)(sh.x + 2);
    sh.w = (int16_t)(sh.w - 4);
    if (rect_intersect(&x, &sh, &c->r))
        gfx_blend_fill(s, &x, 0, 1);

    int tx = b.x + 1 + layout.convo.pad_x, y = b.y + 16;
    char head[40];
    copy_text(head, m->who, 24);
    int n = (int)strlen(head);
    if (m->time && m->time[0]) {
        copy_text(head + n, " " TEXT_DOT " ", sizeof head - (unsigned)n);
        n += 4;
        copy_text(head + n, m->time, sizeof head - (unsigned)n);
    }
    gfx_text(s, &c->r, t->meta, tx, y, head, m->out ? ink.accent : ink.muted, fill);
    if (m->state) {
        int w = gfx_text_width(t->meta, m->state);
        gfx_text(s, &c->r, t->meta, b.x + b.w - 1 - layout.convo.pad_x - w, y, m->state,
                 m->alert ? ink.accent : ink.muted, fill);
    }
    y += 15;
    int len = (int)strlen(m->text);
    for (int i = 0; i < lines; i++, y += layout.convo.line_h) {
        int a = starts[i], e = i + 1 < lines ? starts[i + 1] : len;
        while (e > a && (m->text[e - 1] == ' ' || m->text[e - 1] == '\n'))
            e--;
        text_draw_n_on(s, &c->r, t->body, tx, y, m->text + a, e - a, ink.text, fill);
    }
    if (m->note)
        gfx_text(s, &c->r, t->meta, tx, y - 1, m->note, m->alert ? ink.accent : ink.muted, fill);
}

void convo_paint(struct convo *c, const struct surface *s)
{
    if (!c->dirty)
        return;
    c->dirty = 0;
    ui_backdrop(s, &c->r);
    int zero = c->r.y + c->r.h - layout.convo.gap - c->below + c->off;   /* the screen row of content position 0 */
    int focus = c->off > 0 ? convo_focus(c) : -1;
    for (int i = c->count - 1, b = 0; i >= 0; b += c->h[i] + layout.convo.gap, i--) {
        int top = zero - b - c->h[i];
        if (top >= c->r.y + c->r.h)
            continue;                      /* below the area */
        if (top + c->h[i] <= c->r.y)
            break;                         /* above it, and every older one too */
        uint16_t starts[MAX_LINES];
        int lines = wrap(c, &c->msgs[i], starts);
        paint_block(c, s, &c->msgs[i], top, starts, lines, i == focus);
    }
    display_invalidate(&c->r);
}
