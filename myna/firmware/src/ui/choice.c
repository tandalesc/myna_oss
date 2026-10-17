/* SPDX-License-Identifier: MIT */
/* The choice and the editor (ui/choice.h). */
#include <stdint.h>

#include "drivers/keypad.h"
#include "kernel/timer.h"
#include "lib/mem.h"
#include "ui/choice.h"
#include "ui/layout.h"
#include "ui/list.h"
#include "ui/textentry.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

#define EDITOR_LINES 6         /* the box grows to this many lines */
#define TIMER_TAP    (UI_TIMER_SCREEN + 0)

/* ---- the choice ---- */

static struct choice ch;
static struct list rows;

static const char *row_label(int r)
{
    return ch.rows[r].label;
}

static const char *row_value(int r)
{
    return ch.rows[r].value ? ch.rows[r].value : "";
}

static int row_muted(int r)
{
    return ch.rows[r].why != 0;
}

static void choice_enter(int fresh)
{
    int sel = rows.selected;
    struct rect r = layout.content;
    r.h = (int16_t)(layout.list.rows * layout.list.row_h);
    list_init(&rows, &r, ch.count);
    rows.numbered = 1;
    rows.label = row_label;
    rows.value = row_value;
    rows.muted = row_muted;
    if (!fresh)
        list_select(&rows, sel);
    ui_title(ch.title);
    ui_soft_keys("", "Select", "Back");
}

static void choice_paint(const struct surface *fb)
{
    list_paint(&rows, fb);
}

static int choice_key(unsigned k)
{
    switch (list_key(&rows, k)) {
    case LIST_CHOSEN: {
        const struct choice_row *r = &ch.rows[rows.selected];
        if (r->why)
            ui_note(r->why);
        else if (!ch.chosen || !ch.chosen(rows.selected))
            ui_pop();
        return 1;
    }
    case LIST_USED:
        return 1;
    }
    if (k == KEY_SOFT_RIGHT) {
        ui_pop();
        return 1;
    }
    return 0;
}

static const struct screen choice_screen = {
    .name = "choice",
    .flags = SCREEN_TITLE | SCREEN_PASSING,
    .enter = choice_enter,
    .paint = choice_paint,
    .key = choice_key,
};

void choice_open(const struct choice *c)
{
    ch = *c;
    if (ch.count > CHOICE_ROWS)
        ch.count = CHOICE_ROWS;
    ui_open(&choice_screen);
}

/* ---- the editor ---- */

static struct editor ed;
static char ed_title[32];
static struct text_entry box;
static struct timer tap_timer;
static struct label help;
static int box_lines;

void editor_title(const char *title)
{
    copy_text(ed_title, title, sizeof ed_title);
    ui_title(ed_title);
}

static void place(int lines)
{
    const struct rect *c = &layout.content;
    box.r = (struct rect){ layout.convo.compose.x, (int16_t)(c->y + 12), layout.convo.compose.w,
                           (int16_t)text_entry_height(lines) };
    box_lines = lines;
    /* the help's label covers everything under the box, so a box that got smaller leaves nothing behind */
    int y = box.r.y + box.r.h;
    struct rect below = { c->x, (int16_t)y, c->w, (int16_t)(c->y + c->h - y) };
    help = (struct label){ .r = below, .font = theme->body, .fg = ink.muted, .over = 1, .align = ALIGN_LEFT,
                           .pad = (uint8_t)(layout.convo.compose.x + 2), .base = (int16_t)(y + 22), .dirty = 1 };
    label_set(&help, ed.help ? ed.help : "");
    text_entry_touch(&box);
}

static void fit(void)
{
    int lines = text_entry_lines(&box, box.r.w);
    if (lines > EDITOR_LINES)
        lines = EDITOR_LINES;
    if (lines != box_lines)
        place(lines);
}

static void editor_enter(int fresh)
{
    static int made;
    if (!made) {
        ui_timer_init(&tap_timer, TIMER_TAP);
        made = 1;
    }
    if (fresh) {
        box.placeholder = ed.placeholder;
        box.max = ed.max;
        box.phone = ed.phone;
        box.count = 0;
        text_entry_init(&box, &layout.convo.compose, &tap_timer);
        if (ed.abc && box.mode == TEXT_PREDICT)
            box.mode = TEXT_LETTERS;
        text_entry_set(&box, ed.text ? ed.text : "");
    }
    ui_title(ed_title);
    ui_soft_keys(ed.left, "Save", "Back");
    box_lines = 0;
    place(1);
    fit();
}

static void editor_leave(void)
{
    timer_stop(&tap_timer);
}

static void editor_paint(const struct surface *fb)
{
    text_entry_paint(&box, fb);
    label_paint(&help, fb);
}

static int editor_key(unsigned k)
{
    if (k == KEY_SOFT_LEFT && text_entry_key(&box, k))
        return 1;              /* Spell */
    switch (k) {
    case KEY_SELECT:
        text_entry_commit(&box);
        if (!ed.save || !ed.save(box.text))
            ui_pop();
        return 1;
    case KEY_SOFT_LEFT:
        if (ed.left_key)
            ed.left_key();
        return 1;
    case KEY_SOFT_RIGHT:
        ui_pop();
        return 1;
    }
    if (text_entry_key(&box, k)) {
        fit();
        return 1;
    }
    return 0;
}

static void editor_timer(unsigned id)
{
    if (id == TIMER_TAP)
        text_entry_timer(&box);
}

static const struct screen editor_screen = {
    .name = "editor",
    .flags = SCREEN_TITLE | SCREEN_PASSING,
    .enter = editor_enter,
    .leave = editor_leave,
    .paint = editor_paint,
    .key = editor_key,
    .timer = editor_timer,
};

void editor_open(const struct editor *e)
{
    ed = *e;
    if (!ed.max || ed.max > TEXT_MAX)
        ed.max = TEXT_MAX;
    copy_text(ed_title, ed.title, sizeof ed_title);
    ui_open(&editor_screen);
}
