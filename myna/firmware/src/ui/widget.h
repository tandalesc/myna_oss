/* SPDX-License-Identifier: MIT */
/* Widgets: pieces of a screen that know their rectangle, remember whether they changed, and redraw only themselves.
 * A screen sets their content in reaction to events and calls paint; a widget that did not change draws nothing and
 * sends nothing to the panel. Larger widgets have their own headers: ui/list.h (numbered list), ui/textentry.h (text
 * box with multi-tap), ui/field.h (time and number fields), ui/convo.h (message blocks).
 *
 * Text is UTF-8, as everywhere in Myna; the atlases have Latin-1, the typographic signs (TEXT_ELLIPSIS, TEXT_DOT, the
 * list's chevron) and, in the sizes for what people write, Cyrillic (myna/tools/mkfont.c). Lengths and positions are
 * in bytes and always at the start of a character. */
#ifndef MYNA_UI_WIDGET_H
#define MYNA_UI_WIDGET_H

#include <stdint.h>

#include "gfx/gfx.h"

enum align { ALIGN_LEFT, ALIGN_CENTRE, ALIGN_RIGHT };

/* one line of text in a box. With bg_rows (one colour per row of the box, from its top: a bar's gradient) or over = 1
 * (what is behind: ui_backdrop) the box is not one colour; otherwise it is filled with bg. */
struct label {
    struct rect r;
    const struct font *font;
    uint16_t fg, bg;
    const uint32_t *bg_rows;
    uint8_t over;
    uint8_t align;
    uint8_t pad;               /* inner margin for left and right alignment */
    uint8_t dirty;
    int16_t base;              /* baseline (screen row); 0: centre the capitals in the box */
    char text[40];
};

void label_set(struct label *l, const char *text);
void label_paint(struct label *l, const struct surface *s);
void label_touch(struct label *l);

/* Text in fixed cells, one per character, as wide as the widest digit: a clock. A change of one character redraws
 * only that character's cell, and the text never moves sideways when its digits change. Drawn over what is behind
 * (ui_backdrop): the standby clock is on the wallpaper. */
#define DIGITS_MAX 8
struct digits {
    struct rect r;             /* the text is centred in r */
    const struct font *font;
    uint16_t fg;
    int16_t base;              /* baseline */
    int8_t tracking;           /* pixels added between cells (the design's letter-spacing) */
    char text[DIGITS_MAX + 1];
    char shown[DIGITS_MAX + 1];    /* what the framebuffer holds; "" = nothing yet: everything is drawn */
};

void digits_set(struct digits *d, const char *text);
void digits_paint(struct digits *d, const struct surface *s);
int digits_dirty(const struct digits *d);
int digits_text_width(const struct digits *d);     /* width of the text in its cells, in pixels */
int digits_left(const struct digits *d);           /* x of its first cell */
void digits_touch(struct digits *d);

#define TEXT_ELLIPSIS "\xE2\x80\xA6"   /* U+2026 */
#define TEXT_DOT      "\xC2\xB7"       /* U+00B7, the middle dot between a sender and a time */

/* text helpers */
/* src into dst (size bytes with the 0); a text too long is cut before a whole character */
void copy_text(char *dst, const char *src, unsigned size);
/* the start of the character before position i of text (i > 0), and of the one after it (i < its length) */
int text_prev(const char *text, int i);
int text_next(const char *text, int i);
/* characters (not bytes) in text[0..len) */
int text_chars(const char *text, int len);
/* v in decimal at out; returns the number of characters (out is terminated) */
int format_uint(char *out, unsigned v);
/* the time of `seconds` (Unix) as the user wants it: "14:05", or "2:05" with " PM" if ampm and 12-hour form */
void format_time(char *out, uint32_t seconds, int ampm);
/* Break text[0..len) into lines no wider than `width` (at spaces; a word longer than a line is cut). starts[i] is
 * where line i begins; line i ends where line i + 1 begins (or at len), its trailing space not drawn. Returns the
 * number of lines (at most max; the last one then holds the rest). An empty text is one empty line. */
int text_wrap(const struct font *f, const char *text, int len, int width, uint16_t *starts, int max);
/* width of text[0..len) */
int text_width_n(const struct font *f, const char *text, int len);
/* draw text[0..len) */
void text_draw_n(const struct surface *s, const struct rect *clip, const struct font *f, int x, int y,
                 const char *text, int len, uint16_t fg);
/* the same on a plain colour bg (a text box, a message block): about 40 % cheaper than over the surface */
void text_draw_n_on(const struct surface *s, const struct rect *clip, const struct font *f, int x, int y,
                    const char *text, int len, uint16_t fg, uint16_t bg);

/* baseline that centres the ink of digits and capitals vertically in a box */
int text_centre_base(const struct rect *r, const struct font *f);

#endif
