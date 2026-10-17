/* SPDX-License-Identifier: MIT */
/* The dialer (a number key on standby) and Calls (menu item 3). Myna cannot make calls yet (the voice path is the
 * next milestone), and says so: the number is typed in large figures, a card under it explains, and the centre soft
 * key offers what works, a text message to that number. The call key shows the same explanation.
 *
 * Smart dialling (the setting, on by default): while keys are typed, the contacts and recent conversations that
 * match them (apps/search.c: a word of the name that starts with the keys' letters, 5-6-4-6 for John; a number that
 * holds the digits) show under the number in place of the card, the best first, four rows in view, the letters or
 * digits that match in the accent. Down goes into the list and up back to the number; with a match chosen the soft
 * keys are Options (Send message, Call, View contact or Add to contacts), Call (not yet: the explanation) and Message
 * (a text to its number: the one that matched, or the contact's first). When nothing matches, the card is back.
 *
 * Keys: the number keys type (holding 0 gives '+'), * and # type themselves, C deletes (held: the whole number; on an
 * empty number it goes back); select or Message writes to the number; the left soft key saves it as a new contact. */
#include <stdint.h>

#include "apps/phone.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "kernel/task.h"
#include "kernel/timer.h"
#include "lib/mem.h"
#include "lib/print.h"
#include "services/settings.h"
#include "sms/sms.h"
#include "sms/store.h"
#include "ui/apps.h"
#include "ui/choice.h"
#include "ui/layout.h"
#include "ui/list.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

#define NUMBER_MAX  24
#define PLUS_MS     600        /* holding 0 this long makes it '+' */
#define TIMER_PLUS  (UI_TIMER_SCREEN + 0)
#define MATCH_ROWS  4          /* two-line rows of matches in view */

static char number[NUMBER_MAX + 1];
static int len;
static struct timer plus_timer;
static uint8_t number_dirty, card_dirty;
static struct search found;
static struct list matches;
static uint8_t showing;        /* the matches are on the screen (else the card) */

static const struct rect number_box = { 0, 58, 240, 48 };
#define NUMBER_BASE (58 + 36)
#define BELOW_Y     118        /* what is under the number: the card, or the matches from MATCH_Y */
#define MATCH_Y     125

static int chosen(void)
{
    return showing && !matches.unfocused;
}

static void soft_keys(void)
{
    if (chosen())
        ui_soft_keys("Options", "Call", "Message");
    else
        ui_soft_keys(len ? "Save" : "", "Message", "Back");
}

static void draw_match(const struct surface *s, const struct rect *r, int row, int sel, uint16_t bg);

/* the matches of the number as it is now: the list, or the card when there are none */
static void search(void)
{
    unsigned n = len && settings_get(SET_SMART_DIAL) ? search_run(&found, number) : 0;
    if (n) {
        struct rect r = { 0, MATCH_Y, DISPLAY_W, MATCH_ROWS * LIST_TALL_H };
        list_init(&matches, &r, (int)n);
        matches.row_h = LIST_TALL_H;
        matches.draw = draw_match;
        matches.unfocused = 1;
    } else if (showing) {
        card_dirty = 1;
    }
    showing = n > 0;
}

static void changed(void)
{
    number_dirty = 1;
    search();
    soft_keys();
    ui_changed();
}

static void enter(int fresh)
{
    static int made;
    if (!made) {
        ui_timer_init(&plus_timer, TIMER_PLUS);
        made = 1;
    }
    if (fresh) {
        len = 0;
        number[0] = 0;
        showing = 0;
    }
    /* again over a screen that closed: the contacts may have changed; the chosen match stays where it was */
    int sel = chosen() ? matches.selected : -1;
    if (settings_get(SET_SMART_DIAL))
        search_begin(&found, 1);
    showing = 0;
    search();
    if (showing && sel >= 0) {
        matches.unfocused = 0;
        list_select(&matches, sel < matches.count ? sel : matches.count - 1);
    }
    ui_title(ui_current() == &calls_screen ? "Calls" : "Phone");
    number_dirty = card_dirty = 1;
    soft_keys();
}

static void leave(void)
{
    timer_stop(&plus_timer);
}

/* the card: what works and what does not yet */
static void paint_card(const struct surface *fb)
{
    const struct theme *t = theme;
    const struct rect *c = &layout.content;
    /* a block as a message's (ui/convo.c): a header line and three lines of text */
    struct rect b = { layout.convo.blocks.x, BELOW_Y + 14, layout.convo.blocks.w,
                      (int16_t)(2 + layout.convo.pad_top + layout.convo.head_h + 3 * layout.convo.line_h +
                                layout.convo.pad_bottom) };
    struct rect area = { 0, BELOW_Y, DISPLAY_W, (int16_t)(c->y + c->h - BELOW_Y) };
    ui_backdrop(fb, &area);
    gfx_round_rect(fb, &area, &b, t->block_radius, ink.surface, ink.rule);
    int x = b.x + 1 + layout.convo.pad_x, y = b.y + 16;
    gfx_text_over(fb, &area, t->meta, x, y, "Calls are not available yet", ink.accent);
    static const char *const lines[3] = { "Myna cannot make calls yet.", "Press Message to send this",
                                          "number a text instead." };
    y += 15;
    for (int i = 0; i < 3; i++, y += layout.convo.line_h)
        gfx_text_over(fb, &area, t->body, x, y, lines[i], ink.text);
    display_invalidate(&area);
}

/* a match: the name (a conversation's number) with the letters that matched in the accent and the time of the
   latest message at the right; under it the number, its matched digits in the accent */
static void draw_match(const struct surface *s, const struct rect *r, int row, int sel, uint16_t bg)
{
    const struct theme *t = theme;
    int pad = layout.list.pad, x = r->x + pad, right = r->x + r->w - pad, from, to;
    char title[48], line[SMS_NUMBER_MAX], when[16];
    int ww = 0;
    uint32_t last = search_when(&found, row);
    if (last) {
        format_when(when, last);
        ww = gfx_text_width(t->value, when) + 8;
        if (sel)
            gfx_text_over(s, r, t->value, right - ww + 8, r->y + 17, when, ink.on_accent);
        else
            gfx_text(s, r, t->value, right - ww + 8, r->y + 17, when, ink.muted, bg);
    }
    search_title(&found, row, title, sizeof title, &from, &to);
    search_draw(s, r, sel ? t->row_selected : t->row, x, r->y + 17, right - ww - x, title, from, to, ink.text, sel,
                bg);
    if (search_number(&found, row, line, sizeof line, &from, &to) < 0) {
        copy_text(line, "Not in contacts", sizeof line);
        from = to = 0;
    }
    search_draw(s, r, t->value, x, r->y + 34, right - x, line, from, to, ink.muted, sel, bg);
}

static void paint(const struct surface *fb)
{
    if (number_dirty) {
        number_dirty = 0;
        ui_backdrop(fb, &number_box);
        const struct font *f = theme->dial_font;
        if (len) {
            /* the end of a number too long for the line */
            const char *shown = number;
            while (gfx_text_width(f, shown) > number_box.w - 24)
                shown++;
            gfx_text_over(fb, &number_box, f, (DISPLAY_W - gfx_text_width(f, shown)) / 2, NUMBER_BASE, shown,
                          ink.text);
        } else {
            const struct font *b = theme->body;
            const char *hint = "Type a number";
            gfx_text_over(fb, &number_box, b, (DISPLAY_W - gfx_text_width(b, hint)) / 2, NUMBER_BASE - 10, hint,
                          ink.muted);
        }
        display_invalidate(&number_box);
    }
    if (showing) {
        list_paint(&matches, fb);
    } else if (card_dirty) {
        paint_card(fb);
    }
    card_dirty = 0;
}

static void add(char c)
{
    if (len < NUMBER_MAX) {
        number[len++] = c;
        number[len] = 0;
    }
    changed();
}

/* ---- a match chosen ---- */

/* the number a text to the chosen match goes to */
static void match_number(char *out, unsigned max)
{
    int from, to;
    if (search_number(&found, matches.selected, out, max, &from, &to) < 0)
        search_title(&found, matches.selected, out, max, &from, &to);     /* a conversation: its number */
}

static void message_match(void)
{
    char n[SMS_NUMBER_MAX];
    match_number(n, sizeof n);
    kprintf("dialer: message to %s\n", n);
    messages_open(n);
}

enum { MO_MESSAGE, MO_CALL, MO_VIEW, MO_ADD };
static uint8_t option_map[4];

static int match_option(int row)
{
    char n[SMS_NUMBER_MAX];
    switch (option_map[row]) {
    case MO_MESSAGE:
        message_match();
        return 1;
    case MO_VIEW:
        contacts_view(search_id(&found, matches.selected));
        return 1;
    case MO_ADD:
        match_number(n, sizeof n);
        contacts_new_with_number(n);
        return 1;
    }
    return 0;
}

static void match_options(void)
{
    struct choice c = { .title = "Options", .chosen = match_option };
    option_map[c.count] = MO_MESSAGE;
    c.rows[c.count++] = (struct choice_row){ .label = "Send message" };
    option_map[c.count] = MO_CALL;
    c.rows[c.count++] = (struct choice_row){ .label = "Call", .why = "Calls are not available yet" };
    if (search_id(&found, matches.selected)) {
        option_map[c.count] = MO_VIEW;
        c.rows[c.count++] = (struct choice_row){ .label = "View contact" };
    } else {
        option_map[c.count] = MO_ADD;
        c.rows[c.count++] = (struct choice_row){ .label = "Add to contacts" };
    }
    choice_open(&c);
}

/* up and down: into the matches, along them, back to the number */
static int move(int down)
{
    if (!showing)
        return 0;
    if (matches.unfocused) {
        if (!down)
            return 1;
        matches.unfocused = 0;
        list_touch_row(&matches, matches.selected);
    } else if (!down && matches.selected == 0) {
        matches.unfocused = 1;
        list_touch_row(&matches, 0);
    } else if (down ? matches.selected + 1 < matches.count : 1) {
        list_select(&matches, matches.selected + (down ? 1 : -1));
    }
    soft_keys();
    return 1;
}

#ifdef MYNA_TEST_HOOKS
/* test builds: *#3678*1# / *#3678*0#: the message store answers "full" / works again (sms/store.h);
   *#9255*1# / *#9255*0#: the animated / still standby (the setting SET_WALLPAPER);
   *#2668*5#: made-up contacts in the RAM index up to 500 (services/contacts.h), to measure smart search */
static int service_code(void)
{
    if (strcmp(number, "*#9255*1#") == 0 || strcmp(number, "*#9255*0#") == 0) {
        settings_set(SET_WALLPAPER, number[7] - '0');
        kprintf("test: wallpaper %c\n", number[7]);
        len = 0;
        number[0] = 0;
        changed();
        return 1;
    }
    if (strcmp(number, "*#2668*5#") == 0) {
        contacts_test_fill(CONTACTS_MAX);
        len = 0;
        number[0] = 0;
        search_begin(&found, 1);
        changed();
        return 1;
    }
    int on = strcmp(number, "*#3678*1#") == 0, off = strcmp(number, "*#3678*0#") == 0;
    if (!on && !off)
        return 0;
    store_simulate_full(on);
    kprintf("test: storage full %s\n", on ? "on" : "off");
    if (off)
        task_post(sms_task(), MSG_SMS_KICK, 0, 0);     /* room again: the service tells the network */
    ui_note(on ? "Test: message memory full" : "Test: message memory back");
    len = 0;
    number[0] = 0;
    changed();
    return 1;
}
#endif

static int key(unsigned k)
{
    static const uint8_t digit_keys[10] = { KEY_0, KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9 };
    if (k == (KEY_HELD | KEY_HASH) && !strcmp(number, "#")) {
        /* # held on standby: the Silent profile on, or back to Normal */
        int silent = settings_get(SET_PROFILE) != PROFILE_SILENT;
        ui_pop();
        settings_set(SET_PROFILE, silent ? PROFILE_SILENT : PROFILE_NORMAL);
        ui_note(silent ? "Silent" : "Normal profile");
        return 1;
    }
    for (int i = 0; i < 10; i++)
        if (k == digit_keys[i]) {
            add((char)('0' + i));
            if (i == 0)
                timer_start(&plus_timer, KTIME_MS(PLUS_MS), 0);
            return 1;
        }
    switch (k) {
    case KEY_STAR:
        add('*');
        return 1;
    case KEY_HASH:
        add('#');
#ifdef MYNA_TEST_HOOKS
        service_code();
#endif
        return 1;
    case KEY_CLEAR:
        if (!len)
            return 0;          /* back */
        number[--len] = 0;
        changed();
        return 1;
    case KEY_HELD | KEY_CLEAR:
        if (len) {
            len = 0;
            number[0] = 0;
            changed();
        }
        return 1;
    case KEY_UP:
    case KEY_DOWN:
        return move(k == KEY_DOWN);
    case KEY_SELECT:
        if (chosen())
            ui_note_ms("Calls are not available yet.\nPress Message to send a text.", 3000);
        else if (!len)
            ui_note("Type a number first");
        else
            messages_open(number);
        return 1;
    case KEY_SOFT_LEFT:
        if (chosen())
            match_options();
        else if (len)
            contacts_new_with_number(number);
        return 1;
    case KEY_SOFT_RIGHT:
        if (chosen())
            message_match();
        else
            ui_pop();
        return 1;
    case KEY_CALL:
        if (chosen())
            kprintf("dialer: call key on a match: not available\n");
        ui_note_ms("Calls are not available yet.\nPress Message to send a text.", 3000);
        return 1;
    }
    return 0;
}

static void key_up(unsigned k)
{
    if (k == KEY_0)
        timer_stop(&plus_timer);
}

static void timer(unsigned id)
{
    /* 0 held: it becomes '+' */
    if (id == TIMER_PLUS && len && number[len - 1] == '0') {
        number[len - 1] = '+';
        changed();
    }
}

const struct screen dialer_screen = {
    .name = "dialer",
    .flags = SCREEN_TITLE,
    .enter = enter,
    .leave = leave,
    .paint = paint,
    .key = key,
    .key_up = key_up,
    .timer = timer,
};

const struct screen calls_screen = {
    .name = "calls",
    .flags = SCREEN_TITLE,
    .enter = enter,
    .leave = leave,
    .paint = paint,
    .key = key,
    .key_up = key_up,
    .timer = timer,
};
