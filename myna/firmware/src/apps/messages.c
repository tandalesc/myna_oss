/* SPDX-License-Identifier: MIT */
/* Messages (menu item 1, and the left soft key on standby): text messages as conversations, in the design's
 * conversation layout (STYLE.md section 2: full-width message blocks over a "Write a message" box).
 *
 * The list: "New message", then one two-line row per number, newest first: the contact's name or the number, the
 * time of the last message, a line of it (with "Sending" or "Not sent" in front while that is its state) and the
 * count of unread ones on an accent mark. Select opens; Options: New message, Delete conversation, Mark all read.
 * A conversation with an unsent draft shows the draft's line instead ("Draft:" in front), and counts as new as the
 * draft when that is newer; a draft to a number with no messages yet is a row of its own.
 *
 * A conversation: the messages as blocks, the newest at the bottom, each with its state at the right of its header
 * (Sending..., Waiting for network, Sent, Delivered, Failed) and, for a failure, the reason under its text. The box
 * under them takes the text (multi-tap; its count shows the parts: "Abc 12/160", "Abc 2 parts 40/153"); Send is the
 * centre soft key. Up / down scroll through the blocks (ui/convo.h); Options act on the lowest block in view: Retry
 * (a failed one), Delete message, Delete conversation, Call (not yet: calls are out of scope), Add to contacts or
 * View contact. Opening a conversation marks its messages read. Retry sends a failed text again from the first part the
 * network did not take (sms_retry). Text left in the box when the conversation closes (Back, END, power off) is kept
 * as the number's draft (sms/store.h) and is in the box again when the conversation opens; sending it, or emptying
 * the box, deletes it.
 *
 * New message: a picker of the recipient: "Enter number" (an editor for a phone number), then the contacts that
 * have a number, alphabetical, with the number keys jumping to letters as in Contacts.
 *
 * The data are the message store's (sms/store.h): the records are in RAM, so the list costs no flash read but the
 * lines of the last messages (read once, kept in a small cache); a conversation reads the texts of its newest
 * messages once, as many as POOL holds, and afterwards only the new ones. Received messages elsewhere show a toast
 * with the sender and the first words, the envelope and the standby line (apps/phone.c, ui/home.c). */
#include <stdint.h>

#include "apps/phone.h"
#include "assets.h"
#include "drivers/clock.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "kernel/task.h"
#include "kernel/timer.h"
#include "lib/mem.h"
#include "lib/phonenum.h"
#include "lib/print.h"
#include "lib/sms_pdu.h"
#include "services/contacts.h"
#include "services/network.h"
#include "sms/sms.h"
#include "sms/store.h"
#include "ui/apps.h"
#include "ui/choice.h"
#include "ui/convo.h"
#include "ui/layout.h"
#include "ui/list.h"
#include "ui/textentry.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

#define CONVS      64          /* conversations in the list */
#define PREVIEWS   8           /* lines of last messages kept */
#define POOL       8192        /* the texts of the open conversation (UTF-8) */
#define BOX_LINES  4           /* the box grows to this many lines */
#define TOAST_MS   3000
#define TIMER_TAP  (UI_TIMER_SCREEN + 0)

static const struct screen convo_screen, to_screen;

static char utf_buf[SMS_TEXT_MAX + 1];     /* one message's text as the store keeps it */

/* ---- the conversations ---- */

struct conv {
    uint32_t key;              /* phonenum_key() of the number */
    uint32_t last;             /* the newest message's id; 0: only a draft */
    uint32_t time;             /* the newest of the last message and the draft: the list's order */
    uint16_t count, unread;
    uint8_t draft;             /* an unsent draft (store_draft_find) */
};

static struct conv convs[CONVS];
static int nconv;
static struct list conv_list;

static struct {
    uint32_t id;
    char text[48];
} previews[PREVIEWS];
static unsigned preview_next;

static void build_convs(void)
{
    unsigned n = 0;
    const struct store_entry *e = store_ready() ? store_index(&n) : 0;
    nconv = 0;
    for (unsigned i = n; i-- > 0;) {
        int k = 0;
        while (k < nconv && convs[k].key != e[i].key)
            k++;
        if (k == nconv) {
            if (nconv == CONVS)
                continue;
            convs[nconv++] = (struct conv){ .key = e[i].key, .last = e[i].id, .time = e[i].time };
        }
        convs[k].count++;
        if (e[i].state == SMS_RECEIVED)
            convs[k].unread++;
    }
    /* drafts: on their conversation's row, or a row of their own; a newer draft moves its row up */
    unsigned nd = 0;
    const struct store_draft *d = store_ready() ? store_drafts(&nd) : 0;
    for (unsigned j = 0; j < nd; j++) {
        int k = 0;
        while (k < nconv && convs[k].key != d[j].key)
            k++;
        if (k == nconv) {
            if (nconv == CONVS)
                continue;
            convs[nconv++] = (struct conv){ .key = d[j].key };
        }
        convs[k].draft = 1;
        if (d[j].time > convs[k].time)
            convs[k].time = d[j].time;
    }
    if (!nd)
        return;
    for (int i = 1; i < nconv; i++) {          /* stable: equal times keep the messages' order */
        struct conv c = convs[i];
        int k = i;
        while (k > 0 && convs[k - 1].time < c.time) {
            convs[k] = convs[k - 1];
            k--;
        }
        convs[k] = c;
    }
}

/* the first line of a message's text, as the fonts draw it, from the cache or the store */
static const char *preview_of(uint32_t id)
{
    for (unsigned i = 0; i < PREVIEWS; i++)
        if (previews[i].id == id)
            return previews[i].text;
    unsigned slot = preview_next++ % PREVIEWS;
    previews[slot].id = id;
    previews[slot].text[0] = 0;
    struct sms_record r;
    if (store_read(id, &r, utf_buf, sizeof utf_buf) >= 0) {
        char line[64];
        text_from_utf8(line, sizeof line, utf_buf);
        copy_text(previews[slot].text, line, sizeof previews[slot].text);
    }
    return previews[slot].text;
}

static void number_of(uint32_t id, char *out, unsigned max)
{
    struct sms_record r;
    if (store_read(id, &r, 0, 0) < 0)
        r.number[0] = 0;
    copy_text(out, r.number, max);
}

/* the number of a conversation: its newest message's, or its draft's */
static void conv_number_of(const struct conv *c, char *out, unsigned max)
{
    if (c->last) {
        number_of(c->last, out, max);
        return;
    }
    const struct store_draft *d = store_draft_find(c->key);
    copy_text(out, d ? d->number : "", max);
}

/* text on a row: over the selection bar, or on the background's colour */
static void row_text(const struct surface *s, const struct rect *r, const struct font *f, int x, int y,
                     const char *t, uint16_t fg, int sel, uint16_t bg)
{
    if (sel)
        gfx_text_over(s, r, f, x, y, t, ink.on_accent);
    else
        gfx_text(s, r, f, x, y, t, fg, bg);
}

static void draw_conv_row(const struct surface *s, const struct rect *r, int row, int sel, uint16_t bg)
{
    const struct theme *t = theme;
    int pad = layout.list.pad, right = r->x + r->w - pad;
    if (row == 0) {
        const struct image *icon = &icon_images[ICON_24][ICON_MESSAGES];
        image_draw(s, r, icon, r->x + pad, r->y + (r->h - icon->h) / 2, 0);
        row_text(s, r, sel ? t->row_selected : t->row, r->x + pad + icon->w + 10, r->y + 25, "New message", ink.text,
                 sel, bg);
        return;
    }
    const struct conv *c = &convs[row - 1];
    const struct store_entry *e = c->last ? store_find(c->last) : 0;
    char number[SMS_NUMBER_MAX], name[48], when[16], line[64];
    conv_number_of(c, number, sizeof number);
    people_name(number, name, sizeof name);
    format_when(when, c->time);

    /* line 1: the name, the time at the right */
    const struct font *ft = sel ? t->value_selected : t->value;
    int tw = gfx_text_width(ft, when);
    row_text(s, r, ft, right - tw, r->y + 17, when, c->unread ? ink.accent : ink.muted, sel, bg);
    const struct font *fn = c->unread || sel ? t->row_selected : t->row;
    text_fit(fn, name, right - tw - 8 - (r->x + pad), line, sizeof line);
    row_text(s, r, fn, r->x + pad, r->y + 17, line, ink.text, sel, bg);

    /* line 2: the unread count on an accent mark at the right, the last message's line before it */
    int x2 = right;
    if (c->unread) {
        char num[8];
        format_uint(num, c->unread);
        int nw = gfx_text_width(t->number_selected, num), mw = nw + 10 < 18 ? 18 : nw + 10;
        struct rect mark = { (int16_t)(right - mw), (int16_t)(r->y + 23), (int16_t)mw, 14 };
        gfx_round_rect(s, r, &mark, 7, sel ? ink.on_accent : ink.accent, GFX_NO_BORDER);
        gfx_text_over(s, &mark, t->number_selected, mark.x + (mw - nw) / 2, mark.y + 11, num,
                      sel ? ink.accent : ink.on_accent);
        x2 = right - mw - 8;
    }
    int x = r->x + pad;
    const char *lead = 0, *text;
    uint16_t lc = ink.muted;
    const struct store_draft *d = c->draft ? store_draft_find(c->key) : 0;
    char head[STORE_DRAFT_HEAD];
    if (d) {
        lead = "Draft: ";
        lc = ink.accent;
        text_from_utf8(head, sizeof head, d->head);
        text = head;
    } else {
        if (e && e->dir == SMS_OUT) {
            lead = e->state == SMS_QUEUED ? "Sending: " : e->state == SMS_FAILED ? "Not sent: " : "Me: ";
            if (e->state == SMS_FAILED || e->state == SMS_QUEUED)
                lc = ink.accent;
        }
        text = preview_of(c->last);
    }
    if (lead) {
        row_text(s, r, t->value_selected, x, r->y + 34, lead, lc, sel, bg);
        x += gfx_text_width(t->value_selected, lead);
    }
    text_fit(t->value, text, x2 - x, line, sizeof line);
    row_text(s, r, t->value, x, r->y + 34, line, ink.muted, sel, bg);
}

static const char *no_label(int row)
{
    (void)row;
    return "";
}

static uint8_t hint_dirty;

static void inbox_soft_keys(void)
{
    ui_soft_keys("Options", conv_list.selected ? "Open" : "Write", "Back");
}

static void refresh_list(void)
{
    build_convs();
    conv_list.count = (int16_t)(1 + nconv);
    if (conv_list.selected >= conv_list.count)
        conv_list.selected = (int16_t)(conv_list.count - 1);
    if (conv_list.top > conv_list.selected)
        conv_list.top = conv_list.selected;
    list_touch(&conv_list);
    hint_dirty = 1;
}

static void inbox_enter(int fresh)
{
    int sel = conv_list.selected;
    build_convs();
    struct rect r = layout.content;
    r.h = (int16_t)(r.h / LIST_TALL_H * LIST_TALL_H);
    list_init(&conv_list, &r, 1 + nconv);
    conv_list.row_h = LIST_TALL_H;
    conv_list.label = no_label;
    conv_list.draw = draw_conv_row;
    if (!fresh)
        list_select(&conv_list, sel < conv_list.count ? sel : conv_list.count - 1);
    else
        for (int i = 0; i < nconv; i++)
            if (convs[i].unread) {
                list_select(&conv_list, 1 + i);    /* something new: the newest conversation with it (a newer
                                                      draft may be above it) */
                break;
            }
    hint_dirty = 1;
    ui_title("Messages");
    inbox_soft_keys();
}

static void inbox_paint(const struct surface *fb)
{
    list_paint(&conv_list, fb);
    if (hint_dirty) {
        hint_dirty = 0;
        if (!nconv) {
            const struct font *f = theme->body;
            const char *hint = "No messages yet";
            struct rect area = { 0, (int16_t)(layout.content.y + LIST_TALL_H), DISPLAY_W,
                                 (int16_t)(layout.content.h - LIST_TALL_H) };
            gfx_text_over(fb, &area, f, (DISPLAY_W - gfx_text_width(f, hint)) / 2, area.y + 60, hint, ink.muted);
            display_invalidate(&area);
        }
    }
}

static void open_conv(int i);
static void pick_recipient(void);
static void delete_conversation(uint32_t key);

static uint32_t list_key_to_delete;

static void list_delete_answer(unsigned key)
{
    if (key != KEY_SELECT)
        return;
    delete_conversation(list_key_to_delete);
    refresh_list();
    ui_note("Deleted");
}

static const struct dialog list_delete_dialog = {
    .text = "Delete this conversation?", .centre = "Delete", .right = "Keep", .answer = list_delete_answer,
};

static void mark_all_read(void)
{
    unsigned n;
    const struct store_entry *e = store_index(&n);
    for (unsigned i = 0; i < n; i++)
        if (e[i].state == SMS_RECEIVED) {
            sms_mark_read(e[i].id);
            e = store_index(&n);   /* the index may have moved */
        }
}

enum { LO_NEW, LO_DELETE, LO_READ };
static uint8_t list_options_map[3];

static int list_option(int row)
{
    switch (list_options_map[row]) {
    case LO_NEW:
        pick_recipient();
        return 1;
    case LO_DELETE:
        list_key_to_delete = convs[conv_list.selected - 1].key;
        ui_pop();
        ui_dialog(&list_delete_dialog);
        return 1;
    case LO_READ:
        mark_all_read();
        return 0;
    }
    return 0;
}

static void list_options(void)
{
    struct choice c = { .title = "Options", .chosen = list_option };
    list_options_map[c.count] = LO_NEW;
    c.rows[c.count++] = (struct choice_row){ .label = "New message" };
    if (conv_list.selected > 0) {
        list_options_map[c.count] = LO_DELETE;
        c.rows[c.count++] = (struct choice_row){ .label = "Delete conversation" };
    }
    if (store_unread()) {
        list_options_map[c.count] = LO_READ;
        c.rows[c.count++] = (struct choice_row){ .label = "Mark all as read" };
    }
    choice_open(&c);
}

static int inbox_key(unsigned k)
{
    int r = list_key(&conv_list, k);
    if (r == LIST_CHOSEN || k == KEY_SELECT) {
        if (conv_list.selected == 0)
            pick_recipient();
        else
            open_conv(conv_list.selected - 1);
        return 1;
    }
    if (r == LIST_USED) {
        inbox_soft_keys();
        return 1;
    }
    switch (k) {
    case KEY_SOFT_LEFT:
        list_options();
        return 1;
    case KEY_SOFT_RIGHT:
        ui_pop();
        return 1;
    }
    return 0;
}

const struct screen messages_screen = {
    .name = "messages",
    .flags = SCREEN_TITLE,
    .enter = inbox_enter,
    .paint = inbox_paint,
    .key = inbox_key,
};

/* ---- one conversation ---- */

static char conv_number[SMS_NUMBER_MAX];
static uint32_t conv_key;
static char conv_title[48];                /* the contact's name or the number */
static char conv_who[20];                  /* the other side in the blocks' headers: the first name, or the number */

static struct convo blocks;
static struct text_entry box;
static struct timer tap_timer;
static int box_lines;
static uint8_t hint;

/* the draft: the conversation the box belongs to (set when it opens, so that a jump to another number keeps the
   text under the right one), and the text last kept, so that an unchanged box writes nothing */
static char draft_number[SMS_NUMBER_MAX];
static char draft_kept[TEXT_MAX + 1];

static struct convo_msg msgs[CONVO_MAX];
static uint32_t ids[CONVO_MAX];
static char times[CONVO_MAX][16];
static char notes[CONVO_MAX][48];
static int nmsgs;
static char pool[POOL];
static unsigned pool_used;

/* the header, state and note of message i from its record (RAM: no flash read) */
static void describe(int i)
{
    struct sms_record r;
    if (store_read(ids[i], &r, 0, 0) < 0)
        return;
    struct convo_msg *m = &msgs[i];
    m->out = r.dir == SMS_OUT;
    m->who = m->out ? "Me" : conv_who;
    format_day_time(times[i], r.time);
    m->time = times[i];
    m->state = 0;
    m->note = 0;
    m->alert = 0;
    if (!m->out)
        return;
    switch (r.state) {
    case SMS_QUEUED:
        if (!network_registered()) {
            m->state = "Waiting for network";
        } else if (r.attempts) {
            m->state = "Trying again";
        } else if (r.parts > 1 && r.parts_done) {
            /* a retry that goes on from a later part: "Sending part 2 of 3" */
            static char sending[CONVO_MAX][24];
            char *p = sending[i];
            copy_text(p, "Sending part ", sizeof sending[i]);
            int n = 13;
            n += format_uint(p + n, r.parts_done + 1u);
            copy_text(p + n, " of ", sizeof sending[i] - (unsigned)n);
            n += 4;
            format_uint(p + n, r.parts);
            m->state = p;
        } else {
            m->state = "Sending" TEXT_ELLIPSIS;
        }
        break;
    case SMS_SENT:
        m->state = "Sent";
        break;
    case SMS_DELIVERED:
        m->state = "Delivered";
        break;
    case SMS_FAILED: {
        m->state = "Failed";
        m->alert = 1;
        char why[64];
        int n = 0;
        if (r.parts > 1 && r.parts_done) {
            /* the network took the first parts: say which one it refused ("Part 2 of 3 not sent: ...") */
            copy_text(why, "Part ", sizeof why);
            n = 5;
            n += format_uint(why + n, r.parts_done + 1u);
            copy_text(why + n, " of ", sizeof why - (unsigned)n);
            n += 4;
            n += format_uint(why + n, r.parts);
            copy_text(why + n, " not sent: ", sizeof why - (unsigned)n);
            n += 11;
        } else {
            copy_text(why, "Not sent: ", sizeof why);
            n = 10;
        }
        copy_text(why + n, sms_cause_text(r.cause), sizeof why - (unsigned)n);
        text_fit(theme->meta, why, layout.convo.blocks.w - 2 - 2 * layout.convo.pad_x, notes[i], sizeof notes[i]);
        m->note = notes[i];
        break;
    }
    }
}

/* the text of message `id` into the pool; 0 when it does not fit */
static const char *pool_add(uint32_t id, int must)
{
    struct sms_record r;
    if (store_read(id, &r, utf_buf, sizeof utf_buf) < 0)
        utf_buf[0] = 0;
    unsigned room = POOL - pool_used;
    char *dst = pool + pool_used;
    unsigned len = text_from_utf8(dst, room, utf_buf);
    if (len + 1 >= room && !must && len < strlen(utf_buf))
        return 0;              /* cut: leave it (and every older one) out */
    pool_used += len + 1;
    return dst;
}

/* the newest messages of the conversation: as many as CONVO_MAX and the pool hold */
static void load_all(void)
{
    unsigned n;
    const struct store_entry *e = store_index(&n);
    uint32_t got[CONVO_MAX];
    const char *texts[CONVO_MAX];
    int k = 0;
    pool_used = 0;
    for (unsigned i = n; i-- > 0 && k < CONVO_MAX;) {
        if (e[i].key != conv_key)
            continue;
        const char *t = pool_add(e[i].id, k == 0);
        if (!t)
            break;
        got[k] = e[i].id;
        texts[k++] = t;
    }
    nmsgs = k;
    for (int i = 0; i < k; i++) {
        ids[i] = got[k - 1 - i];
        msgs[i].text = texts[k - 1 - i];
        describe(i);
    }
}

/* the store changed: the new messages are added (their texts read), the rest described again */
static void sync(void)
{
    for (int i = 0; i < nmsgs; i++)
        if (!store_find(ids[i])) {
            load_all();                    /* something was deleted: read again */
            convo_set(&blocks, msgs, nmsgs);
            return;
        }
    unsigned n;
    const struct store_entry *e = store_index(&n);
    uint32_t last = nmsgs ? ids[nmsgs - 1] : 0;
    int added = 0;
    for (unsigned i = 0; i < n; i++) {
        if (e[i].key != conv_key || e[i].id <= last)
            continue;
        const char *t = nmsgs < CONVO_MAX ? pool_add(e[i].id, 0) : 0;
        if (!t) {
            load_all();                    /* no room: the newest again */
            convo_set(&blocks, msgs, nmsgs);
            return;
        }
        ids[nmsgs] = e[i].id;
        msgs[nmsgs].text = t;
        nmsgs++;
        added = 1;
        e = store_index(&n);
    }
    /* a state that changed shows; a received text marked read changes nothing that shows */
    int shown = added;
    for (int i = 0; i < nmsgs; i++) {
        struct convo_msg was = msgs[i];
        describe(i);
        shown |= was.state != msgs[i].state || was.note != msgs[i].note || was.alert != msgs[i].alert;
    }
    if (added)
        convo_set(&blocks, msgs, nmsgs);
    else if (shown)
        convo_refresh(&blocks);
    hint |= (uint8_t)shown;
}

static void mark_read(void)
{
    for (int i = 0; i < nmsgs; i++) {
        const struct store_entry *e = store_find(ids[i]);
        if (e && e->state == SMS_RECEIVED)
            sms_mark_read(ids[i]);
    }
    ui_status_unread((int)store_unread());
}

/* the text's count with its parts: "12/160", "2 parts 40/153" */
static void count_parts(const struct text_entry *e, char *out, unsigned max)
{
    /* asked twice per key (the box's height, its paint): the last answer is kept for the same text */
    static uint32_t last_sum = 1;
    static char last[24];
    uint32_t sum = e->len;
    for (unsigned i = 0; i < e->len; i++)
        sum = sum * 31 + (uint8_t)e->text[i];
    if (sum == last_sum) {
        copy_text(out, last, max);
        return;
    }
    last_sum = sum;
    static char utf[TEXT_MAX * 3 + 1];
    unsigned len = text_to_utf8(utf, sizeof utf, e->text);
    struct sms_plan plan = { .coding = SMS_GSM7 };
    int parts = sms_plan(utf, len, &plan);
    if (parts < 0) {
        copy_text(last, "too long", sizeof last);
        copy_text(out, last, max);
        return;
    }
    unsigned single = plan.coding == SMS_UCS2 ? SMS_UCS2_SINGLE : SMS_GSM7_SINGLE;
    unsigned per = plan.coding == SMS_UCS2 ? SMS_UCS2_PART : SMS_GSM7_PART;
    char t[32];
    int n = 0;
    unsigned used = plan.units;
    if (parts > 1) {
        n += format_uint(t + n, (unsigned)parts);
        copy_text(t + n, " parts ", sizeof t - (unsigned)n);
        n += 7;
        used = plan.units - (unsigned)(parts - 1) * per;
        if (used > per)
            used = per;
    }
    n += format_uint(t + n, used);
    t[n++] = '/';
    format_uint(t + n, parts > 1 ? per : single);
    copy_text(last, t, sizeof last);
    copy_text(out, last, max);
}

/* the box (as high as its text needs, up to BOX_LINES) and the blocks above it */
static void place(int lines)
{
    const struct rect *c = &layout.convo.compose;
    int h = text_entry_height(lines), bottom = c->y + c->h;
    box.r = (struct rect){ c->x, (int16_t)(bottom - h), c->w, (int16_t)h };
    blocks.r = layout.convo.blocks;
    blocks.r.h = (int16_t)(box.r.y - blocks.r.y);    /* to the box: a box that got smaller leaves nothing */
    blocks.below = 4;
    box_lines = lines;
    convo_refresh(&blocks);
    text_entry_touch(&box);
    hint = 1;
}

static void fit_box(void)
{
    int lines = text_entry_lines(&box, layout.convo.compose.w);
    if (lines > BOX_LINES)
        lines = BOX_LINES;
    if (lines != box_lines)
        place(lines);
}

static void names(void)
{
    people_name(conv_number, conv_title, sizeof conv_title);
    const char *name = contacts_lookup(conv_number);
    if (name) {
        char first[48];
        text_from_utf8(first, sizeof first, name);
        unsigned n = 0;
        while (first[n] && first[n] != ' ' && n + 1 < sizeof conv_who)
            n++;
        first[n] = 0;
        copy_text(conv_who, first, sizeof conv_who);
    } else {
        copy_text(conv_who, conv_number, sizeof conv_who);
    }
}

/* the box's text as the number's draft (an empty box deletes it); nothing is written when it did not change */
static void keep_draft(void)
{
    text_entry_timer(&box);
    if (!draft_number[0] || strcmp(box.text, draft_kept) == 0)
        return;
    static char utf[TEXT_MAX * 3 + 1];
    unsigned len = text_to_utf8(utf, sizeof utf, box.text);
    int e = store_draft_put(draft_number, clock_seconds(), utf, len);
    kprintf("ui: draft for %s %s (%u bytes): %d\n", draft_number, len ? "kept" : "deleted", len, e);
    if (!e)
        copy_text(draft_kept, box.text, sizeof draft_kept);
}

/* the number's draft in the box, the cursor at its end */
static void restore_draft(void)
{
    copy_text(draft_number, conv_number, sizeof draft_number);
    draft_kept[0] = 0;
    if (!store_draft_find(conv_key) || store_draft_get(conv_key, utf_buf, sizeof utf_buf) <= 0)
        return;
    text_from_utf8(draft_kept, sizeof draft_kept, utf_buf);
    text_entry_set(&box, draft_kept);
    copy_text(draft_kept, box.text, sizeof draft_kept);    /* what the box took (cut to its length) */
    kprintf("ui: draft for %s restored (%u characters)\n", draft_number, box.len);
}

static void thread_enter(int fresh)
{
    static int made;
    if (!made) {
        ui_timer_init(&tap_timer, TIMER_TAP);
        box.placeholder = "Write a message";
        box.count = count_parts;
        text_entry_init(&box, &layout.convo.compose, &tap_timer);
        made = 1;
    }
    names();
    if (fresh) {
        text_entry_init(&box, &layout.convo.compose, &tap_timer);   /* empty, in the mode the setting gives */
        restore_draft();
        load_all();
    } else {
        for (int i = 0; i < nmsgs; i++)
            describe(i);
    }
    mark_read();
    ui_title(conv_title);
    ui_soft_keys("Options", "Send", "Back");
    box_lines = 0;
    place(1);
    if (fresh)
        convo_set(&blocks, msgs, nmsgs);
    fit_box();
}

static void thread_leave(void)
{
    keep_draft();              /* also when a screen opens over it (Options): nothing is written if it did not change */
    timer_stop(&tap_timer);
}

static void thread_paint(const struct surface *fb)
{
    int redo = blocks.dirty || hint;
    convo_paint(&blocks, fb);
    if (redo) {
        hint = 0;
        if (!nmsgs) {
            const struct font *f = theme->body;
            const char *line = "No messages yet";
            int y = blocks.r.y + blocks.r.h / 2;
            gfx_text_over(fb, &blocks.r, f, (DISPLAY_W - gfx_text_width(f, line)) / 2, y, line, ink.muted);
        }
    }
    text_entry_paint(&box, fb);
}

static void send(void)
{
    text_entry_commit(&box);
    if (!box.len) {
        ui_note("Write a message first");
        return;
    }
    static char utf[TEXT_MAX * 3 + 1];
    text_to_utf8(utf, sizeof utf, box.text);
    int32_t id = sms_send(conv_number, utf);
    kprintf("ui: send to %s: %d\n", conv_number, id);
    if (id < 0) {
        ui_note(id == STORE_FULL ? "Not sent: the memory is full" : id > -1000 ? "Not sent: storage error"
                                                                               : sms_cause_text((unsigned)-id));
        return;
    }
    text_entry_clear(&box);
    keep_draft();              /* sent: the draft goes */
    fit_box();
    sync();                    /* the new block at once, "Sending..." */
}

/* ---- options of a conversation ---- */

static uint32_t focus_id;

static void delete_message_answer(unsigned key)
{
    if (key != KEY_SELECT)
        return;
    store_delete(focus_id);
    sync();
    ui_status_unread((int)store_unread());
    ui_note("Deleted");
}

static const struct dialog delete_message_dialog = {
    .text = "Delete this message?", .centre = "Delete", .right = "Keep", .answer = delete_message_answer,
};

static void delete_conversation(uint32_t key)
{
    for (;;) {
        unsigned n;
        const struct store_entry *e = store_index(&n);
        unsigned i = 0;
        while (i < n && e[i].key != key)
            i++;
        if (i == n || store_delete(e[i].id))
            break;
    }
    store_draft_delete(key);
    ui_status_unread((int)store_unread());
}

static void delete_conversation_answer(unsigned key)
{
    if (key != KEY_SELECT)
        return;
    delete_conversation(conv_key);
    text_entry_clear(&box);
    draft_kept[0] = 0;         /* nothing to keep when it closes */
    ui_pop();
    ui_note("Deleted");
}

static const struct dialog delete_conversation_dialog = {
    .text = "Delete the whole conversation?", .centre = "Delete", .right = "Keep",
    .answer = delete_conversation_answer,
};

static void retry(uint32_t id)
{
    /* the same message goes again, from the first part the network did not take */
    int e = sms_retry(id);
    kprintf("ui: retry of message %u: %d\n", id, e ? e : (int)id);
    if (e)
        ui_note("Not sent again: storage error");
    sync();
}

enum { CO_RETRY, CO_DELETE, CO_DELETE_ALL, CO_CALL, CO_CONTACT, CO_SYMBOL };
static uint8_t thread_options_map[7];

static int thread_option(int row)
{
    switch (thread_options_map[row]) {
    case CO_RETRY:
        ui_pop();
        retry(focus_id);
        return 1;
    case CO_DELETE:
        ui_pop();
        ui_dialog(&delete_message_dialog);
        return 1;
    case CO_DELETE_ALL:
        ui_pop();
        ui_dialog(&delete_conversation_dialog);
        return 1;
    case CO_SYMBOL:
        ui_pop();
        text_entry_symbols(&box);
        return 1;
    case CO_CONTACT:
        if (contacts_lookup_id(conv_number)) {
            ui_pop();
            contacts_show_number(conv_number);
        } else {
            contacts_new_with_number(conv_number);
        }
        return 1;
    }
    return 0;
}

static void thread_options(void)
{
    struct choice c = { .title = "Options", .chosen = thread_option };
    int f = convo_focus(&blocks);
    focus_id = f >= 0 && f < nmsgs ? ids[f] : 0;
    const struct store_entry *e = focus_id ? store_find(focus_id) : 0;
    if (e && e->dir == SMS_OUT && e->state == SMS_FAILED) {
        thread_options_map[c.count] = CO_RETRY;
        c.rows[c.count++] = (struct choice_row){ .label = "Retry" };
    }
    if (focus_id) {
        thread_options_map[c.count] = CO_DELETE;
        c.rows[c.count++] = (struct choice_row){ .label = "Delete message" };
        thread_options_map[c.count] = CO_DELETE_ALL;
        c.rows[c.count++] = (struct choice_row){ .label = "Delete conversation" };
    }
    thread_options_map[c.count] = CO_CALL;
    c.rows[c.count++] = (struct choice_row){ .label = "Call", .why = "Calls are not available yet" };
    thread_options_map[c.count] = CO_CONTACT;
    c.rows[c.count++] = (struct choice_row){ .label = contacts_lookup_id(conv_number) ? "View contact" : "Add to contacts" };
    thread_options_map[c.count] = CO_SYMBOL;
    c.rows[c.count++] = (struct choice_row){ .label = "Add symbol" };
    choice_open(&c);
}

static int thread_key(unsigned k)
{
    if (k == KEY_SOFT_LEFT && text_entry_key(&box, k))
        return 1;              /* Spell */
    switch (k) {
    case KEY_SELECT:
        send();
        return 1;
    case KEY_SOFT_LEFT:
        text_entry_commit(&box);
        thread_options();
        return 1;
    case KEY_SOFT_RIGHT:
        ui_pop();
        return 1;
    case KEY_CALL:
        ui_note("Calls are not available yet");
        return 1;
    }
    if (text_entry_key(&box, k)) {
        fit_box();
        return 1;
    }
    return convo_key(&blocks, k);
}

static void thread_timer(unsigned id)
{
    if (id == TIMER_TAP)
        text_entry_timer(&box);
}

static const struct screen convo_screen = {
    .name = "conversation",
    .flags = SCREEN_TITLE,
    .enter = thread_enter,
    .leave = thread_leave,
    .paint = thread_paint,
    .key = thread_key,
    .timer = thread_timer,
};

void messages_open(const char *number)
{
    char n[SMS_NUMBER_MAX];
    if (phonenum_normalize(number, n, sizeof n) < 0) {
        ui_note("Not a phone number");
        return;
    }
    copy_text(conv_number, n, sizeof conv_number);
    conv_key = phonenum_key(n);
    ui_open(&convo_screen);
}

static void open_conv(int i)
{
    char number[SMS_NUMBER_MAX];
    conv_number_of(&convs[i], number, sizeof number);
    copy_text(conv_number, number, sizeof conv_number);
    conv_key = convs[i].key;
    ui_open(&convo_screen);
}

/* ---- New message: the recipient ---- */

static uint16_t order[CONTACTS_MAX];       /* contacts with a number, alphabetical (contacts_at indexes) */
static unsigned norder;
static struct list to_list;
static char to_name[48];
static uint32_t to_contact;
static struct vcard_contact to_card;

static const char *to_label(int row)
{
    if (row == 0)
        return "Enter number";
    uint32_t id;
    const char *name;
    if (contacts_at(order[row - 1], &id, &name))
        return "";
    text_from_utf8(to_name, sizeof to_name, name);
    return to_name;
}

static const char *to_value(int row)
{
    return row == 0 || contacts_numbers_at(order[row - 1]) > 1 ? LIST_CHEVRON : "";
}

static void to_enter(int fresh)
{
    int sel = to_list.selected;
    unsigned all = people_sorted(order, CONTACTS_MAX);
    norder = 0;
    for (unsigned i = 0; i < all; i++)
        if (contacts_numbers_at(order[i]))
            order[norder++] = order[i];
    struct rect r = layout.content;
    r.h = (int16_t)(layout.list.rows * layout.list.row_h);
    list_init(&to_list, &r, 1 + (int)norder);
    to_list.label = to_label;
    to_list.value = to_value;
    if (!fresh)
        list_select(&to_list, sel);
    ui_title("New message");
    ui_soft_keys("", "Select", "Back");
}

static void to_paint(const struct surface *fb)
{
    list_paint(&to_list, fb);
}

static int number_entered(const char *text)
{
    char n[SMS_NUMBER_MAX];
    if (!text[0] || phonenum_normalize(text, n, sizeof n) < 0) {
        ui_note("Not a phone number");
        return 1;              /* stay in the editor */
    }
    messages_open(n);
    return 1;
}

static int to_number_chosen(int row)
{
    messages_open(to_card.numbers[row].number);
    return 1;
}

static void to_choose(int row)
{
    if (row == 0) {
        struct editor e = { .title = "New message", .placeholder = "Number", .help = "The number to write to",
                            .max = 24, .phone = 1, .save = number_entered };
        editor_open(&e);
        return;
    }
    const char *name;
    if (contacts_at(order[row - 1], &to_contact, &name) || contacts_get(to_contact, &to_card) || !to_card.count)
        return;
    if (to_card.count == 1) {
        messages_open(to_card.numbers[0].number);
        return;
    }
    static char labels[VCARD_NUMBERS][24];
    struct choice c = { .title = "Send to", .count = to_card.count, .chosen = to_number_chosen };
    for (unsigned i = 0; i < to_card.count; i++) {
        text_from_utf8(labels[i], sizeof labels[i], to_card.numbers[i].number);
        c.rows[i] = (struct choice_row){ .label = labels[i], .value = vcard_label_name(to_card.numbers[i].label) };
    }
    choice_open(&c);
}

static int to_key(unsigned k)
{
    switch (list_key(&to_list, k)) {
    case LIST_CHOSEN:
        to_choose(to_list.selected);
        return 1;
    case LIST_USED:
        return 1;
    }
    int j = people_jump(order, norder, k);
    if (j >= 0) {
        list_select(&to_list, j + 1);
        return 1;
    }
    if (k == KEY_SOFT_RIGHT) {
        ui_pop();
        return 1;
    }
    return 0;
}

static const struct screen to_screen = {
    .name = "recipient",
    .flags = SCREEN_TITLE | SCREEN_PASSING,
    .enter = to_enter,
    .paint = to_paint,
    .key = to_key,
};

static void pick_recipient(void)
{
    ui_open(&to_screen);
}

void messages_compose(void)
{
    pick_recipient();
}

/* ---- the services' news ---- */

void messages_start(void)
{
#ifndef MYNA_UI_DEMO          /* with it, the envelope of the mock-ups stays */
    ui_status_unread(store_ready() ? (int)store_unread() : 0);
#endif
}

void messages_power_off(void)
{
    if (ui_in_stack(&convo_screen))
        keep_draft();
}

void messages_network(void)
{
    if (!ui_in_stack(&convo_screen))
        return;
    for (int i = 0; i < nmsgs; i++)
        describe(i);
    convo_refresh(&blocks);
}

/* a toast: who wrote, and the first words */
static void notify(uint32_t id)
{
    struct sms_record r;
    if (store_read(id, &r, utf_buf, sizeof utf_buf) < 0)
        return;
    char name[48], text[96], line[64], toast[80];
    people_name(r.number, name, sizeof name);
    text_from_utf8(text, sizeof text, utf_buf);
    int width = DISPLAY_W - 24 - 2 * layout.toast.pad;
    text_fit(theme->body, name, width, toast, 40);
    unsigned n = (unsigned)strlen(toast);
    toast[n++] = '\n';
    text_fit(theme->body, text, width, line, sizeof line);
    copy_text(toast + n, line, sizeof toast - n);
    kprintf("ui: new message %u from %s: toast\n", id, r.number);
    ui_note_ms(toast, TOAST_MS);
}

void messages_sms_event(unsigned ev, uint32_t id)
{
    const struct store_entry *e = store_find(id);
    int here = ui_current() == &convo_screen;
    if (e && ui_in_stack(&convo_screen) && e->key == conv_key) {
        sync();
        if (ev == SMS_EV_RECEIVED && here) {
            mark_read();
            id = 0;            /* read where it arrived: no toast */
        }
    }
    if (ev == SMS_EV_RECEIVED && id) {
        notify(id);
#ifdef MYNA_BENCH
        ui_bench_from(sms_stats()->last_receive_mark, "incoming message (+CMT to the toast)");
#endif
    }
    if (ev == SMS_EV_FAILED && !(here && e && e->key == conv_key)) {
        char name[48], toast[80];
        number_of(id, toast, sizeof toast);
        people_name(toast, name, sizeof name);
        copy_text(toast, "Not sent to ", sizeof toast);
        copy_text(toast + 12, name, sizeof toast - 12);
        ui_note_ms(toast, TOAST_MS);
    }
    if (ui_in_stack(&messages_screen))
        refresh_list();
    ui_status_unread((int)store_unread());
}
