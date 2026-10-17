/* SPDX-License-Identifier: MIT */
/* The numbered list (STYLE.md section 2, the settings style): rows of 27 px with a number (1-9 open a row directly), a
 * label, a value or a chevron at the right, and one strong highlight bar in the theme's accent on the selected row.
 * Rows come from callbacks, so a list can show anything (settings, later messages and contacts) without copying it.
 *
 * Motion is cheap (STYLE.md section 4): moving the selection redraws two rows; scrolling past the last visible row
 * moves the list by one row: the rows that stay are copied, one new row is drawn.
 *
 * A list of taller rows (row_h = LIST_TALL_H: a conversation, two lines) draws each row's content itself (`draw`),
 * on the same background and selection bar. A row can be muted (shown in the muted colour: an action not possible
 * yet). */
#ifndef MYNA_UI_LIST_H
#define MYNA_UI_LIST_H

#include <stdint.h>

#include "gfx/gfx.h"

#define LIST_CHEVRON "\xE2\x80\xBA"    /* U+203A: the value of a row that opens something further */
#define LIST_TALL_H  41        /* the height of a two-line row: six fill the content area */

struct list {
    struct rect r;             /* the list's area: its width, its top, and as many rows as fit in its height */
    int16_t count;             /* rows */
    int16_t selected;
    int16_t top;               /* first visible row */
    uint8_t numbered;          /* show 1, 2, 3 ... in front of the rows */
    uint8_t row_h;             /* 0: the settings' 27 px; or LIST_TALL_H */
    uint8_t unfocused;         /* no row on the selection bar: the focus is elsewhere (the dialer's number) */
    const char *(*label)(int row);
    const char *(*value)(int row);     /* may be 0, or return "" for none */
    int (*muted)(int row);             /* may be 0: 1 draws the row's label in the muted colour */
    /* may be 0: draws the row's content in r over its background (sel: on the selection bar; bg: the background's
       colour in the middle of the row), in place of the number, label and value */
    void (*draw)(const struct surface *s, const struct rect *r, int row, int sel, uint16_t bg);
    uint32_t dirty;            /* visible rows to draw, a bit per row from top */
    int16_t scroll;            /* rows to move the picture by before drawing (+1 down, -1 up) */
};

enum { LIST_NONE, LIST_USED, LIST_CHOSEN };

/* set up l in r (its rows, its selection 0) */
void list_init(struct list *l, const struct rect *r, int count);
/* up / down move the selection (round from the end to the start), select or a number key 1-9 chooses a row:
   LIST_CHOSEN (l->selected is the row), LIST_USED for a move, LIST_NONE for a key the list does not use */
int list_key(struct list *l, unsigned key);
void list_select(struct list *l, int row);
void list_touch(struct list *l);           /* draw every row again */
void list_touch_row(struct list *l, int row);
void list_paint(struct list *l, const struct surface *s);
int list_visible(const struct list *l);    /* rows that fit */

#endif
