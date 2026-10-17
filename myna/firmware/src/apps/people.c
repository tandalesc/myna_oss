/* SPDX-License-Identifier: MIT */
/* Contacts (menu item 2, and the right soft key on standby), on the contacts service (services/contacts.h).
 *
 * The list: "New contact", then every contact in alphabetical order. Number keys search (apps/search.c): the keys
 * typed show in a field over the list, which shows only the contacts whose name has a word that starts with the
 * keys' letters (2 abc ... 9 wxyz; 5-6-4 finds John), then those whose number holds the digits; C takes the last key
 * back, C held or Back the whole search. Select opens the contact; Options: New contact, Send message, Edit, Delete.
 *
 * A contact: its numbers as a numbered list, each with its label (Mobile, Home, Work, Other), and its note under
 * them. Select (Message) writes to the chosen number; Options: Send message, Call (not yet), Edit, Delete (after a
 * question).
 *
 * New / Edit: a numbered list of the fields (first name, last name, up to four numbers with their labels, "Add
 * number", note); select opens a field in an editor (ui/choice.h): a number in the phone-number box, whose left soft
 * key changes its label; an emptied number is removed. Save keeps the contact (a contact needs a name or a number);
 * Back with changes asks whether to drop them. */
#include <stdint.h>

#include "apps/phone.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "kernel/ostimer.h"
#include "lib/mem.h"
#include "lib/phonenum.h"
#include "lib/print.h"
#include "services/contacts.h"
#include "ui/apps.h"
#include "ui/choice.h"
#include "ui/layout.h"
#include "ui/list.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

#define JUMP_MS   1500         /* the same number key again within this: its next letter */
#define NAME_MAX  40           /* characters of a name or a number in an editor */
#define NOTE_MAX  200

static const struct screen view_screen, edit_screen;

/* ---- shared ---- */

static char lower(char c)
{
    return c >= 'A' && c <= 'Z' ? (char)(c + 32) : c;
}

unsigned people_sorted(uint16_t *order, unsigned max)
{
    return contacts_sorted(order, max);        /* kept by the service, made again at each change */
}

int people_jump(const uint16_t *order, unsigned n, unsigned key)
{
    static const uint8_t keys[8] = { KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9 };
    static const char *const letters[8] = { "abc", "def", "ghi", "jkl", "mno", "pqrs", "tuv", "wxyz" };
    static unsigned last_key, step;
    static ktime_t last_at;
    int k = -1;
    for (int i = 0; i < 8; i++)
        if (keys[i] == key)
            k = i;
    if (k < 0)
        return -1;
    ktime_t now = ktime_now();
    step = key == last_key && now - last_at < KTIME_MS(JUMP_MS) ? step + 1 : 0;
    last_key = key;
    last_at = now;
    char want = letters[k][step % strlen(letters[k])];
    int after = -1;
    for (unsigned i = 0; i < n; i++) {
        uint32_t id;
        const char *name;
        if (contacts_at(order[i], &id, &name))
            continue;
        char c = lower(name[0]);
        if (c == want)
            return (int)i;
        if (c > want && after < 0)
            after = (int)i;
    }
    return after >= 0 ? after : n ? (int)n - 1 : -1;
}

void people_name(const char *number, char *out, unsigned max)
{
    const char *name = contacts_lookup(number);
    if (name)
        text_from_utf8(out, max, name);
    else
        copy_text(out, number, max);
}

static int delete_contact(uint32_t id)
{
    int e = contacts_delete(id);
    kprintf("ui: contact %u deleted: %d\n", id, e);
    ui_note(e ? "Not deleted: storage error" : "Deleted");
    return e;
}

/* ---- the list ---- */

#define FIELD_H    34          /* the search field's band over the list */
#define FOUND_ROWS 7           /* rows under it */

static uint16_t order[CONTACTS_MAX];
static unsigned count;
static struct list book;
static char row_name[48];
static uint8_t book_hint;
static uint32_t book_focus;    /* a new contact, to select when the list shows again */
static struct search found;    /* the search, while keys are typed */
static char query[SEARCH_QUERY_MAX + 1];
static unsigned qlen;
static uint8_t field_dirty, below_dirty;

static int searching(void)
{
    return qlen > 0;
}

static uint32_t id_at(int row)
{
    uint32_t id = 0;
    const char *name;
    if (searching())
        return row >= 0 && row < found.count ? search_id(&found, row) : 0;
    if (row > 0 && (unsigned)row <= count)
        contacts_at(order[row - 1], &id, &name);
    return id;
}

static const char *book_label(int row)
{
    if (row == 0)
        return "New contact";
    uint32_t id;
    const char *name;
    if (contacts_at(order[row - 1], &id, &name))
        return "";
    text_from_utf8(row_name, sizeof row_name, name);
    return row_name;
}

static const char *book_value(int row)
{
    return row ? LIST_CHEVRON : "";
}

/* a row of the search: the name with the matched letters marked, a matched number at the right */
static void draw_found(const struct surface *s, const struct rect *r, int row, int sel, uint16_t bg)
{
    const struct theme *t = theme;
    int pad = layout.list.pad, x = r->x + pad, right = r->x + r->w - pad;
    char name[48], number[VCARD_NUMBER_MAX];
    int from, to, nf = 0, nt = 0;
    search_title(&found, row, name, sizeof name, &from, &to);
    const struct font *fv = sel ? t->value_selected : t->value;
    const char *value = LIST_CHEVRON;
    if (found.hits[row].kind == CONTACTS_HIT_NUMBER && !search_number(&found, row, number, sizeof number, &nf, &nt))
        value = number;
    int vw = gfx_text_width(fv, value);
    search_draw(s, r, fv, right - vw, r->y + (sel ? layout.list.value_base_sel : layout.list.value_base), vw, value,
                nf, nt, ink.value, sel, bg);
    search_draw(s, r, sel ? t->row_selected : t->row, x,
                r->y + (sel ? layout.list.label_base_sel : layout.list.label_base), right - vw - 8 - x, name, from, to,
                ink.text, sel, bg);
}

static void book_soft_keys(void)
{
    if (searching())
        ui_soft_keys("Options", found.count ? "View" : "", "Back");
    else
        ui_soft_keys("Options", book.selected ? "View" : "New", "Back");
}

/* the list of the whole book, or of the search's hits under its field */
static void book_layout(void)
{
    struct rect r = layout.content;
    if (searching()) {
        r.y = (int16_t)(r.y + FIELD_H);
        r.h = (int16_t)(FOUND_ROWS * layout.list.row_h);
        list_init(&book, &r, found.count);
        book.draw = draw_found;
    } else {
        r.h = (int16_t)(layout.list.rows * layout.list.row_h);
        list_init(&book, &r, 1 + (int)count);
        book.draw = 0;
    }
    book.label = book_label;
    book.value = book_value;
    book_hint = 1;
}

static void book_enter(int fresh)
{
    int sel = book.selected;
    count = people_sorted(order, CONTACTS_MAX);
    if (fresh || book_focus)
        qlen = 0;              /* a contact just made shows in the whole book */
    query[qlen] = 0;
    search_begin(&found, 0);
    if (searching())
        search_run(&found, query);
    book_layout();
    if (!fresh)
        list_select(&book, sel < book.count ? sel : book.count - 1);
    else if (count)
        list_select(&book, 1);
    for (unsigned i = 0; book_focus && i < count; i++)
        if (id_at((int)i + 1) == book_focus)
            list_select(&book, (int)i + 1);    /* a contact just made: where it went */
    book_focus = 0;
    field_dirty = 1;
    ui_title("Contacts");
    book_soft_keys();
}

/* the search's keys changed: its hits, or the whole book again with the contact that was chosen (id) */
static void book_search_changed(uint32_t id)
{
    int was = book.draw != 0;
    query[qlen] = 0;
    if (searching())
        search_run(&found, query);
    else
        kprintf("contacts: search cleared\n");
    book_layout();
    if (searching()) {
        below_dirty = !was;    /* the whole book's last rows are below the search's */
    } else {
        for (unsigned i = 0; id && i < count; i++)
            if (id_at((int)i + 1) == id)
                list_select(&book, (int)i + 1);
        if (!book.selected && count)
            list_select(&book, 1);
    }
    field_dirty = 1;
    book_soft_keys();
}

/* the search's field: a glass, the keys typed, how many contacts match */
static void paint_field(const struct surface *fb)
{
    const struct theme *t = theme;
    struct rect area = { 0, layout.content.y, DISPLAY_W, FIELD_H };
    ui_backdrop(fb, &area);
    struct rect box = { layout.convo.blocks.x, (int16_t)(area.y + 4), layout.convo.blocks.w, 26 };
    gfx_round_rect(fb, &area, &box, t->field_radius, ink.surface, ink.rule);
    int gx = box.x + 10, gy = box.y + 7;
    struct rect ring = { (int16_t)gx, (int16_t)gy, 10, 10 };
    gfx_round_rect(fb, &box, &ring, 5, ink.surface, ink.muted);
    for (int i = 0; i < 3; i++) {
        struct rect h = { (int16_t)(gx + 8 + i), (int16_t)(gy + 8 + i), 2, 2 };
        gfx_fill(fb, &h, ink.muted);
    }
    int base = box.y + 18;
    char n[24];
    if (found.total) {
        int k = format_uint(n, found.total);
        copy_text(n + k, found.total == 1 ? " match" : " matches", sizeof n - (unsigned)k);
    } else {
        copy_text(n, "No match", sizeof n);
    }
    int nx = box.x + box.w - 10 - gfx_text_width(t->value, n);
    gfx_text(fb, &box, t->value, nx, base, n, ink.muted, ink.surface);
    const char *keys = query;  /* the last keys of a search too long for the field */
    while (keys[1] && gfx_text_width(t->row_selected, keys) > nx - 8 - (gx + 20))
        keys++;
    gfx_text(fb, &box, t->row_selected, gx + 20, base, keys, ink.text, ink.surface);
    display_invalidate(&area);
}

static void book_paint(const struct surface *fb)
{
    if (searching() && field_dirty)
        paint_field(fb);
    field_dirty = 0;
    if (below_dirty) {
        below_dirty = 0;
        int top = book.r.y + book.r.h;
        struct rect r = { 0, (int16_t)top, DISPLAY_W, (int16_t)(layout.content.y + layout.content.h - top) };
        ui_backdrop(fb, &r);
        display_invalidate(&r);
    }
    list_paint(&book, fb);
    if (book_hint) {
        book_hint = 0;
        const char *hint = searching() ? (found.count ? 0 : "No contact matches") : count ? 0 : "No contacts yet";
        if (hint) {
            const struct font *f = theme->body;
            struct rect area = { 0, (int16_t)(book.r.y + 2 * layout.list.row_h), DISPLAY_W, 80 };
            gfx_text_over(fb, &area, f, (DISPLAY_W - gfx_text_width(f, hint)) / 2, area.y + 40, hint, ink.muted);
            display_invalidate(&area);
        }
    }
}

static uint32_t asked_id;

static void book_delete_answer(unsigned key)
{
    if (key == KEY_SELECT)
        delete_contact(asked_id);
    ui_redraw();
}

static const struct dialog book_delete_dialog = {
    .text = "Delete this contact?", .centre = "Delete", .right = "Keep", .answer = book_delete_answer,
};

static void new_contact(void);
static void edit_contact(uint32_t id);
static void message_contact(uint32_t id);

enum { BO_NEW, BO_MESSAGE, BO_EDIT, BO_DELETE };
static uint8_t book_map[4];

static int book_option(int row)
{
    uint32_t id = id_at(book.selected);
    switch (book_map[row]) {
    case BO_NEW:
        new_contact();
        return 1;
    case BO_MESSAGE:
        message_contact(id);
        return 1;
    case BO_EDIT:
        edit_contact(id);
        return 1;
    case BO_DELETE:
        asked_id = id;
        ui_pop();
        ui_dialog(&book_delete_dialog);
        return 1;
    }
    return 0;
}

static void book_options(void)
{
    struct choice c = { .title = "Options", .chosen = book_option };
    book_map[c.count] = BO_NEW;
    c.rows[c.count++] = (struct choice_row){ .label = "New contact" };
    if (id_at(book.selected)) {
        book_map[c.count] = BO_MESSAGE;
        c.rows[c.count++] = (struct choice_row){ .label = "Send message" };
        book_map[c.count] = BO_EDIT;
        c.rows[c.count++] = (struct choice_row){ .label = "Edit" };
        book_map[c.count] = BO_DELETE;
        c.rows[c.count++] = (struct choice_row){ .label = "Delete" };
    }
    choice_open(&c);
}

static int book_key(unsigned k)
{
    static const uint8_t digit_keys[10] = { KEY_0, KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9 };
    switch (list_key(&book, k)) {
    case LIST_CHOSEN:
        if (!searching() && book.selected == 0)
            new_contact();
        else
            contacts_view(id_at(book.selected));
        return 1;
    case LIST_USED:
        book_soft_keys();
        return 1;
    }
    uint32_t id = id_at(book.selected);
    for (int i = 0; i < 10; i++)
        if (k == digit_keys[i]) {
            if (qlen < SEARCH_QUERY_MAX) {
                query[qlen++] = (char)('0' + i);
                book_search_changed(id);
            }
            return 1;
        }
    if (searching() && (k == KEY_CLEAR || k == (KEY_HELD | KEY_CLEAR) || k == KEY_SOFT_RIGHT)) {
        qlen = k == KEY_CLEAR ? qlen - 1 : 0;      /* C: the last key; C held or Back: all of them */
        book_search_changed(id);
        return 1;
    }
    switch (k) {
    case KEY_SOFT_LEFT:
        book_options();
        return 1;
    case KEY_SOFT_RIGHT:
        ui_pop();
        return 1;
    }
    return 0;
}

const struct screen contacts_screen = {
    .name = "contacts",
    .flags = SCREEN_TITLE,
    .enter = book_enter,
    .paint = book_paint,
    .key = book_key,
};

/* ---- one contact ---- */

static uint32_t view_id;
static struct vcard_contact card;
static struct list numbers;
static char view_title[48];
static char view_number[VCARD_NUMBER_MAX];
static uint8_t note_dirty;

static const char *number_label(int row)
{
    text_from_utf8(view_number, sizeof view_number, card.numbers[row].number);
    return view_number;
}

static const char *number_value(int row)
{
    return vcard_label_name(card.numbers[row].label);
}

static void view_enter(int fresh)
{
    int sel = numbers.selected;
    if (contacts_get(view_id, &card)) {
        memset(&card, 0, sizeof card);
        copy_text(card.given, "?", sizeof card.given);
    }
    char name[64];
    vcard_display_name(&card, name, sizeof name);
    text_from_utf8(view_title, sizeof view_title, name);
    struct rect r = layout.content;
    r.h = (int16_t)(VCARD_NUMBERS * layout.list.row_h);
    list_init(&numbers, &r, card.count);
    numbers.numbered = 1;
    numbers.label = number_label;
    numbers.value = number_value;
    if (!fresh && sel < card.count)
        list_select(&numbers, sel);
    note_dirty = 1;
    ui_title(view_title);
    ui_soft_keys("Options", card.count ? "Message" : "", "Back");
}

/* the note (or "No numbers") under the numbers, in a block like a message's */
static void paint_note(const struct surface *fb)
{
    const struct theme *t = theme;
    int top = layout.content.y + card.count * layout.list.row_h;
    struct rect area = { 0, (int16_t)top, DISPLAY_W, (int16_t)(layout.content.y + layout.content.h - top) };
    ui_backdrop(fb, &area);
    if (!card.count)
        gfx_text_over(fb, &area, t->body, layout.convo.blocks.x + 2, top + 24, "No numbers", ink.muted);
    if (card.note[0]) {
        static char note[VCARD_NOTE_MAX];
        text_from_utf8(note, sizeof note, card.note);
        int pad = layout.convo.pad_x, w = layout.convo.blocks.w;
        uint16_t starts[8];
        int lines = text_wrap(t->body, note, (int)strlen(note), w - 2 - 2 * pad, starts, 8);
        struct rect b = { layout.convo.blocks.x, (int16_t)(top + (card.count ? 12 : 36)), (int16_t)w,
                          (int16_t)(2 + layout.convo.pad_top + layout.convo.head_h + lines * layout.convo.line_h +
                                    layout.convo.pad_bottom) };
        gfx_round_rect(fb, &area, &b, t->block_radius, ink.surface, ink.rule);
        int x = b.x + 1 + pad, y = b.y + 16;
        gfx_text_over(fb, &area, t->meta, x, y, "Note", ink.muted);
        y += 15;
        int len = (int)strlen(note);
        for (int i = 0; i < lines; i++, y += layout.convo.line_h) {
            int a = starts[i], e = i + 1 < lines ? starts[i + 1] : len;
            while (e > a && (note[e - 1] == ' ' || note[e - 1] == '\n'))
                e--;
            text_draw_n(fb, &area, t->body, x, y, note + a, e - a, ink.text);
        }
    }
    display_invalidate(&area);
}

static void view_paint(const struct surface *fb)
{
    list_paint(&numbers, fb);
    if (note_dirty) {
        note_dirty = 0;
        paint_note(fb);
    }
}

static void view_delete_answer(unsigned key)
{
    if (key != KEY_SELECT)
        return;
    if (!delete_contact(view_id))
        ui_pop();
}

static char delete_question[64];
static const struct dialog view_delete_dialog = {
    .text = delete_question, .centre = "Delete", .right = "Keep", .answer = view_delete_answer,
};

enum { VO_MESSAGE, VO_CALL, VO_EDIT, VO_DELETE };
static uint8_t view_map[4];

static int view_option(int row)
{
    switch (view_map[row]) {
    case VO_MESSAGE:
        ui_pop();
        messages_open(card.numbers[numbers.selected].number);
        return 1;
    case VO_EDIT:
        edit_contact(view_id);
        return 1;
    case VO_DELETE: {
        char name[32];
        text_fit(theme->body, view_title, 150, name, sizeof name);
        copy_text(delete_question, "Delete ", sizeof delete_question);
        copy_text(delete_question + 7, name, sizeof delete_question - 7);
        unsigned n = (unsigned)strlen(delete_question);
        copy_text(delete_question + n, "?", sizeof delete_question - n);
        ui_pop();
        ui_dialog(&view_delete_dialog);
        return 1;
    }
    }
    return 0;
}

static void view_options(void)
{
    struct choice c = { .title = "Options", .chosen = view_option };
    if (card.count) {
        view_map[c.count] = VO_MESSAGE;
        c.rows[c.count++] = (struct choice_row){ .label = "Send message" };
        view_map[c.count] = VO_CALL;
        c.rows[c.count++] = (struct choice_row){ .label = "Call", .why = "Calls are not available yet" };
    }
    view_map[c.count] = VO_EDIT;
    c.rows[c.count++] = (struct choice_row){ .label = "Edit" };
    view_map[c.count] = VO_DELETE;
    c.rows[c.count++] = (struct choice_row){ .label = "Delete" };
    choice_open(&c);
}

static int view_key(unsigned k)
{
    switch (list_key(&numbers, k)) {
    case LIST_CHOSEN:
        messages_open(card.numbers[numbers.selected].number);
        return 1;
    case LIST_USED:
        return 1;
    }
    switch (k) {
    case KEY_SOFT_LEFT:
        view_options();
        return 1;
    case KEY_SOFT_RIGHT:
        ui_pop();
        return 1;
    case KEY_CALL:
        ui_note("Calls are not available yet");
        return 1;
    }
    return 0;
}

static const struct screen view_screen = {
    .name = "contact",
    .flags = SCREEN_TITLE,
    .enter = view_enter,
    .paint = view_paint,
    .key = view_key,
};

void contacts_view(uint32_t id)
{
    if (!id)
        return;
    view_id = id;
    ui_open(&view_screen);
}

int contacts_show_number(const char *number)
{
    uint32_t id = contacts_lookup_id(number);
    if (!id)
        return 0;
    contacts_view(id);
    return 1;
}

static void message_contact(uint32_t id)
{
    struct vcard_contact c;
    if (contacts_get(id, &c) || !c.count) {
        ui_note("No number to write to");
        return;
    }
    ui_pop();                  /* the options */
    messages_open(c.numbers[0].number);
}

/* ---- new and edit ---- */

static struct vcard_contact draft;
static uint32_t draft_id;
static uint8_t draft_changed;
static struct list fields;
static char field_values[VCARD_NUMBERS + 4][48];
static int edit_slot;          /* the number being edited (draft.count: a new one) */
static uint8_t edit_label;

enum { F_GIVEN, F_FAMILY, F_NUMBER, F_ADD, F_NOTE };

static int field_of(int row, int *slot)
{
    if (row == 0)
        return F_GIVEN;
    if (row == 1)
        return F_FAMILY;
    row -= 2;
    if (row < draft.count) {
        *slot = row;
        return F_NUMBER;
    }
    row -= draft.count;
    if (draft.count < VCARD_NUMBERS) {
        if (row == 0)
            return F_ADD;
        row--;
    }
    return F_NOTE;
}

static int field_rows(void)
{
    return 2 + draft.count + (draft.count < VCARD_NUMBERS) + 1;
}

static const char *field_label(int row)
{
    int slot = 0;
    switch (field_of(row, &slot)) {
    case F_GIVEN:
        return "First name";
    case F_FAMILY:
        return "Last name";
    case F_NUMBER:
        return vcard_label_name(draft.numbers[slot].label);
    case F_ADD:
        return "Add number";
    }
    return "Note";
}

static const char *field_value(int row)
{
    int slot = 0;
    const char *v = "";
    switch (field_of(row, &slot)) {
    case F_GIVEN:
        v = draft.given;
        break;
    case F_FAMILY:
        v = draft.family;
        break;
    case F_NUMBER:
        v = draft.numbers[slot].number;
        break;
    case F_ADD:
        return LIST_CHEVRON;
    case F_NOTE:
        v = draft.note;
        break;
    }
    char t[64];
    text_from_utf8(t, sizeof t, v);
    text_fit(theme->value, t, 130, field_values[row], sizeof field_values[row]);
    return field_values[row];
}

static void edit_enter(int fresh)
{
    int sel = fields.selected;
    struct rect r = layout.content;
    r.h = (int16_t)(layout.list.rows * layout.list.row_h);
    list_init(&fields, &r, field_rows());
    fields.numbered = 1;
    fields.label = field_label;
    fields.value = field_value;
    if (!fresh)
        list_select(&fields, sel < fields.count ? sel : fields.count - 1);
    ui_title(draft_id ? "Edit contact" : "New contact");
    ui_soft_keys("Save", "Edit", "Back");
}

static void edit_paint(const struct surface *fb)
{
    list_paint(&fields, fb);
}

static int save_given(const char *text)
{
    text_to_utf8(draft.given, sizeof draft.given, text);
    draft_changed = 1;
    return 0;
}

static int save_family(const char *text)
{
    text_to_utf8(draft.family, sizeof draft.family, text);
    draft_changed = 1;
    return 0;
}

static int save_note(const char *text)
{
    text_to_utf8(draft.note, sizeof draft.note, text);
    draft_changed = 1;
    return 0;
}

static int save_number(const char *text)
{
    char n[VCARD_NUMBER_MAX];
    if (!text[0]) {
        if (edit_slot < draft.count) {     /* emptied: the number goes */
            for (int i = edit_slot; i + 1 < draft.count; i++)
                draft.numbers[i] = draft.numbers[i + 1];
            draft.count--;
            draft_changed = 1;
        }
        return 0;
    }
    if (phonenum_normalize(text, n, sizeof n) < 0) {
        ui_note("Not a phone number");
        return 1;
    }
    copy_text(draft.numbers[edit_slot].number, n, sizeof n);
    draft.numbers[edit_slot].label = edit_label;
    if (edit_slot == draft.count)
        draft.count++;
    draft_changed = 1;
    return 0;
}

static char number_title[32];

static void number_title_set(void)
{
    copy_text(number_title, vcard_label_name(edit_label), sizeof number_title);
    unsigned n = (unsigned)strlen(number_title);
    copy_text(number_title + n, " number", sizeof number_title - n);
}

static void next_label(void)
{
    edit_label = (uint8_t)((edit_label + 1) % VCARD_LABELS);
    number_title_set();
    editor_title(number_title);
}

static void edit_number(int slot)
{
    static char text[VCARD_NUMBER_MAX];
    edit_slot = slot;
    if (slot < draft.count) {
        edit_label = draft.numbers[slot].label;
        text_from_utf8(text, sizeof text, draft.numbers[slot].number);
    } else {
        /* a new number: the first label not in use */
        edit_label = VCARD_MOBILE;
        for (int l = 0; l < VCARD_LABELS; l++) {
            int used = 0;
            for (int i = 0; i < draft.count; i++)
                used |= draft.numbers[i].label == l;
            if (!used) {
                edit_label = (uint8_t)l;
                break;
            }
        }
        text[0] = 0;
    }
    number_title_set();
    struct editor e = { .title = number_title, .text = text, .placeholder = "Number", .help = "Label: left soft key",
                        .max = 24, .phone = 1, .left = "Label", .left_key = next_label, .save = save_number };
    editor_open(&e);
}

static void edit_field(int row)
{
    static char text[NOTE_MAX + 1];
    int slot = 0;
    struct editor e = { .max = NAME_MAX, .text = text, .abc = 1 };
    switch (field_of(row, &slot)) {
    case F_GIVEN:
        text_from_utf8(text, sizeof text, draft.given);
        e.title = "First name";
        e.save = save_given;
        break;
    case F_FAMILY:
        text_from_utf8(text, sizeof text, draft.family);
        e.title = "Last name";
        e.save = save_family;
        break;
    case F_NUMBER:
        edit_number(slot);
        return;
    case F_ADD:
        edit_number(draft.count);
        return;
    case F_NOTE:
        text_from_utf8(text, sizeof text, draft.note);
        e.title = "Note";
        e.max = NOTE_MAX;
        e.abc = 0;             /* sentences: predictive text, as the setting says */
        e.save = save_note;
        break;
    }
    editor_open(&e);
}

static void save_contact(void)
{
    if (!draft.given[0] && !draft.family[0] && !draft.count) {
        ui_note("Add a name or a number");
        return;
    }
    int32_t r = draft_id ? contacts_update(draft_id, &draft) : contacts_add(&draft);
    kprintf("ui: contact %u saved: %d (\"%s\" \"%s\", %u numbers, note \"%s\")\n", draft_id, r, draft.given,
            draft.family, draft.count, draft.note);
    if (r < 0) {
        ui_note(r == -3 ? "Not saved: the memory is full" : "Not saved: storage error");
        return;
    }
    if (draft_id) {
        ui_pop();
    } else {
        view_id = book_focus = (uint32_t)r;
        ui_replace(&view_screen);
    }
    ui_note("Saved");
}

static void discard_answer(unsigned key)
{
    if (key == KEY_SELECT)
        ui_pop();
}

static const struct dialog discard_dialog = {
    .text = "Drop the changes?", .centre = "Drop", .right = "Keep", .answer = discard_answer,
};

static int edit_key(unsigned k)
{
    switch (list_key(&fields, k)) {
    case LIST_CHOSEN:
        edit_field(fields.selected);
        return 1;
    case LIST_USED:
        return 1;
    }
    switch (k) {
    case KEY_SOFT_LEFT:
        save_contact();
        return 1;
    case KEY_SOFT_RIGHT:
    case KEY_CLEAR:
        if (draft_changed)
            ui_dialog(&discard_dialog);
        else
            ui_pop();
        return 1;
    }
    return 0;
}

static const struct screen edit_screen = {
    .name = "contact edit",
    .flags = SCREEN_TITLE,
    .enter = edit_enter,
    .paint = edit_paint,
    .key = edit_key,
};

static void new_contact(void)
{
    memset(&draft, 0, sizeof draft);
    draft_id = 0;
    draft_changed = 0;
    ui_open(&edit_screen);
}

static void edit_contact(uint32_t id)
{
    if (!id || contacts_get(id, &draft)) {
        ui_note("Not found");
        return;
    }
    draft_id = id;
    draft_changed = 0;
    ui_open(&edit_screen);
}

void contacts_new_with_number(const char *number)
{
    memset(&draft, 0, sizeof draft);
    if (phonenum_normalize(number, draft.numbers[0].number, sizeof draft.numbers[0].number) >= 0) {
        draft.numbers[0].label = VCARD_MOBILE;
        draft.count = 1;
    }
    draft_id = 0;
    draft_changed = 1;
    ui_open(&edit_screen);
}
