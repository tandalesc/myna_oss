/* SPDX-License-Identifier: MIT */
/* Notes (menu item *): short notes typed with predictive text or multi-tap, shown as message blocks over the text box, in the layout of
 * the design's conversation screen. Save (select or the centre soft key) adds the text as a note; up / down scroll the
 * notes; C deletes, and on an empty box goes back; Options (the left soft key): Add symbol, Delete all notes (after a dialog). The box grows with its text up to four lines.
 *
 * The notes are kept in RAM only for now (the eight newest); keeping them in the user file system comes later. This
 * screen is also the example of the conversation and text widgets for the Messages screen. */
#include <stdint.h>

#include "drivers/clock.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "kernel/timer.h"
#include "lib/mem.h"
#include "ui/apps.h"
#include "ui/choice.h"
#include "ui/convo.h"
#include "ui/layout.h"
#include "ui/textentry.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

#define NOTES     8
#define NOTE_MAX  160          /* a note is as long as a one-part text message */
#define MAX_BOX   4            /* lines the box grows to */
#define TIMER_TAP (UI_TIMER_SCREEN + 0)

static char note_text[NOTES][NOTE_MAX + 1];
static char note_time[NOTES][12];
static struct convo_msg msgs[NOTES];
static int count;

static struct convo blocks;
static struct text_entry box;
static struct timer tap_timer;
static int box_lines;
static uint8_t hint_dirty;

static void soft_keys(void);
static void fit_box(void);

/* the box (as high as its text needs) and the blocks above it */
static void place(int lines)
{
    const struct rect *c = &layout.convo.compose;
    int h = text_entry_height(lines);
    int bottom = c->y + c->h;
    box.r = (struct rect){ c->x, (int16_t)(bottom - h), c->w, (int16_t)h };
    blocks.r = layout.convo.blocks;
    blocks.r.h = (int16_t)(box.r.y - blocks.r.y);    /* to the box: a box that got smaller leaves nothing */
    blocks.below = 4;
    box_lines = lines;
    convo_touch(&blocks);
    text_entry_touch(&box);
    hint_dirty = 1;
}

static void enter(int fresh)
{
    static int made;
    if (!made) {
        ui_timer_init(&tap_timer, TIMER_TAP);
        box.placeholder = "Write a note";
        box.max = NOTE_MAX;
        text_entry_init(&box, &layout.convo.compose, &tap_timer);
        made = 1;
    }
    (void)fresh;
    ui_title("Notes");
    soft_keys();
    place(1);
    convo_set(&blocks, msgs, count);
    fit_box();
}

static void save(void)
{
    if (!box.len)
        return;
    if (count == NOTES) {
        memmove(note_text[0], note_text[1], sizeof note_text[0] * (NOTES - 1));
        memmove(note_time[0], note_time[1], sizeof note_time[0] * (NOTES - 1));
        count--;
    }
    copy_text(note_text[count], box.text, sizeof note_text[0]);
    format_time(note_time[count], clock_seconds(), 1);
    count++;
    for (int i = 0; i < count; i++)
        msgs[i] = (struct convo_msg){ .out = 1, .who = "Me", .time = note_time[i], .text = note_text[i] };
    convo_set(&blocks, msgs, count);
    text_entry_clear(&box);
    soft_keys();
    ui_note("Saved");
}

static void soft_keys(void)
{
    ui_soft_keys("Options", "Save", "Back");
}

static void delete_answer(unsigned key)
{
    if (key != KEY_SELECT)
        return;
    count = 0;
    convo_set(&blocks, msgs, 0);
    hint_dirty = 1;
    soft_keys();
}

static const struct dialog delete_dialog = {
    .text = "Delete all notes?", .centre = "Delete", .right = "Keep", .answer = delete_answer,
};

static void fit_box(void)
{
    int lines = text_entry_lines(&box, layout.convo.compose.w);
    if (lines > MAX_BOX)
        lines = MAX_BOX;
    if (lines != box_lines)
        place(lines);
}

static void paint(const struct surface *fb)
{
    int redo = blocks.dirty || hint_dirty;
    convo_paint(&blocks, fb);
    if (redo) {
        hint_dirty = 0;
        if (!count) {
            const struct font *f = theme->body;
            const char *hint = "No notes yet";
            int y = blocks.r.y + blocks.r.h / 2;
            gfx_text_over(fb, &blocks.r, f, (DISPLAY_W - gfx_text_width(f, hint)) / 2, y, hint, ink.muted);
        }
    }
    text_entry_paint(&box, fb);
}

static int notes_option(int row)
{
    ui_pop();
    if (row == 0)
        text_entry_symbols(&box);
    else
        ui_dialog(&delete_dialog);
    return 1;
}

static void notes_options(void)
{
    text_entry_commit(&box);
    struct choice c = { .title = "Options", .count = 2, .chosen = notes_option };
    c.rows[0] = (struct choice_row){ .label = "Add symbol" };
    c.rows[1] = (struct choice_row){ .label = "Delete all notes", .why = count ? 0 : "There are no notes" };
    choice_open(&c);
}

static int key(unsigned k)
{
    if (k == KEY_SOFT_LEFT && text_entry_key(&box, k))
        return 1;              /* Spell */
    switch (k) {
    case KEY_SELECT:
        text_entry_commit(&box);
        save();
        fit_box();
        return 1;
    case KEY_SOFT_RIGHT:
        ui_pop();
        return 1;
    case KEY_SOFT_LEFT:
        notes_options();
        return 1;
    }
    if (text_entry_key(&box, k)) {
        fit_box();
        return 1;
    }
    return convo_key(&blocks, k);
}

static void timer(unsigned id)
{
    if (id == TIMER_TAP)
        text_entry_timer(&box);
}

static void leave(void)
{
    text_entry_timer(&box);
    timer_stop(&tap_timer);
}

const struct screen notes_screen = {
    .name = "notes",
    .flags = SCREEN_TITLE,
    .enter = enter,
    .leave = leave,
    .paint = paint,
    .key = key,
    .timer = timer,
};
