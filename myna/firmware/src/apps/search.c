/* SPDX-License-Identifier: MIT */
/* Smart search (apps/phone.h): what matches keys typed, for the dialer (dialer.c) and Contacts (people.c).
 *
 * The contacts service finds the hits (services/contacts.h: each name's keys are made when the index is read or
 * changed); this file adds the dialer's recent conversations, ranks the hits, and gives the screens what a row
 * shows. The dialer keeps the best SEARCH_SHOWN (each hit put in its place among them); Contacts keeps every hit, in
 * the alphabet's order within each kind (a pass over the alphabet per kind, no sorting). Recency comes from the
 * message store's records in RAM: when a screen opens, the newest SEARCH_CONVS conversations are listed once, and each
 * contact gets the place of its latest one. */
#include <stdint.h>

#include "apps/phone.h"
#include "kernel/ostimer.h"
#include "lib/keyseq.h"
#include "lib/mem.h"
#include "lib/print.h"
#include "sms/store.h"
#include "ui/theme.h"
#include "ui/widget.h"

#define NEVER   255            /* a contact without a recent conversation */
#define NO_RANK 1023           /* a conversation's place in the alphabet: after every contact */

/* the newest conversations, newest first */
static struct {
    uint32_t key, time;
    uint8_t known;             /* a contact has the number: the contact is the hit */
    char number[SMS_NUMBER_MAX];
} convs[SEARCH_CONVS];
static unsigned nconvs;
static uint8_t recent[CONTACTS_MAX];       /* each contact's latest conversation (its place in convs), or NEVER */
static struct contacts_hit found[CONTACTS_MAX];
static int16_t by_rank[CONTACTS_MAX];      /* Contacts: the hit (in found) of each place in the alphabet, or -1 */

/* the conversations, and each contact's latest one (a table of the conversations' keys: one probe a number) */
static void list_conversations(void)
{
    unsigned n = 0;
    const struct store_entry *e = store_ready() ? store_index(&n) : 0;
    nconvs = 0;
    for (unsigned i = n; i-- > 0 && nconvs < SEARCH_CONVS;) {
        unsigned k = 0;
        while (k < nconvs && convs[k].key != e[i].key)
            k++;
        if (k < nconvs)
            continue;
        struct sms_record r;
        if (store_read(e[i].id, &r, 0, 0) < 0)
            continue;
        convs[nconvs].key = e[i].key;
        convs[nconvs].time = e[i].time;
        convs[nconvs].known = 0;
        memcpy(convs[nconvs].number, r.number, sizeof r.number);
        convs[nconvs].number[SMS_NUMBER_MAX - 1] = 0;
        nconvs++;
    }
    uint8_t table[64];
    memset(table, NEVER, sizeof table);
    for (unsigned k = nconvs; k-- > 0;) {
        unsigned h = (convs[k].key * 2654435761u) >> 26;
        while (table[h] != NEVER && convs[table[h]].key != convs[k].key)
            h = (h + 1) & 63;
        table[h] = (uint8_t)k;
    }
    unsigned count = contacts_count();
    for (unsigned i = 0; i < count && i < CONTACTS_MAX; i++) {
        unsigned nk;
        const uint32_t *keys = contacts_number_keys_at(i, &nk);
        recent[i] = NEVER;
        for (unsigned j = 0; j < nk; j++) {
            unsigned h = (keys[j] * 2654435761u) >> 26;
            while (table[h] != NEVER && convs[table[h]].key != keys[j])
                h = (h + 1) & 63;
            if (table[h] != NEVER) {
                convs[table[h]].known = 1;
                if (table[h] < recent[i])
                    recent[i] = table[h];
            }
        }
    }
}

void search_begin(struct search *s, int dial)
{
    s->dial = (uint8_t)dial;
    s->valid = 0;
    if (dial)
        list_conversations();
}

/* a hit in its place among the best (rank: smaller is better) */
static void offer(struct search *s, struct search_hit h, uint32_t rank)
{
    s->total++;
    unsigned i = s->count;
    if (i == SEARCH_SHOWN) {
        if (rank >= s->rank[i - 1])
            return;
        i--;
    } else {
        s->count++;
    }
    for (; i > 0 && s->rank[i - 1] > rank; i--) {
        s->hits[i] = s->hits[i - 1];
        s->rank[i] = s->rank[i - 1];
    }
    s->hits[i] = h;
    s->rank[i] = rank;
}

unsigned search_run(struct search *s, const char *query)
{
    unsigned len = (unsigned)strlen(query), was = (unsigned)strlen(s->query);
    int narrow = s->valid && was && len > was && !memcmp(query, s->query, was);
    if (len > SEARCH_QUERY_MAX)
        len = SEARCH_QUERY_MAX;
    memcpy(s->query, query, len);
    s->query[len] = 0;
    s->count = 0;
    s->total = 0;
    s->valid = 0;
    if (!len)
        return 0;
#ifdef MYNA_BENCH
    ktime_t t0 = ktime_now();
    unsigned looked = narrow ? s->ncand : contacts_count();
#endif
    unsigned n = contacts_search(s->query, narrow ? s->cand : 0, s->ncand, s->dial, found);
    for (unsigned j = 0; j < n; j++)
        s->cand[j] = found[j].index;
    s->ncand = (uint16_t)n;
    if (s->dial) {
        for (unsigned j = 0; j < n; j++) {
            unsigned i = found[j].index;
            offer(s, (struct search_hit){ (uint16_t)i, found[j].kind, found[j].number, found[j].at },
                  (uint32_t)found[j].kind << 18 | (uint32_t)recent[i] << 10 | contacts_rank(i));
        }
    } else {
        unsigned places = contacts_count();
        memset(by_rank, 0xFF, places * sizeof by_rank[0]);
        for (unsigned j = 0; j < n; j++)
            by_rank[contacts_rank(found[j].index)] = (int16_t)j;
        for (unsigned kind = CONTACTS_HIT_NAME; kind <= CONTACTS_HIT_NUMBER; kind++)
            for (unsigned r = 0; r < places; r++) {
                int j = by_rank[r];
                if (j >= 0 && found[j].kind == kind)
                    s->hits[s->count++] = (struct search_hit){ found[j].index, found[j].kind, found[j].number,
                                                               found[j].at };
            }
        s->total = (uint16_t)n;
    }
    unsigned m = 0;
    if (s->dial) {
        unsigned k = narrow ? s->nconv_cand : nconvs;
        for (unsigned j = 0; j < k; j++) {
            unsigned c = narrow ? s->conv_cand[j] : j, which;
            if (c >= nconvs || convs[c].known)
                continue;
            int at = keyseq_find(convs[c].number, s->query, len, &which);
            if (at < 0)
                continue;
            s->conv_cand[m++] = (uint8_t)c;
            offer(s, (struct search_hit){ (uint16_t)(SEARCH_CONV | c), CONTACTS_HIT_NUMBER, 0, (uint8_t)at },
                  (uint32_t)CONTACTS_HIT_NUMBER << 18 | c << 10 | NO_RANK);
        }
    }
    s->nconv_cand = (uint16_t)m;
    s->valid = 1;
#ifdef MYNA_BENCH
    kprintf("bench: search \"%s\" in %u contacts: %u instructions\n", s->query, looked,
            ktime_to_us(ktime_now() - t0) * 100);
#endif
    /* the console: the query and the first hits ("search: \"266\": 2: Anne Moss, Bonn Hart") */
    char line[160];
    int p = 0;
    for (unsigned i = 0; i < s->count && i < 6 && p < 120; i++) {
        char t[40];
        int from, to;
        search_title(s, (int)i, t, sizeof t, &from, &to);
        if (i)
            line[p++] = ',', line[p++] = ' ';
        for (const char *c = t; *c && p < 150; c++)
            line[p++] = *c;
    }
    line[p] = 0;
    kprintf("search: \"%s\": %u: %s\n", s->query, s->total, line);
    return s->count;
}

void search_title(const struct search *s, int i, char *out, unsigned max, int *from, int *to)
{
    const struct search_hit *h = &s->hits[i];
    unsigned len = (unsigned)strlen(s->query);
    *from = *to = 0;
    if (h->contact & SEARCH_CONV) {
        copy_text(out, convs[h->contact & ~SEARCH_CONV].number, max);
        *from = h->at;
        *to = h->at + (int)len;
        return;
    }
    uint32_t id;
    const char *name;
    if (contacts_at(h->contact, &id, &name)) {
        copy_text(out, "?", max);
        return;
    }
    text_from_utf8(out, max, name);
    if (h->kind == CONTACTS_HIT_NUMBER)
        return;
    /* the bytes of the keys that matched: from the first one's character to the end of the last one's */
    char keys[CONTACT_NAME_MAX];
    uint8_t at[CONTACT_NAME_MAX];
    int n = keyseq_name(out, keys, at, sizeof keys);
    int last = h->at + (int)len - 1;
    if (last >= n)
        return;
    *from = at[h->at];
    *to = text_next(out, at[last]);
}

int search_number(const struct search *s, int i, char *out, unsigned max, int *from, int *to)
{
    const struct search_hit *h = &s->hits[i];
    *from = *to = 0;
    if (h->contact & SEARCH_CONV || contacts_number_at(h->contact, h->number, out, max))
        return -1;
    if (h->kind == CONTACTS_HIT_NUMBER) {
        *from = h->at;
        *to = h->at + (int)strlen(s->query);
    }
    return 0;
}

uint32_t search_when(const struct search *s, int i)
{
    const struct search_hit *h = &s->hits[i];
    unsigned c = h->contact & SEARCH_CONV ? h->contact & ~SEARCH_CONV : recent[h->contact];
    return s->dial && c < nconvs ? convs[c].time : 0;
}

uint32_t search_id(const struct search *s, int i)
{
    uint32_t id = 0;
    const char *name;
    if (!(s->hits[i].contact & SEARCH_CONV))
        contacts_at(s->hits[i].contact, &id, &name);
    return id;
}

/* one piece of a marked text, from a 0-terminated copy; returns the pen after it */
static int piece(const struct surface *s, const struct rect *clip, const struct font *f, int x, int y,
                 const char *text, int len, uint16_t fg, int sel, uint16_t bg)
{
    char buf[64];
    if (len <= 0)
        return x;
    if (len >= (int)sizeof buf)
        len = (int)sizeof buf - 1;
    memcpy(buf, text, (size_t)len);
    buf[len] = 0;
    return sel ? gfx_text_over(s, clip, f, x, y, buf, fg) : gfx_text(s, clip, f, x, y, buf, fg, bg);
}

void search_draw(const struct surface *s, const struct rect *clip, const struct font *f, int x, int y, int width,
                 const char *text, int from, int to, uint16_t fg, int sel, uint16_t bg)
{
    char shown[64];
    text_fit(f, text, width, shown, sizeof shown);
    int n = (int)strlen(shown), kept = n;
    if (strcmp(shown, text))
        kept = n - 3;          /* cut: the ellipsis is never marked */
    if (to > kept)
        to = kept;
    if (from > to)
        from = to;
    if (sel)
        fg = ink.on_accent;
    x = piece(s, clip, f, x, y, shown, from, fg, sel, bg);
    int mx = x;
    x = piece(s, clip, f, x, y, shown + from, to - from, sel ? fg : ink.accent, sel, bg);
    if (sel && x > mx) {
        struct rect u = { (int16_t)mx, (int16_t)(y + 2), (int16_t)(x - mx), 2 };
        gfx_fill(s, &u, ink.on_accent);
    }
    piece(s, clip, f, x, y, shown + to, n - to, fg, sel, bg);
}
