/* SPDX-License-Identifier: MIT */
/* The text box: predictive text, multi-tap, digits; the symbols and Spell screens (ui/textentry.h). */
#include <stdint.h>

#include "assets.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "kernel/timer.h"
#include "lib/mem.h"
#include "lib/print.h"
#include "lib/utf8.h"
#include "services/settings.h"
#include "services/words.h"
#include "ui/layout.h"
#include "ui/textentry.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

#define TAP_MS     1000        /* the pause that takes a multi-tap letter */
#define MAX_LINES  48          /* TEXT_MAX of narrow letters, with room */
#define COUNT_GAP  8           /* between the text and the count on the last line */
#define SIGN_GAP   3           /* between the book sign and the mode's name */

/* the keys of the pad and their letters (UTF-8: a few accented letters after the digit) */
static const uint8_t pad_keys[11] = { KEY_0, KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9, KEY_STAR };
static const char *const letters[10] = {
    "0+", ".,?!'\"-()@/:;_1", "abc2\xC3\xA4\xC3\xA0\xC3\xA5\xC3\xA7", "def3\xC3\xA9\xC3\xA8", "ghi4\xC3\xAC", "jkl5",
    "mno6\xC3\xB6\xC3\xB2\xC3\xB1", "pqrs7\xC3\x9F", "tuv8\xC3\xBC\xC3\xB9", "wxyz9",
};
/* predictive text: the signs of key 1 after a word, the likeliest first */
static const char *const signs[] = { ".", ",", "?", "!", "'", "\"", "-", ":", ";", "(", ")", "@", "/", "&" };
#define SIGNS (int)(sizeof signs / sizeof signs[0])
static const char *const case_names[CASES] = { "Abc", "abc", "ABC" };

/* the candidates of the word being chosen: one box chooses at a time */
static char cands[WORDS_CANDIDATES][WORD_MAX];
static const struct text_entry *cands_of;

static void open_symbols(struct text_entry *e);
static void open_spell(struct text_entry *e);
static void close_list(struct text_entry *e);

/* ---- characters ---- */

static uint32_t upper(uint32_t c)
{
    if ((c >= 'a' && c <= 'z') || (c >= 0xE0 && c <= 0xFE && c != 0xF7) || (c >= 0x430 && c <= 0x44F))
        return c - 32;
    if (c >= 0x450 && c <= 0x45F)
        return c - 80;
    return c;
}

/* character n of a UTF-8 set into out (with its 0); returns its bytes */
static int nth_char(const char *set, int n, char *out)
{
    int i = 0;
    while (n-- > 0 && set[i])
        i = text_next(set, i);
    int j = set[i] ? text_next(set, i) : i;
    memcpy(out, set + i, (size_t)(j - i));
    out[j - i] = 0;
    return j - i;
}

static int set_chars(const char *set)
{
    return text_chars(set, (int)strlen(set));
}

/* the first character of s as a capital, into out (WORD_MAX) */
static void capitalise(const char *s, char *out)
{
    const uint8_t *p = (const uint8_t *)s;
    uint32_t c = gfx_utf8_next(&p);
    char head[4];
    int n = (int)utf8_put(upper(c), head);
    copy_text(out, "", WORD_MAX);
    if (n + strlen((const char *)p) + 1 > WORD_MAX) {
        copy_text(out, s, WORD_MAX);
        return;
    }
    memcpy(out, head, (size_t)n);
    copy_text(out + n, (const char *)p, WORD_MAX - (unsigned)n);
}

/* a candidate as it goes into the text: all capitals in ABC, a capital first at a sentence's start in Abc */
static void shape(const struct text_entry *e, const char *w, char *out)
{
    if (e->shift == CASE_UPPER) {
        const uint8_t *p = (const uint8_t *)w;
        unsigned n = 0;
        while (*p) {
            char c[4];
            unsigned k = utf8_put(upper(gfx_utf8_next(&p)), c);
            if (n + k + 1 > WORD_MAX)
                break;
            memcpy(out + n, c, k);
            n += k;
        }
        out[n] = 0;
    } else if (e->word_cap) {
        capitalise(w, out);
    } else {
        copy_text(out, w, WORD_MAX);
    }
}

/* ---- the text ---- */

void text_entry_touch(struct text_entry *e)
{
    e->dirty = 2;              /* everything */
    ui_soft_override(0, text_entry_soft_left(e));
    ui_changed();
}

/* the text changed by a key: when the lines stay where they were, only the cursor's line and the count are drawn */
static void typed(struct text_entry *e)
{
    e->dirty |= 1;
    ui_soft_override(0, text_entry_soft_left(e));
    ui_changed();
}

static int insert_n(struct text_entry *e, const char *s, int n)
{
    if (e->len + n > e->max)
        return 0;
    memmove(e->text + e->cursor + n, e->text + e->cursor, (size_t)(e->len - e->cursor + 1));
    memcpy(e->text + e->cursor, s, (size_t)n);
    e->cursor = (uint16_t)(e->cursor + n);
    e->len = (uint16_t)(e->len + n);
    return 1;
}

static int insert(struct text_entry *e, const char *s)
{
    return insert_n(e, s, (int)strlen(s));
}

static void delete_before(struct text_entry *e)
{
    int from = text_prev(e->text, e->cursor), n = e->cursor - from;
    memmove(e->text + from, e->text + e->cursor, (size_t)(e->len - e->cursor + 1));
    e->cursor = (uint16_t)from;
    e->len = (uint16_t)(e->len - n);
}

/* the cursor is at the start of a sentence: the text's start, or after ". " (or ! ? or a new line) */
static int sentence_start(const struct text_entry *e)
{
    int j = e->cursor - 1;
    if (j < 0)
        return 1;
    if (e->text[j] == '\n')
        return 1;
    if (e->text[j] != ' ')
        return 0;
    while (j >= 0 && (e->text[j] == ' ' || e->text[j] == '\n'))
        j--;
    return j < 0 || e->text[j] == '.' || e->text[j] == '!' || e->text[j] == '?';
}

/* ---- predictive text ---- */

static int composing(const struct text_entry *e)
{
    return e->keys[0] != 0;
}

static int composing_sign(const struct text_entry *e)
{
    return e->keys[0] == '1' && !e->keys[1];
}

const char *text_entry_soft_left(const struct text_entry *e)
{
    return composing(e) && !composing_sign(e) && (!e->candidates || e->cycled) ? "Spell" : 0;
}

static void refill(struct text_entry *e)
{
    int exact = 1;
    e->candidates = (uint8_t)(composing_sign(e) ? SIGNS : words_candidates(e->keys, cands, &exact));
    e->exact = (uint8_t)exact;
    cands_of = e;
    if (e->candidate >= e->candidates)
        e->candidate = 0;
}

static const char *candidate(const struct text_entry *e, int i)
{
    return composing_sign(e) ? signs[i] : cands[i];
}

/* a sequence no word has: the likeliest beginning of its longest known part, then the first letter of each key */
static void unknown_word(struct text_entry *e, char *out)
{
    char keys[TEXT_KEYS];
    int n = (int)strlen(e->keys), k = n - 1, exact;
    out[0] = 0;
    for (; k > 0; k--) {
        memcpy(keys, e->keys, (size_t)k);
        keys[k] = 0;
        if (words_candidates(keys, cands, &exact)) {
            copy_text(out, cands[0], WORD_MAX);
            break;
        }
    }
    if (k < 0)
        k = 0;
    unsigned len = (unsigned)strlen(out);
    for (int i = k; i < n && len + 2 < WORD_MAX; i++)
        out[len++] = e->keys[i] == '1' ? '\'' : letters[e->keys[i] - '0'][0];
    out[len] = 0;
    e->candidates = 0;
    cands_of = 0;
}

/* show the candidate in place of the word being chosen, and a completion after it when one fits */
static void show_word(struct text_entry *e)
{
    char w[WORD_MAX], shown[WORD_MAX];
    if (e->candidates)
        copy_text(w, candidate(e, e->candidate), sizeof w);
    else
        unknown_word(e, w);
    if (composing_sign(e))
        copy_text(shown, w, sizeof shown);
    else
        shape(e, w, shown);
    if ((int)strlen(shown) > e->max - (e->len - (e->cursor - e->word_start))) {
        /* no room for the word: the last key is not taken */
        e->keys[strlen(e->keys) - 1] = 0;
        if (e->keys[0]) {
            e->candidate = 0;
            refill(e);
            show_word(e);
        }
        return;
    }
    while (e->cursor > e->word_start)
        delete_before(e);
    insert(e, shown);
    e->completion[0] = 0;
    char full[WORD_MAX];
    unsigned s = (unsigned)strlen(w);
    if (e->candidates && e->candidate == 0 && !composing_sign(e) && strlen(e->keys) >= 2 &&
        words_complete(e->keys, w, full) > (int)s)
        copy_text(e->completion, full + s, sizeof e->completion);
}

/* the word being chosen is taken as it shows; a word chosen over the first candidate is learnt */
static void commit_word(struct text_entry *e)
{
    if (!composing(e))
        return;
    if (!composing_sign(e) && e->candidates && e->candidate > 0 && cands_of == e)
        words_learn(cands[e->candidate]);
    e->keys[0] = 0;
    e->completion[0] = 0;
    e->candidate = e->candidates = 0;
    e->cycled = 0;
}

/* take the letter being tapped (or the predictive word) as it is */
void text_entry_commit(struct text_entry *e)
{
    e->tap_key = -1;
    if (e->tap_timer)
        timer_stop(e->tap_timer);
    commit_word(e);
    close_list(e);
}

static void start_word(struct text_entry *e, const char *keys)
{
    commit_word(e);
    e->word_start = e->cursor;
    e->word_cap = (uint8_t)(e->shift == CASE_SENTENCE && sentence_start(e));
    copy_text(e->keys, keys, sizeof e->keys);
    e->candidate = 0;
    e->cycled = 0;
    refill(e);
    show_word(e);
    if (!composing(e))
        e->word_start = e->cursor;
}

/* one key less of the word being chosen (C, or a held key that becomes its digit) */
static void drop_key(struct text_entry *e)
{
    unsigned n = (unsigned)strlen(e->keys);
    if (n)
        e->keys[n - 1] = 0;
    e->completion[0] = 0;
    if (e->keys[0]) {
        e->candidate = 0;
        e->cycled = 0;
        refill(e);
        show_word(e);
    } else {
        while (e->cursor > e->word_start)
            delete_before(e);
        commit_word(e);
    }
}

static void predict_key(struct text_entry *e, int idx)
{
    unsigned n = (unsigned)strlen(e->keys);
    if (idx == 1) {
        if (composing_sign(e)) {
            e->candidate = (uint8_t)((e->candidate + 1) % SIGNS);    /* 1 again: the next sign */
            show_word(e);
            return;
        }
        if (composing(e) && n + 1 < sizeof e->keys) {
            /* an apostrophe, if a word has one here ("I'm"); else the word is done and a sign follows */
            char keys[TEXT_KEYS];
            int exact;
            memcpy(keys, e->keys, n);
            keys[n] = '1';
            keys[n + 1] = 0;
            if (words_candidates(keys, cands, &exact)) {
                copy_text(e->keys, keys, sizeof e->keys);
                e->candidate = 0;
                refill(e);
                show_word(e);
                return;
            }
            refill(e);         /* the candidates of the word as it was, for commit_word */
        }
        start_word(e, "1");
        return;
    }
    if (composing_sign(e))
        commit_word(e);
    if (!composing(e)) {
        char k[2] = { (char)('0' + idx), 0 };
        start_word(e, k);
        return;
    }
    if (n + 1 >= sizeof e->keys)
        return;
    e->keys[n] = (char)('0' + idx);
    e->keys[n + 1] = 0;
    e->candidate = 0;
    e->cycled = 0;
    refill(e);
    show_word(e);
}

/* another candidate: dir +1 or -1, round */
static void next_candidate(struct text_entry *e, int dir)
{
    if (e->candidates > 1) {
        int c = e->candidate + dir;
        if (c >= e->candidates) {
            c = 0;
            e->cycled = 1;     /* none of them: Spell is offered */
        } else if (c < 0) {
            c = e->candidates - 1;
        }
        e->candidate = (uint8_t)c;
    } else {
        e->cycled = 1;
    }
    show_word(e);
    if (e->candidates > 1) {
        e->list_shown = 1;     /* the list of the candidates shows from the first step through them */
        e->list_kept = 1;
    }
}

/* ---- multi-tap ---- */

static void tap(struct text_entry *e, int idx)
{
    const char *set = idx < 10 ? letters[idx] : "";
    char c[8];
    if (e->phone) {
        if (idx != 10) {
            text_entry_commit(e);
            c[0] = (char)('0' + idx);
            c[1] = 0;
            insert(e, c);
            return;
        }
        set = "+*";            /* '+' first: what a number needs most */
    } else if (e->mode == TEXT_NUMBERS) {
        text_entry_commit(e);
        c[0] = (char)('0' + idx);
        c[1] = 0;
        insert(e, c);
        return;
    }
    if (e->tap_key == idx) {
        /* the same key again: the next letter of its set, in place of the one shown */
        e->tap_count = (uint8_t)((e->tap_count + 1) % set_chars(set));
        delete_before(e);
    } else {
        text_entry_commit(e);
        e->tap_key = (int8_t)idx;
        e->tap_count = 0;
        e->tap_upper = !e->phone && (e->shift == CASE_UPPER || (e->shift == CASE_SENTENCE && sentence_start(e)));
    }
    nth_char(set, e->tap_count, c);
    if (e->tap_upper) {
        const uint8_t *p = (const uint8_t *)c;
        utf8_put(upper(gfx_utf8_next(&p)), c);
        c[text_next(c, 0)] = 0;
    }
    if (!insert(e, c)) {
        e->tap_key = -1;
        return;
    }
    if (e->tap_timer)
        timer_start(e->tap_timer, KTIME_MS(TAP_MS), 0);
}

/* a number key held: the letter (or the key of a word) its press gave becomes the digit */
static void held_digit(struct text_entry *e, int idx)
{
    char d[2] = { (char)('0' + idx), 0 };
    if (e->mode == TEXT_PREDICT && !e->plain && idx != 0) {
        if (composing(e)) {
            if (composing_sign(e)) {
                while (e->cursor > e->word_start)
                    delete_before(e);
                commit_word(e);
            } else {
                drop_key(e);
                commit_word(e);
            }
        }
    } else if (e->mode == TEXT_NUMBERS) {
        return;                /* a digit already */
    } else if (e->tap_key == idx) {
        delete_before(e);
        e->tap_key = -1;
    }
    text_entry_commit(e);
    insert(e, d);
}

/* ---- keys ---- */

static int pad_index(unsigned key)
{
    for (int i = 0; i < 11; i++)
        if (key == pad_keys[i])
            return i;
    return -1;
}

static int key_inner(struct text_entry *e, unsigned key);

/* the list of candidates goes when a key does something else: what was under it is drawn again */
static void close_list(struct text_entry *e)
{
    if (!e->list_shown)
        return;
    e->list_shown = 0;
    ui_redraw();
}

int text_entry_key(struct text_entry *e, unsigned key)
{
    e->list_kept = 0;
    int used = key_inner(e, key);
    if (!e->list_kept)
        close_list(e);
    return used;
}

static int key_inner(struct text_entry *e, unsigned key)
{
    int idx = pad_index(key & ~(unsigned)KEY_HELD);
    if (key & KEY_HELD) {
        if (e->phone)
            return 0;
        if (idx >= 0 && idx < 10) {
            held_digit(e, idx);
            typed(e);
            return 1;
        }
        if (key == (KEY_HELD | KEY_CLEAR) && e->len) {
            text_entry_clear(e);
            return 1;
        }
        if (key == (KEY_HELD | KEY_STAR)) {
            /* the symbols, in place of what the press did */
            if (e->star_did == 1)
                next_candidate(e, -1);
            else if (e->star_did == 2)
                e->shift = (uint8_t)((e->shift + CASES - 1) % CASES);
            else if (e->star_did == 3 && e->cursor && e->text[e->cursor - 1] == '*')
                delete_before(e);
            e->star_did = 0;
            text_entry_commit(e);
            typed(e);
            open_symbols(e);
            return 1;
        }
        if (key == (KEY_HELD | KEY_HASH)) {
            /* the next input method, in place of the space (or #) the press typed */
            if (e->hash_put && e->cursor)
                delete_before(e);
            e->hash_put = 0;
            text_entry_commit(e);
            do
                e->mode = (uint8_t)((e->mode + 1) % TEXT_MODES);
            while (e->mode == TEXT_PREDICT && e->plain);
            if (!e->plain && e->mode != TEXT_NUMBERS)
                settings_set(SET_PREDICTIVE, e->mode == TEXT_PREDICT);    /* the next box starts the same way */
            /* said for a moment besides the sign, so a hold that was not meant is seen for what it did (the next key
               takes the toast away) */
            ui_note_ms(e->mode == TEXT_PREDICT ? "Predictive text" : e->mode == TEXT_LETTERS ? "Letters" : "Numbers", 1000);
            typed(e);
            return 1;
        }
        return 0;
    }
    int predictive = e->mode == TEXT_PREDICT && !e->phone && !e->plain;
    if (key == KEY_STAR && !e->phone) {
        if (predictive && composing(e)) {
            next_candidate(e, 1);
            e->star_did = 1;
        } else if (e->mode == TEXT_NUMBERS) {
            insert(e, "*");
            e->star_did = 3;
        } else {
            /* the case: Abc, abc, ABC */
            text_entry_commit(e);
            e->shift = (uint8_t)((e->shift + 1) % CASES);
            e->star_did = 2;
        }
        typed(e);
        return 1;
    }
    if (idx >= 0) {
        if (predictive && idx >= 1) {
            if (e->tap_key >= 0) {
                e->tap_key = -1;   /* a 0 or + being tapped is taken */
                if (e->tap_timer)
                    timer_stop(e->tap_timer);
            }
            predict_key(e, idx);
        } else {
            tap(e, idx);           /* letters, digits, and 0 then + in predictive text */
        }
        typed(e);
        return 1;
    }
    switch (key) {
    case KEY_SOFT_LEFT:
        if (!text_entry_soft_left(e))
            return 0;
        open_spell(e);
        return 1;
    case KEY_HASH:
        /* the space: it takes the word (or the letter) being chosen; # itself in a number and in 123 */
        text_entry_commit(e);
        e->hash_put = (uint8_t)insert(e, e->phone || e->mode == TEXT_NUMBERS ? "#" : " ");
        break;
    case KEY_CLEAR:
        if (composing(e)) {
            if (composing_sign(e)) {
                while (e->cursor > e->word_start)
                    delete_before(e);
                commit_word(e);
            } else {
                drop_key(e);
            }
            break;
        }
        if (!e->cursor)
            return 0;
        text_entry_commit(e);
        delete_before(e);
        break;
    case KEY_LEFT:
        text_entry_commit(e);
        if (e->cursor)
            e->cursor = (uint16_t)text_prev(e->text, e->cursor);
        break;
    case KEY_RIGHT:
        if (composing(e)) {
            if (e->completion[0]) {
                /* the longer word offered: its rest goes in, and the word is taken */
                insert(e, e->completion);
                e->completion[0] = 0;
            }
            commit_word(e);
            break;
        }
        text_entry_commit(e);
        if (e->cursor < e->len)
            e->cursor = (uint16_t)text_next(e->text, e->cursor);
        break;
    case KEY_UP:
    case KEY_DOWN:
        if (!composing(e))
            return 0;
        next_candidate(e, key == KEY_DOWN ? 1 : -1);
        break;
    default:
        return 0;
    }
    typed(e);
    return 1;
}

void text_entry_timer(struct text_entry *e)
{
    if (e->tap_key < 0)
        return;
    e->tap_key = -1;
    typed(e);
}

void text_entry_clear(struct text_entry *e)
{
    e->len = e->cursor = 0;
    e->text[0] = 0;
    e->tap_key = -1;
    e->keys[0] = 0;
    e->completion[0] = 0;
    e->candidate = e->candidates = 0;
    e->cycled = 0;
    if (e->tap_timer)
        timer_stop(e->tap_timer);
    text_entry_touch(e);
}

void text_entry_set(struct text_entry *e, const char *text)
{
    text_entry_clear(e);
    copy_text(e->text, text, (unsigned)e->max + 1);
    e->len = e->cursor = (uint16_t)strlen(e->text);
}

void text_entry_init(struct text_entry *e, const struct rect *r, struct timer *tap_timer)
{
    e->r = *r;
    e->tap_timer = tap_timer;
    if (!e->max || e->max > TEXT_MAX)
        e->max = TEXT_MAX;
    e->mode = !e->phone && !e->plain && settings_get(SET_PREDICTIVE) ? TEXT_PREDICT : TEXT_LETTERS;
    e->shift = CASE_SENTENCE;
    e->list_shown = 0;
    text_entry_clear(e);
}

const char *text_entry_mode_name(const struct text_entry *e)
{
    if (e->phone || e->mode == TEXT_NUMBERS)
        return "123";
    if (e->shift != CASE_SENTENCE)
        return case_names[e->shift];
    /* Abc: as the next letter will be */
    if (e->mode == TEXT_PREDICT)
        return e->word_cap && composing(e) ? "Abc" : !composing(e) && sentence_start(e) ? "Abc" : "abc";
    return e->tap_key >= 0 ? (e->tap_upper ? "Abc" : "abc") : sentence_start(e) ? "Abc" : "abc";
}

/* ---- drawing ---- */

/* the predictive sign in front of the mode's name */
static int has_sign(const struct text_entry *e)
{
    return e->mode == TEXT_PREDICT && !e->phone && !e->plain;
}

/* the mode's name and the count: "Abc 12/160"; while a word is chosen with several candidates, which one ("2/4") */
static int indicator(const struct text_entry *e, char *buf, unsigned max)
{
    unsigned n = 0;
    char pos[12];
    const char *name = text_entry_mode_name(e);
    if (has_sign(e) && composing(e) && !composing_sign(e)) {
        if (!e->candidates) {
            name = "?";
        } else if (e->candidates > 1) {
            int k = format_uint(pos, (unsigned)e->candidate + 1);
            pos[k++] = '/';
            format_uint(pos + k, e->candidates);
            name = pos;
        }
    }
    for (const char *p = name; *p && n + 2 < max; p++)
        buf[n++] = *p;
    buf[n++] = ' ';
    buf[n] = 0;
    if (e->count) {
        e->count(e, buf + n, max - n);
    } else {
        char num[16];
        int k = format_uint(num, (unsigned)text_chars(e->text, e->len));
        num[k++] = '/';
        format_uint(num + k, e->max);
        copy_text(buf + n, num, max - n);
    }
    return gfx_text_width(theme->number, buf) + (has_sign(e) ? status_predict.w + SIGN_GAP : 0);
}

static int inner_width(int box_w)
{
    return box_w - 2 - 2 * layout.convo.box_pad_x;
}

/* Lines of the text in a box `box_w` wide: starts[0..text_lines) of the text, and starts[text_lines] = len. The count
 * goes at the right of the last line, or on a line of its own under it (one line more) when that line leaves no room
 * for it. Returns the lines with the count's. */
static int wrap(const struct text_entry *e, int box_w, uint16_t *starts, int *text_lines, int *count_w, char *count,
                unsigned count_max)
{
    const struct font *f = theme->body;
    int width = inner_width(box_w), iw = indicator(e, count, count_max);
    int n = text_wrap(f, e->text, e->len, width, starts, MAX_LINES);
    starts[n] = e->len;
    *text_lines = n;
    *count_w = iw;
    int last = e->len ? text_width_n(f, e->text + starts[n - 1], e->len - starts[n - 1])
                      : e->placeholder ? gfx_text_width(f, e->placeholder) : 0;
    return last + COUNT_GAP + iw > width ? n + 1 : n;
}

int text_entry_height(int lines)
{
    return 2 + 2 * layout.convo.box_pad_y + lines * layout.convo.line_h - 1;
}

int text_entry_lines(const struct text_entry *e, int width)
{
    uint16_t starts[MAX_LINES + 1];
    int tl, cw;
    char count[40];
    return wrap(e, width, starts, &tl, &cw, count, sizeof count);
}

/* one line of the box: its text, and on the cursor's line the caret, the letter or word being chosen and a
 * completion; the count at the right of the count's line. `band`: clear the line's band first (a line drawn alone). */
struct box_view {
    const struct rect *r;
    struct rect inner;
    int x0, base0, first, cl, text_lines, count_line, iw;
    const uint16_t *starts;
    const char *count;
};

static void paint_line(const struct text_entry *e, const struct surface *s, const struct box_view *v, int i, int band)
{
    const struct font *f = theme->body;
    int y = v->base0 + (i - v->first) * layout.convo.line_h;
    int count_x = v->r->x + v->r->w - 1 - layout.convo.box_pad_x - v->iw;
    if (band) {
        struct rect b = { (int16_t)(v->r->x + 3), (int16_t)(y - 11), (int16_t)(v->r->w - 6), 15 };
        gfx_fill(s, &b, ink.surface);
        display_invalidate(&b);
    }
    if (i == v->count_line) {
        int x = count_x;
        if (has_sign(e)) {
            image_draw(s, v->r, &status_predict, x, y - 9, composing(e) ? ink.accent : ink.muted);
            x += status_predict.w + SIGN_GAP;
        }
        gfx_text(s, v->r, theme->number, x, y, v->count, ink.muted, ink.surface);
    }
    if (!e->len) {
        if (i == 0) {
            if (e->placeholder)
                gfx_text(s, &v->inner, f, v->x0, y, e->placeholder, ink.muted, ink.surface);
            struct rect caret = { (int16_t)v->x0, (int16_t)(y - 11), 1, 14 };
            gfx_fill(s, &caret, ink.accent);
        }
        return;
    }
    if (i >= v->text_lines)
        return;
    int a = v->starts[i], b = v->starts[i + 1];
    while (b > a && (e->text[b - 1] == ' ' || e->text[b - 1] == '\n') && b != e->cursor)
        b--;
    text_draw_n_on(s, &v->inner, f, v->x0, y, e->text + a, b - a, ink.text, ink.surface);
    if (i != v->cl)
        return;
    int cx = v->x0 + text_width_n(f, e->text + a, e->cursor - a);
    if (e->tap_key >= 0 || composing(e)) {
        /* the letter (or word) being chosen is underlined; a word no list has, in dashes */
        int from = composing(e) ? e->word_start : text_prev(e->text, e->cursor);
        if (from < a)
            from = a;
        int ux = v->x0 + text_width_n(f, e->text + a, from - a);
        if (composing(e) && !e->candidates && !composing_sign(e)) {
            for (int x = ux; x < cx; x += 4) {
                struct rect u = { (int16_t)x, (int16_t)(y + 2), (int16_t)(x + 2 < cx ? 2 : cx - x), 2 };
                gfx_fill(s, &u, ink.accent);
            }
        } else {
            struct rect u = { (int16_t)ux, (int16_t)(y + 2), (int16_t)(cx - ux), 2 };
            gfx_fill(s, &u, ink.accent);
        }
    }
    if (e->completion[0]) {
        /* the rest of a longer word, after the caret, if it fits on the line */
        int right = v->inner.x + v->inner.w - layout.convo.box_pad_x;
        if (i == v->count_line)
            right = count_x - COUNT_GAP;
        if (cx + 1 + gfx_text_width(f, e->completion) <= right)
            gfx_text(s, &v->inner, f, cx + 1, y, e->completion, ink.muted, ink.surface);
    }
    struct rect caret = { (int16_t)cx, (int16_t)(y - 11), 1, 14 };
    gfx_fill(s, &caret, ink.accent);
}

static void paint_box(struct text_entry *e, const struct surface *s)
{
    if (!e->dirty)
        return;
    const struct rect *r = &e->r;
    int lh = layout.convo.line_h;
    uint16_t starts[MAX_LINES + 1];
    char count[40];
    struct box_view v = {
        .r = r, .inner = { (int16_t)(r->x + 1), (int16_t)(r->y + 1), (int16_t)(r->w - 2), (int16_t)(r->h - 2) },
        .x0 = r->x + 1 + layout.convo.box_pad_x, .base0 = r->y + 1 + layout.convo.box_pad_y + 12, .starts = starts,
        .count = count,
    };
    int lines = wrap(e, r->w, starts, &v.text_lines, &v.iw, count, sizeof count);
    int visible = (r->h - 2 - 2 * layout.convo.box_pad_y + 1) / lh;
    if (visible < 1)
        visible = 1;
    /* the first line shown: the cursor's line in view, and the count's line too when the cursor is on the last */
    while (v.cl + 1 < v.text_lines && e->cursor >= starts[v.cl + 1])
        v.cl++;
    v.first = v.cl - visible + 1 > 0 ? v.cl - visible + 1 : 0;
    if (v.cl == v.text_lines - 1 && lines - visible > v.first)
        v.first = lines - visible;
    v.count_line = lines - 1;

    /* where the lines are: the same as at the last paint, and the cursor on the text's last line, when only that
       line (and the count) changed */
    uint32_t sum = (uint32_t)r->y * 7919u + (uint32_t)r->h * 131u + (uint32_t)lines * 31u + (uint32_t)v.first * 17u +
                   (uint32_t)v.cl * 3u + (e->len ? 1u : 0u);
    for (int i = 0; i <= v.cl && i < v.text_lines; i++)
        sum = sum * 33u + starts[i];
    int partial = e->dirty == 1 && sum == e->shown && v.cl == v.text_lines - 1;
    e->dirty = 0;
    e->shown = sum;
    if (partial) {
        paint_line(e, s, &v, v.cl, 1);
        if (v.count_line != v.cl && v.count_line >= v.first && v.count_line < v.first + visible)
            paint_line(e, s, &v, v.count_line, 1);
        return;
    }

    const struct theme *t = theme;
    int R = t->field_radius;
    ui_backdrop(s, r);
    gfx_round_rect(s, 0, r, R, ink.surface, ink.rule);
    /* the box is sunk a little: a shade along the inside of its top */
    struct rect shade = { (int16_t)(r->x + R), (int16_t)(r->y + 1), (int16_t)(r->w - 2 * R), 1 };
    gfx_blend_fill(s, &shade, 0, 3);
    shade.y++;
    gfx_blend_fill(s, &shade, 0, 1);
    for (int i = v.first; i < lines && i < v.first + visible; i++)
        paint_line(e, s, &v, i, 0);
    display_invalidate(r);
}

/* The candidates as a small list over the box, from the word's left edge: up to LIST_ROWS of them round the one
 * shown, that one on an accent bar. It is drawn after the box on every paint while it shows (what the screen draws
 * under it, a new message block, cannot hide it); closing it draws the screen again (close_list). */
#define LIST_ROWS  4
#define LIST_ROW_H 22
#define LIST_PAD   10

static void paint_list(struct text_entry *e, const struct surface *s)
{
    const struct font *f = theme->row, *fs = theme->row_selected;
    int n = e->candidates, rows = n < LIST_ROWS ? n : LIST_ROWS;
    int first = e->candidate - 1;
    if (first > n - rows)
        first = n - rows;
    if (first < 0)
        first = 0;
    char w[WORD_MAX];
    int width = 0;
    for (int i = 0; i < n; i++) {
        shape(e, candidate(e, i), w);
        int k = gfx_text_width(fs, w);
        width = k > width ? k : width;
    }
    width += 2 * LIST_PAD;
    if (width < 84)
        width = 84;
    /* from the word's left edge on its line */
    uint16_t starts[MAX_LINES + 1];
    int tl, cw, cl = 0;
    char count[40];
    wrap(e, e->r.w, starts, &tl, &cw, count, sizeof count);
    while (cl + 1 < tl && e->word_start >= starts[cl + 1])
        cl++;
    int x = e->r.x + 1 + layout.convo.box_pad_x - LIST_PAD +
            text_width_n(theme->body, e->text + starts[cl], e->word_start - starts[cl]);
    if (x + width > DISPLAY_W - 4)
        x = DISPLAY_W - 4 - width;
    if (x < 4)
        x = 4;
    int h = rows * LIST_ROW_H + 6;
    struct rect card = { (int16_t)x, (int16_t)(e->r.y - 4 - h), (int16_t)width, (int16_t)h };
    gfx_round_rect(s, 0, &card, 8, ink.surface, ink.rule);
    for (int i = 0; i < rows; i++) {
        int c = first + i;
        struct rect row = { (int16_t)(card.x + 3), (int16_t)(card.y + 3 + i * LIST_ROW_H), (int16_t)(card.w - 6),
                            LIST_ROW_H };
        shape(e, candidate(e, c), w);
        if (c == e->candidate) {
            gfx_round_rect(s, &card, &row, 6, ink.accent, GFX_NO_BORDER);
            gfx_text_over(s, &row, fs, row.x + LIST_PAD - 3, row.y + 16, w, ink.on_accent);
        } else {
            gfx_text(s, &row, f, row.x + LIST_PAD - 3, row.y + 16, w, ink.text, ink.surface);
        }
    }
    display_invalidate(&card);
}

void text_entry_paint(struct text_entry *e, const struct surface *s)
{
    paint_box(e, s);
    if (e->list_shown && composing(e) && e->candidates > 1)
        paint_list(e, s);
}

/* ---- the symbols: a grid of signs over the screen of the box ---- */

#define SYM_COLS 6
#define SYM_ROWS 6
#define SYM_W    40
#define SYM_H    40
static const char *const symbols[SYM_COLS * SYM_ROWS] = {
    ".", ",", "?", "!", "'", "\"", "-", "(", ")", ":", ";", "@", "/", "&", "_", "+", "=", "*", "#", "%", "$",
    "\xE2\x82\xAC", "\xC2\xA3", "<", ">", "[", "]", "~", "^", "\xC2\xBF", "\xC2\xA1", "\xC2\xA7", "\xC2\xB0",
    "\xE2\x80\xA6", "\\", "\xC2\xB6",
};
#define SYM_NEWLINE (SYM_COLS * SYM_ROWS - 1)  /* the pilcrow stands for a new line */

static struct text_entry *target;          /* the box the symbols or the spelling go to */
static int sym_sel, sym_drawn_sel = -1;
static uint8_t sym_full;

static struct rect sym_cell(int i)
{
    const struct rect *c = &layout.content;
    int x0 = (c->w - SYM_COLS * SYM_W) / 2, y0 = c->y + (c->h - SYM_ROWS * SYM_H) / 2;
    return (struct rect){ (int16_t)(x0 + i % SYM_COLS * SYM_W), (int16_t)(y0 + i / SYM_COLS * SYM_H), SYM_W, SYM_H };
}

static void sym_paint_cell(const struct surface *fb, int i)
{
    struct rect r = sym_cell(i);
    ui_backdrop(fb, &r);
    const struct font *f = theme->title_font;
    if (i == sym_sel) {
        struct rect tile = { (int16_t)(r.x + 3), (int16_t)(r.y + 3), (int16_t)(r.w - 6), (int16_t)(r.h - 6) };
        gfx_round_rect(fb, &r, &tile, 9, ink.accent, GFX_NO_BORDER);
    }
    int w = gfx_text_width(f, symbols[i]);
    uint16_t fg = i == sym_sel ? ink.on_accent : ink.text;
    gfx_text_over(fb, &r, f, r.x + (r.w - w) / 2, r.y + r.h / 2 + 6, symbols[i], fg);
    display_invalidate(&r);
}

static void sym_enter(int fresh)
{
    if (fresh)
        sym_sel = 0;
    sym_full = 1;
    ui_title("Symbols");
    ui_soft_keys("", "Insert", "Back");
}

static void sym_paint(const struct surface *fb)
{
    if (sym_full) {
        sym_full = 0;
        for (int i = 0; i < SYM_COLS * SYM_ROWS; i++)
            sym_paint_cell(fb, i);
    } else if (sym_drawn_sel != sym_sel) {
        sym_paint_cell(fb, sym_drawn_sel);
        sym_paint_cell(fb, sym_sel);
    }
    sym_drawn_sel = sym_sel;
}

static int sym_key(unsigned k)
{
    int n = SYM_COLS * SYM_ROWS, c = sym_sel % SYM_COLS;
    switch (k) {
    case KEY_LEFT:
        sym_sel = (sym_sel + n - 1) % n;
        break;
    case KEY_RIGHT:
        sym_sel = (sym_sel + 1) % n;
        break;
    case KEY_UP:
        sym_sel = sym_sel >= SYM_COLS ? sym_sel - SYM_COLS : n - SYM_COLS + c;
        break;
    case KEY_DOWN:
        sym_sel = sym_sel + SYM_COLS < n ? sym_sel + SYM_COLS : c;
        break;
    case KEY_SELECT:
        if (target) {
            insert(target, sym_sel == SYM_NEWLINE ? "\n" : symbols[sym_sel]);
            text_entry_touch(target);
        }
        ui_pop();
        return 1;
    case KEY_SOFT_RIGHT:
    case KEY_STAR:
        ui_pop();
        return 1;
    default:
        return 0;
    }
    ui_changed();
    return 1;
}

static const struct screen symbols_screen = {
    .name = "symbols",
    .flags = SCREEN_TITLE,
    .enter = sym_enter,
    .paint = sym_paint,
    .key = sym_key,
};

static void open_symbols(struct text_entry *e)
{
    target = e;
    ui_push(&symbols_screen);
}

void text_entry_symbols(struct text_entry *e)
{
    text_entry_commit(e);
    open_symbols(e);
}

/* ---- Spell: a word typed letter by letter, added to My words ---- */

#define TIMER_SPELL_TAP (UI_TIMER_SCREEN + 0)
static struct text_entry spell_box;
static struct timer spell_tap;
static struct label spell_help;

static void spell_enter(int fresh)
{
    static int made;
    if (!made) {
        ui_timer_init(&spell_tap, TIMER_SPELL_TAP);
        made = 1;
    }
    struct rect r = { layout.convo.compose.x, (int16_t)(layout.content.y + 12), layout.convo.compose.w,
                      (int16_t)text_entry_height(1) };
    if (fresh) {
        spell_box.plain = 1;
        spell_box.max = WORD_MAX - 1;
        spell_box.placeholder = "The new word";
        text_entry_init(&spell_box, &r, &spell_tap);
        spell_box.shift = CASE_LOWER;
    }
    spell_box.r = r;
    text_entry_touch(&spell_box);
    int y = r.y + r.h;
    const struct rect *c = &layout.content;
    spell_help = (struct label){ .r = { c->x, (int16_t)y, c->w, (int16_t)(c->y + c->h - y) }, .font = theme->body,
                                 .fg = ink.muted, .over = 1, .align = ALIGN_LEFT,
                                 .pad = (uint8_t)(layout.convo.compose.x + 2), .base = (int16_t)(y + 22), .dirty = 1 };
    label_set(&spell_help, "Type it letter by letter.");
    ui_title("Spell word");
    ui_soft_keys("", "Save", "Back");
}

static void spell_paint(const struct surface *fb)
{
    text_entry_paint(&spell_box, fb);
    label_paint(&spell_help, fb);
}

/* the spelt word in place of the one being chosen in the box it came from, which takes it */
static void spelt(struct text_entry *e, const char *word)
{
    char shown[WORD_MAX];
    shape(e, word, shown);
    while (e->cursor > e->word_start)
        delete_before(e);
    insert(e, shown);
    e->keys[0] = 0;
    e->completion[0] = 0;
    e->candidate = e->candidates = 0;
    e->cycled = 0;
    words_learn(word);
    e->list_shown = 0;         /* the screen under it is drawn again as it comes back */
    text_entry_touch(e);
}

static int spell_key(unsigned k)
{
    switch (k) {
    case KEY_SELECT:
        text_entry_commit(&spell_box);
        if (spell_box.len && target)
            spelt(target, spell_box.text);
        ui_pop();
        return 1;
    case KEY_SOFT_RIGHT:
        ui_pop();
        return 1;
    }
    return text_entry_key(&spell_box, k);
}

static void spell_timer(unsigned id)
{
    if (id == TIMER_SPELL_TAP)
        text_entry_timer(&spell_box);
}

static void spell_leave(void)
{
    timer_stop(&spell_tap);
}

static const struct screen spell_screen = {
    .name = "spell",
    .flags = SCREEN_TITLE,
    .enter = spell_enter,
    .leave = spell_leave,
    .paint = spell_paint,
    .key = spell_key,
    .timer = spell_timer,
};

static void open_spell(struct text_entry *e)
{
    target = e;
    ui_push(&spell_screen);
}
