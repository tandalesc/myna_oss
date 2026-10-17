/* SPDX-License-Identifier: MIT */
/* The text box: text typed on the twelve keys, as on the phones of the era, in a rounded box of the theme (the
 * conversation's "Write a message" box of the design). Text is UTF-8.
 *
 * The keys are laid out as on the slider phones of the era: # is the space, * the case, and holding them
 * changes the input method and opens the symbols.
 *
 * Input methods, stepped by # held: predictive text (when the setting SET_PREDICTIVE is on, every box starts in it),
 * multi-tap letters, 123. Moving into or out of predictive text also sets the setting, so the next box starts the
 * same way. The case, stepped by *: Abc (a capital at the start of a sentence), abc, ABC. The mode shows at the right
 * of the box's last line with the count ("Abc 12/160"); predictive text has the book sign in front, and in Abc it shows
 * "Abc" where the next word starts a sentence and "abc" elsewhere.
 *
 * Predictive text (services/words.h): one press per letter. The word being typed is underlined and shows the
 * likeliest word for the keys so far; * (or down) shows the next candidate, up the one before, and from the first
 * such step the candidates show as a list over the box. # takes the word with a space, right takes it as it is, and
 * also takes a completion when one is offered: a longer word that fits is shown after the cursor in the muted colour.
 * A sequence no word has offers Spell on the left soft key (also after going round all the candidates): a box of its
 * own where the word is typed with multi-tap, then added to My words and put in the text. 1 gives punctuation: after
 * a word, "." (1 again or * for the next sign: , ? ! ' " - ...), inside a word an apostrophe when a word has one there
 * ("I'm"). 0 gives 0, and + when pressed again within 1 s.
 *
 * Multi-tap: each number key holds letters (2 abc ... 9 wxyz, 1 punctuation, 0 then +, a few accented letters after
 * the digit); the same key again within 1 s steps through them, another key or the pause takes the letter, which is
 * underlined while it is chosen. # ends the letter and types a space. 123: digits, * and #.
 *
 * In every mode: a number key held gives its digit, * held opens the symbols (a grid of signs to insert), C deletes
 * (held: everything), left / right move the cursor.
 *
 * The box shows as many lines as it is high, scrolled to the cursor's line. A screen whose box grows with the text asks
 * text_entry_lines(). The count can be the caller's: a text message shows its parts ("Abc 2 parts 40/153").
 *
 * Phone numbers: with `phone` set, the number keys type digits only, * gives '+' (a second tap within 1 s: '*'),
 * # types '#'; the mode shows as "123".
 *
 * A screen with a text box passes it every key first that it does not use itself, and KEY_SOFT_LEFT before its own
 * use of it (the box takes it while it offers Spell; the label is shown by the box through ui_soft_override). */
#ifndef MYNA_UI_TEXTENTRY_H
#define MYNA_UI_TEXTENTRY_H

#include <stdint.h>

#include "gfx/gfx.h"

struct timer;

#define TEXT_MAX 612           /* four parts of a text message in the GSM 7-bit alphabet (bytes of UTF-8) */
#define TEXT_KEYS 24           /* key presses of one predictive word */

enum text_mode { TEXT_PREDICT, TEXT_LETTERS, TEXT_NUMBERS, TEXT_MODES };    /* the input method */
enum text_case { CASE_SENTENCE, CASE_LOWER, CASE_UPPER, CASES };              /* Abc, abc, ABC */

struct text_entry {
    struct rect r;             /* the box */
    const char *placeholder;   /* shown while empty */
    /* the count at the right of the last line, after the mode's name; 0: "<characters>/<max>" */
    void (*count)(const struct text_entry *e, char *out, unsigned max);
    uint8_t phone;             /* a phone number: digits, + * # only */
    uint8_t plain;             /* never predictive (the spelling box) */
    struct timer *tap_timer;   /* the screen's timer for the multi-tap pause; it calls text_entry_timer() */
    uint16_t max;              /* bytes, at most TEXT_MAX */
    uint16_t len, cursor;
    uint8_t mode;              /* enum text_mode */
    uint8_t shift;             /* enum text_case */
    uint8_t star_did;          /* what the last * press did (for * held): 1 a candidate, 2 the case, 3 a sign */
    uint8_t hash_put;          /* the last # press typed a character (for # held) */
    int8_t tap_key;            /* the key being tapped (an index in the key table), -1 none */
    uint8_t tap_count;
    uint8_t tap_upper;         /* the letter being tapped is a capital */
    /* predictive: the word being chosen */
    uint8_t candidate, candidates;
    uint8_t exact;             /* the candidates are whole words (else beginnings of longer ones) */
    uint8_t cycled;            /* went round all the candidates: Spell is offered */
    uint8_t list_shown;        /* the candidates as a list over the box (after * , up or down) */
    uint8_t list_kept;         /* this key keeps the list */
    uint8_t word_cap;          /* the word starts a sentence */
    uint8_t dirty;             /* 1: typed (maybe one line to draw), 2: everything */
    uint32_t shown;            /* where the lines were at the last paint (a sum of the layout) */
    uint16_t word_start;       /* where the word being chosen starts in the text */
    char keys[TEXT_KEYS];      /* its keys ("4663"; "1" for punctuation) */
    char completion[32];       /* the rest of a longer word offered after the cursor, or "" */
    char text[TEXT_MAX + 1];
};

void text_entry_init(struct text_entry *e, const struct rect *r, struct timer *tap_timer);
int text_entry_key(struct text_entry *e, unsigned key);   /* 1 if used (C on an empty box is not) */
void text_entry_timer(struct text_entry *e);               /* the multi-tap pause is over: take the letter */
void text_entry_commit(struct text_entry *e);              /* take the letter or the word being chosen */
void text_entry_clear(struct text_entry *e);
void text_entry_set(struct text_entry *e, const char *text);   /* the text (cut to max), the cursor at its end */
void text_entry_touch(struct text_entry *e);
void text_entry_paint(struct text_entry *e, const struct surface *s);
int text_entry_lines(const struct text_entry *e, int width);  /* lines the text needs in a box `width` wide */
int text_entry_height(int lines);                             /* the height of a box that shows `lines` lines */
const char *text_entry_mode_name(const struct text_entry *e);
/* the symbols, over the screen of the box (an Options row "Add symbol"); the one chosen goes in at the cursor */
void text_entry_symbols(struct text_entry *e);
/* the left soft key's label the box wants now ("Spell"), or 0; the box sets it with ui_soft_override() itself */
const char *text_entry_soft_left(const struct text_entry *e);

#endif
