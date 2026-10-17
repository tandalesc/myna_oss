/* SPDX-License-Identifier: MIT */
/* Two small screens every application uses (STYLE.md section 2: the numbered list, the text box):
 *
 * A choice: a few actions or values as a numbered list on a screen of its own (Options, a label, one of a contact's
 * numbers). Select or the row's number chooses; a muted row (something not possible yet, such as a call) shows its
 * reason as a toast instead. Back or C closes it.
 *
 * An editor: one text box under the title bar (multi-tap, or a phone number), with a line of help under it, Save on
 * the centre soft key and an optional action of the caller's on the left soft key (a number's label).
 *
 * Both call the caller while they are still the top screen: the callback returns 0 to close them, or 1 when it went
 * somewhere itself (with ui_open(), which puts the next screen in their place: they are SCREEN_PASSING, so a choice
 * that leads to an editor, or an editor that leads to a conversation, leaves nothing behind; for a dialog, ui_pop()
 * first). The title and the editor's text are copied; the rows' texts must live while the choice is open. */
#ifndef MYNA_UI_CHOICE_H
#define MYNA_UI_CHOICE_H

#include <stdint.h>

#define CHOICE_ROWS 9

struct choice_row {
    const char *label;
    const char *value;         /* may be 0 */
    const char *why;           /* not 0: the row is muted, and choosing it shows this */
};

struct choice {
    const char *title;
    int count;
    struct choice_row rows[CHOICE_ROWS];
    int (*chosen)(int row);
};

void choice_open(const struct choice *c);

struct editor {
    const char *title;
    const char *text;          /* to start with (UTF-8) */
    const char *placeholder;
    const char *help;          /* under the box, or 0 */
    uint16_t max;              /* characters, at most TEXT_MAX */
    uint8_t phone;             /* a phone number (ui/textentry.h) */
    uint8_t abc;               /* start in Abc, not predictive text (a name: predictive text is one # away) */
    const char *left;          /* the left soft key, or 0 */
    void (*left_key)(void);    /* its action: it may change the title (editor_title) */
    int (*save)(const char *text);
};

void editor_open(const struct editor *e);
void editor_title(const char *title);

#endif
