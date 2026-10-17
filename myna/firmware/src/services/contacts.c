/* SPDX-License-Identifier: MIT */
/* Contacts (services/contacts.h). */
#include <stdint.h>

#include "fs/storage.h"
#include "kernel/heap.h"
#include "kernel/ostimer.h"
#include "lib/keyseq.h"
#include "lib/mem.h"
#include "lib/phonenum.h"
#include "lib/print.h"
#include "services/contacts.h"

#define FILE_MAX 2048          /* a contact's vCard: four numbers, a note of 255 bytes and the names fit in 1 KB */
#define INDEX_PATH  "/contacts/index"
#define INDEX_MAGIC 0x32584E43u    /* "CNX2" (CNX1 had no numbers: such an index is made again from the files) */

enum { E_NOT_FOUND = -1, E_STORAGE = -2, E_FULL = -3 };

/* the index entry, also the record of the index file */
struct entry {
    uint32_t id;
    uint32_t keys[VCARD_NUMBERS];
    uint8_t nkeys;
    uint8_t pad[3];
    char name[CONTACT_NAME_MAX];
    char numbers[CONTACT_NUMBERS_TEXT];    /* the normal forms, between spaces (smart search, contacts_number_at) */
};

struct index_header {
    uint32_t magic;
    uint16_t entry_size, pad;
    uint32_t count, next_id;
};

static lfs_t *fs;
static struct entry *index_;   /* CONTACTS_MAX entries from the start-up heap (64 KB kept out of .bss) */
/* what a search compares, made from an entry when it is read or changed (RAM only) */
struct derived {
    char keys[CONTACT_NAME_MAX];   /* the name's keys (lib/keyseq.h) */
    uint16_t starts;               /* bit k: a word starts with key k */
    uint16_t digits;               /* bit d: a number has the digit d */
    uint32_t pairs[4];             /* bit 10 a + b: a number has the digits a, b next to each other */
    uint32_t head[2];              /* the name's first 8 bytes as the alphabet compares them, as two numbers */
};
static struct derived *derived;    /* CONTACTS_MAX of them, from the heap as well */
static uint16_t alpha[CONTACTS_MAX];           /* indexes in alphabetical order */
static uint16_t rank[CONTACTS_MAX];            /* each index's place in it */
static unsigned count;
static uint32_t next_id = 1;
static uint8_t loaded;
static uint8_t file_cache[STORAGE_FILE_CACHE];
static char file_buf[FILE_MAX];

static void path_of(char *out, uint32_t id)
{
    static const char hex[] = "0123456789abcdef";
    memcpy(out, "/contacts/", 10);
    for (int i = 0; i < 8; i++)
        out[10 + i] = hex[(id >> (28 - 4 * i)) & 15];
    memcpy(out + 18, ".vcf", 5);
}

static int id_of(const char *name, uint32_t *id)
{
    uint32_t v = 0;
    for (int i = 0; i < 8; i++) {
        char c = name[i];
        if (c >= '0' && c <= '9')
            v = v << 4 | (uint32_t)(c - '0');
        else if (c >= 'a' && c <= 'f')
            v = v << 4 | (uint32_t)(c - 'a' + 10);
        else
            return -1;
    }
    if (strcmp(name + 8, ".vcf"))
        return -1;
    *id = v;
    return 0;
}

static int read_text(const char *path, char *out, unsigned max)
{
    lfs_file_t f;
    struct lfs_file_config fc = { .buffer = file_cache };
    if (lfs_file_opencfg(fs, &f, path, LFS_O_RDONLY, &fc))
        return E_NOT_FOUND;
    lfs_ssize_t n = lfs_file_read(fs, &f, out, max - 1);
    lfs_file_close(fs, &f);
    if (n < 0)
        return E_STORAGE;
    out[n] = 0;
    return (int)n;
}

static int write_text(const char *path, const char *text, unsigned len)
{
    lfs_file_t f;
    struct lfs_file_config fc = { .buffer = file_cache };
    int e = lfs_file_opencfg(fs, &f, path, LFS_O_WRONLY | LFS_O_CREAT | LFS_O_TRUNC, &fc);
    if (e)
        return e == LFS_ERR_NOSPC ? E_FULL : E_STORAGE;
    lfs_ssize_t w = lfs_file_write(fs, &f, text, len);
    int c = lfs_file_close(fs, &f);
    if (w < 0 || c)
        return (w == LFS_ERR_NOSPC || c == LFS_ERR_NOSPC) ? E_FULL : E_STORAGE;
    return 0;
}

static void fill(struct entry *e, uint32_t id, const struct vcard_contact *c)
{
    e->id = id;
    vcard_display_name(c, e->name, sizeof e->name);
    e->nkeys = c->count;
    unsigned len = 0;
    e->numbers[0] = 0;
    for (unsigned i = 0; i < c->count; i++) {
        e->keys[i] = phonenum_key(c->numbers[i].number);
        char n[VCARD_NUMBER_MAX];
        int l = phonenum_normalize(c->numbers[i].number, n, sizeof n);
        if (l <= 0 || len + (len > 0) + (unsigned)l + 1 > sizeof e->numbers)
            continue;          /* not a number, or no room for it whole: not searched */
        if (len)
            e->numbers[len++] = ' ';
        memcpy(e->numbers + len, n, (size_t)l + 1);
        len += (unsigned)l;
    }
}

/* ---- what smart search needs: the keys of each name, the alphabetical order ---- */

static char lower(char c)
{
    return c >= 'A' && c <= 'Z' ? (char)(c + 32) : c;
}

/* names in the order of a phone book: letters without regard to case, then the bytes; equal names by index */
static int before(unsigned a, unsigned b)
{
    /* most names differ in their first 8 bytes: two comparisons of numbers */
    const uint32_t *p = derived[a].head, *q = derived[b].head;
    if (p[0] != q[0])
        return p[0] < q[0];
    if (p[1] != q[1])
        return p[1] < q[1];
    const char *x = index_[a].name, *y = index_[b].name;
    for (; *x && lower(*x) == lower(*y); x++, y++)
        ;
    int d = (int)(uint8_t)lower(*x) - (int)(uint8_t)lower(*y);
    return d < 0 || (d == 0 && a < b);
}

static void derive(unsigned i)
{
    struct derived *d = &derived[i];
    const char *name = index_[i].name;
    d->head[0] = d->head[1] = 0;
    for (unsigned k = 0, end = 0; k < 8; k++) {
        end |= !name[k];
        d->head[k >> 2] |= (uint32_t)(end ? 0 : (uint8_t)lower(name[k])) << (24 - 8 * (k & 3));
    }
    keyseq_name(name, d->keys, 0, sizeof d->keys);
    d->starts = d->digits = 0;
    memset(d->pairs, 0, sizeof d->pairs);
    for (const char *k = d->keys; *k; k++)
        if (k == d->keys || k[-1] == ' ')
            d->starts |= (uint16_t)(1u << (*k - '0'));
    for (const char *n = index_[i].numbers; *n; n++)
        if (*n >= '0' && *n <= '9') {
            d->digits |= (uint16_t)(1u << (*n - '0'));
            if (n[1] >= '0' && n[1] <= '9') {
                unsigned b = (unsigned)(*n - '0') * 10 + (unsigned)(n[1] - '0');
                d->pairs[b >> 5] |= 1u << (b & 31);
            }
        }
}

/* the alphabetical order again (a merge sort: about 4,500 comparisons for 500 contacts) */
static void sort(void)
{
    static uint16_t tmp[CONTACTS_MAX];
    for (unsigned i = 0; i < count; i++)
        alpha[i] = (uint16_t)i;
    for (unsigned w = 1; w < count; w *= 2) {
        for (unsigned lo = 0; lo < count; lo += 2 * w) {
            unsigned mid = lo + w < count ? lo + w : count, hi = lo + 2 * w < count ? lo + 2 * w : count;
            unsigned a = lo, b = mid, k = lo;
            while (a < mid && b < hi)
                tmp[k++] = before(alpha[b], alpha[a]) ? alpha[b++] : alpha[a++];
            while (a < mid)
                tmp[k++] = alpha[a++];
            while (b < hi)
                tmp[k++] = alpha[b++];
        }
        memcpy(alpha, tmp, count * sizeof alpha[0]);
    }
    for (unsigned i = 0; i < count; i++)
        rank[alpha[i]] = (uint16_t)i;
}

static int find(uint32_t id)
{
    for (unsigned i = 0; i < count; i++)
        if (index_[i].id == id)
            return (int)i;
    return -1;
}

static int write_index(void)
{
    struct index_header h = { INDEX_MAGIC, sizeof(struct entry), 0, count, next_id };
    lfs_file_t f;
    struct lfs_file_config fc = { .buffer = file_cache };
    int e = lfs_file_opencfg(fs, &f, INDEX_PATH, LFS_O_WRONLY | LFS_O_CREAT | LFS_O_TRUNC, &fc);
    if (e)
        return e == LFS_ERR_NOSPC ? E_FULL : E_STORAGE;
    lfs_ssize_t w = lfs_file_write(fs, &f, &h, sizeof h);
    if (w >= 0 && count)
        w = lfs_file_write(fs, &f, index_, count * sizeof index_[0]);
    int c = lfs_file_close(fs, &f);
    return w < 0 || c ? E_STORAGE : 0;
}

static int read_index(void)
{
    struct index_header h;
    lfs_file_t f;
    struct lfs_file_config fc = { .buffer = file_cache };
    if (lfs_file_opencfg(fs, &f, INDEX_PATH, LFS_O_RDONLY, &fc))
        return E_NOT_FOUND;
    int ok = lfs_file_read(fs, &f, &h, sizeof h) == sizeof h && h.magic == INDEX_MAGIC &&
             h.entry_size == sizeof(struct entry) && h.count <= CONTACTS_MAX;
    if (ok && h.count)
        ok = lfs_file_read(fs, &f, index_, h.count * sizeof index_[0]) == (lfs_ssize_t)(h.count * sizeof index_[0]);
    lfs_file_close(fs, &f);
    if (!ok)
        return E_STORAGE;
    count = h.count;
    next_id = h.next_id;
    return 0;
}

/* the slow way, without an index: every contact's file */
static void rebuild(void)
{
    lfs_dir_t dir;
    static struct lfs_info info;
    count = 0;
    if (lfs_dir_open(fs, &dir, "/contacts"))
        return;
    while (lfs_dir_read(fs, &dir, &info) > 0 && count < CONTACTS_MAX) {
        uint32_t id;
        if (info.type != LFS_TYPE_REG || id_of(info.name, &id))
            continue;
        char path[24];
        path_of(path, id);
        static struct vcard_contact c;
        int n = read_text(path, file_buf, sizeof file_buf);
        if (n < 0 || vcard_parse(file_buf, (unsigned)n, &c))
            continue;
        unsigned i = count++;
        while (i && index_[i - 1].id > id) {        /* kept in id order */
            index_[i] = index_[i - 1];
            i--;
        }
        fill(&index_[i], id, &c);
        if (id >= next_id)
            next_id = id + 1;
    }
    lfs_dir_close(fs, &dir);
}

int contacts_init(void)
{
    if (loaded)
        return fs ? 0 : E_STORAGE;
    loaded = 1;
    ktime_t t0 = ktime_now();
    index_ = heap_take(CONTACTS_MAX * sizeof index_[0], 4);
    derived = heap_take(CONTACTS_MAX * sizeof derived[0], 4);
    fs = index_ && derived ? storage_fs(FS_USER) : 0;
    if (!fs)
        return E_STORAGE;
    if (lfs_mkdir(fs, "/contacts") != 0) {
        if (read_index()) {
            rebuild();
            write_index();
        } else {
            /* a contact written after the last index (a power cut between the file and the index) */
            char path[24];
            static struct vcard_contact c;
            unsigned found = 0;
            for (;;) {
                path_of(path, next_id);
                int n = count < CONTACTS_MAX ? read_text(path, file_buf, sizeof file_buf) : -1;
                if (n < 0)
                    break;
                if (!vcard_parse(file_buf, (unsigned)n, &c))
                    fill(&index_[count++], next_id, &c);
                next_id++;
                found++;
            }
            if (found)
                write_index();
        }
    }
    ktime_t t1 = ktime_now();
    for (unsigned i = 0; i < count; i++)
        derive(i);
    sort();
    kprintf("contacts: %u read in %u us (their keys and order %u us)\n", count, ktime_to_us(ktime_now() - t0),
            ktime_to_us(ktime_now() - t1));
    return 0;
}

static int save(uint32_t id, const struct vcard_contact *c)
{
    int n = vcard_format(c, file_buf, sizeof file_buf);
    if (n < 0)
        return E_NOT_FOUND;
    char path[24];
    path_of(path, id);
    return write_text(path, file_buf, (unsigned)n);
}

int32_t contacts_add(const struct vcard_contact *c)
{
    if (contacts_init())
        return E_STORAGE;
    if (count >= CONTACTS_MAX)
        return E_FULL;
    uint32_t id = next_id;
    int e = save(id, c);
    if (e)
        return e;
    next_id++;
    fill(&index_[count], id, c);
    derive(count++);
    sort();
    if (write_index())
        kprintf("contacts: the index was not written\n");    /* found again from the files at the next start */
    return (int32_t)id;
}

int contacts_update(uint32_t id, const struct vcard_contact *c)
{
    if (contacts_init())
        return E_STORAGE;
    int i = find(id);
    if (i < 0)
        return E_NOT_FOUND;
    int e = save(id, c);
    if (!e) {
        fill(&index_[i], id, c);
        derive((unsigned)i);
        sort();
        e = write_index();
    }
    return e;
}

int contacts_delete(uint32_t id)
{
    if (contacts_init())
        return E_STORAGE;
    int i = find(id);
    if (i < 0)
        return E_NOT_FOUND;
    char path[24];
    path_of(path, id);
    if (lfs_remove(fs, path))
        return E_STORAGE;
    for (unsigned k = (unsigned)i; k + 1 < count; k++) {
        index_[k] = index_[k + 1];
        derived[k] = derived[k + 1];
    }
    count--;
    sort();
    return write_index();
}

int contacts_get(uint32_t id, struct vcard_contact *c)
{
    if (contacts_init())
        return E_STORAGE;
    char path[24];
    path_of(path, id);
    int n = read_text(path, file_buf, sizeof file_buf);
    if (n < 0)
        return n;
    return vcard_parse(file_buf, (unsigned)n, c) ? E_NOT_FOUND : 0;
}

static const struct entry *lookup(const char *number)
{
    if (contacts_init() || !number[0])
        return 0;
    uint32_t key = phonenum_key(number);
    for (unsigned i = 0; i < count; i++)
        for (unsigned k = 0; k < index_[i].nkeys; k++)
            if (index_[i].keys[k] == key)
                return &index_[i];
    return 0;
}

const char *contacts_lookup(const char *number)
{
    const struct entry *e = lookup(number);
    return e ? e->name : 0;
}

uint32_t contacts_lookup_id(const char *number)
{
    const struct entry *e = lookup(number);
    return e ? e->id : 0;
}

unsigned contacts_count(void)
{
    contacts_init();
    return count;
}

int contacts_at(unsigned i, uint32_t *id, const char **name)
{
    if (contacts_init() || i >= count)
        return E_NOT_FOUND;
    *id = index_[i].id;
    *name = index_[i].name;
    return 0;
}

unsigned contacts_numbers_at(unsigned i)
{
    return contacts_init() || i >= count ? 0 : index_[i].nkeys;
}

unsigned contacts_sorted(uint16_t *order, unsigned max)
{
    unsigned n = contacts_count() < max ? count : max;
    memcpy(order, alpha, n * sizeof order[0]);
    return n;
}

unsigned contacts_rank(unsigned i)
{
    return i < count ? rank[i] : CONTACTS_MAX;
}

int contacts_number_at(unsigned i, unsigned k, char *out, unsigned max)
{
    if (contacts_init() || i >= count || !max)
        return -1;
    const char *p = index_[i].numbers;
    for (; k && *p; p++)
        if (*p == ' ')
            k--;
    unsigned n = 0;
    while (p[n] && p[n] != ' ' && n + 1 < max) {
        out[n] = p[n];
        n++;
    }
    out[n] = 0;
    return n ? 0 : -1;
}

const uint32_t *contacts_number_keys_at(unsigned i, unsigned *n)
{
    *n = contacts_init() || i >= count ? 0 : index_[i].nkeys;
    return *n ? index_[i].keys : 0;
}

unsigned contacts_search(const char *query, const uint16_t *within, unsigned n, int with_number,
                         struct contacts_hit *out)
{
    unsigned len = (unsigned)strlen(query), hits = 0;
    if (contacts_init() || !len)
        return 0;
    /* what a contact must have to be worth comparing: a word that starts with the first key; every digit of the query
       in its numbers, and each pair of them next to each other (most contacts fail these tests of a few bits) */
    int names = 1;
    uint16_t digits = 0;
    uint32_t pairs[4] = { 0, 0, 0, 0 };
    for (unsigned i = 0; i < len; i++) {
        if (query[i] < '0' || query[i] > '9') {
            names = 0;         /* + * #: only a number can have them, and the tests do not know them */
            continue;
        }
        digits |= (uint16_t)(1u << (query[i] - '0'));
        if (i + 1 < len && query[i + 1] >= '0' && query[i + 1] <= '9') {
            unsigned b = (unsigned)(query[i] - '0') * 10 + (unsigned)(query[i + 1] - '0');
            pairs[b >> 5] |= 1u << (b & 31);
        }
    }
    uint16_t first = names ? (uint16_t)(1u << (query[0] - '0')) : 0;
    unsigned m = within ? n : count;
    for (unsigned j = 0; j < m; j++) {
        unsigned i = within ? within[j] : j;
        const struct entry *e = &index_[i];
        const struct derived *d = &derived[i];
        if (i >= count || (with_number && !e->numbers[0]))
            continue;
        int at = d->starts & first ? keyseq_word(d->keys, query, len) : -1;
        if (at >= 0) {
            out[hits++] = (struct contacts_hit){ (uint16_t)i, at ? CONTACTS_HIT_WORD : CONTACTS_HIT_NAME, 0,
                                                 (uint8_t)at };
            continue;
        }
        if (names && ((d->digits & digits) != digits || (d->pairs[0] & pairs[0]) != pairs[0] ||
                      (d->pairs[1] & pairs[1]) != pairs[1] || (d->pairs[2] & pairs[2]) != pairs[2] ||
                      (d->pairs[3] & pairs[3]) != pairs[3]))
            continue;
        unsigned which = 0;
        at = keyseq_find(e->numbers, query, len, &which);
        if (at >= 0)
            out[hits++] = (struct contacts_hit){ (uint16_t)i, CONTACTS_HIT_NUMBER, (uint8_t)which, (uint8_t)at };
    }
    return hits;
}

#ifdef MYNA_TEST_HOOKS
void contacts_test_fill(unsigned n)
{
    /* made-up names from two short lists and numbers from a counter: every combination differs */
    static const char *const given[25] = {
        "Ada", "Bram", "Cleo", "Dov", "Edda", "Finn", "Gita", "Hugo", "Ines", "Joss", "Kai", "Lena", "Milo",
        "Nora", "Otto", "Pia", "Quin", "Rosa", "Sven", "Tilda", "Uma", "Vito", "Wren", "Xia", "Yusuf",
    };
    static const char *const family[20] = {
        "Abara", "Brook", "Castell", "Dunmore", "Eklund", "Farrow", "Gallo", "Hollis", "Ibsen", "Juarez",
        "Kovac", "Lindqvist", "Marsh", "Novak", "Okafor", "Pruitt", "Rasku", "Sorensen", "Thorne", "Vance",
    };
    if (contacts_init())
        return;
    ktime_t t0 = ktime_now();
    static struct vcard_contact c;
    for (unsigned k = count; k < n && count < CONTACTS_MAX; k++) {
        memset(&c, 0, sizeof c);
        memcpy(c.given, given[k % 25], strlen(given[k % 25]) + 1);
        memcpy(c.family, family[k / 25 % 20], strlen(family[k / 25 % 20]) + 1);
        /* +1 555 03xx xxx: seven digits from k */
        char *d = c.numbers[0].number;
        memcpy(d, "+1555", 5);
        uint32_t v = 3000000 + k * 7919 % 1000000;
        for (int i = 11; i >= 5; i--, v /= 10)
            d[i] = (char)('0' + v % 10);
        d[12] = 0;
        c.count = 1;
        fill(&index_[count++], 0x10000 + k, &c);
    }
    /* what a start with this index does after reading it */
    ktime_t t1 = ktime_now();
    for (unsigned i = 0; i < count; i++)
        derive(i);
    ktime_t t2 = ktime_now();
    sort();
    kprintf("contacts: test: %u in the index (%u us; their keys %u us, the order %u us)\n", count,
            ktime_to_us(ktime_now() - t0), ktime_to_us(t2 - t1), ktime_to_us(ktime_now() - t2));
}
#endif

int contacts_export(uint32_t id, const char *path)
{
    if (contacts_init())
        return E_STORAGE;
    char from[24];
    path_of(from, id);
    int n = read_text(from, file_buf, sizeof file_buf);
    if (n < 0)
        return n;
    return write_text(path, file_buf, (unsigned)n);
}

int32_t contacts_import(const char *path)
{
    if (contacts_init())
        return E_STORAGE;
    static struct vcard_contact c;
    int n = read_text(path, file_buf, sizeof file_buf);
    if (n < 0)
        return n;
    if (vcard_parse(file_buf, (unsigned)n, &c))
        return E_NOT_FOUND;
    return contacts_add(&c);
}
