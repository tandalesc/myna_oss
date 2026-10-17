/* SPDX-License-Identifier: MIT */
/* The message store (sms/store.h). */
#include <stdint.h>

#include "fs/storage.h"
#include "kernel/heap.h"
#include "kernel/ostimer.h"
#include "lib/mem.h"
#include "lib/phonenum.h"
#include "lib/print.h"
#include "sms/store.h"

#define ATTR_RECORD    0x4D    /* 'M': the struct sms_record of a message file or a part file */
#define ATTR_DRAFT     0x44    /* 'D': a draft's struct draft_head */
#define RECORD_VERSION 1
#define INDEX_PATH     "/sms/index"
#define INDEX_MAGIC    0x31584D53u /* "SMX1" */
#define PARTS_MAX      64      /* parts waiting for the rest of their message */

struct index_header {
    uint32_t magic;
    uint16_t version, record_size;
    uint32_t count, next_id;
};

_Static_assert(sizeof(struct sms_record) == 56, "the record is part of the file format");

static lfs_t *fs;
/* taken from the start-up heap at store_init (36 KB: kept out of .bss, which crt0 clears before main) */
static struct sms_record *recs;                       /* oldest first (ids grow with time) */
static struct store_entry *idx;                       /* the same order: what lists need */
static unsigned count, unread;
static uint32_t next_id = 1;
static uint8_t simulate_full;
static uint8_t file_cache[STORAGE_FILE_CACHE];
static struct store_stats stats;

/* a draft file's attribute */
struct draft_head {
    uint32_t time;
    char number[SMS_NUMBER_MAX];
};

static struct store_draft drafts[STORE_DRAFTS];
static unsigned drafts_count;

static struct store_part_key parts[PARTS_MAX];
static uint8_t part_seq[PARTS_MAX];
static unsigned parts_count;

const struct store_stats *store_stats(void)
{
    return &stats;
}

int store_ready(void)
{
    return fs != 0;
}

void store_simulate_full(int on)
{
    simulate_full = (uint8_t)on;
}

int store_simulating_full(void)
{
    return simulate_full;
}

/* ---- names ---- */

static char *put_hex(char *p, uint32_t v, int digits)
{
    static const char hex[] = "0123456789abcdef";
    for (int i = digits - 1; i >= 0; i--)
        *p++ = hex[(v >> (4 * i)) & 15];
    return p;
}

static char *put_dec(char *p, unsigned v)
{
    char d[10];
    int n = 0;
    do {
        d[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v);
    while (n)
        *p++ = d[--n];
    return p;
}

static void message_path(char *out, uint32_t id)
{
    memcpy(out, "/sms/m/", 7);
    *put_hex(out + 7, id, 8) = 0;
}

static void draft_path(char *out, uint32_t key)
{
    memcpy(out, "/sms/d/", 7);
    *put_hex(out + 7, key, 8) = 0;
}

static void part_name(char *p, const struct store_part_key *k, unsigned seq)
{
    p = put_hex(p, k->key, 8);
    *p++ = '-';
    p = put_hex(p, k->ref, 4);
    *p++ = '-';
    p = put_dec(p, k->total);
    *p++ = '-';
    p = put_dec(p, seq);
    *p = 0;
}

static void part_path(char *out, const struct store_part_key *k, unsigned seq)
{
    memcpy(out, "/sms/p/", 7);
    part_name(out + 7, k, seq);
}

/* hexadecimal digits up to `stop` (or the end); returns the end or 0 */
static const char *parse_hex(const char *s, char stop, uint32_t *out)
{
    uint32_t v = 0;
    const char *b = s;
    for (; *s && *s != stop; s++) {
        char c = *s;
        if (c >= '0' && c <= '9')
            v = v << 4 | (uint32_t)(c - '0');
        else if (c >= 'a' && c <= 'f')
            v = v << 4 | (uint32_t)(c - 'a' + 10);
        else
            return 0;
    }
    *out = v;
    return s > b ? s : 0;
}

static const char *parse_dec(const char *s, char stop, uint32_t *out)
{
    uint32_t v = 0;
    const char *b = s;
    for (; *s && *s != stop; s++) {
        if (*s < '0' || *s > '9')
            return 0;
        v = v * 10 + (uint32_t)(*s - '0');
    }
    *out = v;
    return s > b ? s : 0;
}

/* ---- the index ---- */

static void entry_from(struct store_entry *e, const struct sms_record *r)
{
    e->id = r->id;
    e->time = r->time;
    e->key = phonenum_key(r->number);
    e->dir = r->dir;
    e->state = r->state;
    e->cause = r->cause;
}

static void count_unread(void)
{
    unread = 0;
    for (unsigned i = 0; i < count; i++)
        unread += idx[i].state == SMS_RECEIVED;
}

static int index_pos(uint32_t id)
{
    unsigned lo = 0, hi = count;
    while (lo < hi) {
        unsigned mid = (lo + hi) / 2;
        if (idx[mid].id < id)
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo < count && idx[lo].id == id ? (int)lo : -1;
}

/* insert keeping id order */
static void index_insert(const struct sms_record *r)
{
    unsigned i = count;
    while (i && idx[i - 1].id > r->id) {
        idx[i] = idx[i - 1];
        recs[i] = recs[i - 1];
        i--;
    }
    recs[i] = *r;
    entry_from(&idx[i], r);
    count++;
    if (r->id >= next_id)
        next_id = r->id + 1;
}

static void index_remove(unsigned i)
{
    for (; i + 1 < count; i++) {
        idx[i] = idx[i + 1];
        recs[i] = recs[i + 1];
    }
    count--;
}

const struct store_entry *store_index(unsigned *n)
{
    *n = count;
    return idx;
}

const struct store_entry *store_find(uint32_t id)
{
    int i = index_pos(id);
    return i < 0 ? 0 : &idx[i];
}

unsigned store_unread(void)
{
    return unread;
}

unsigned store_parts_waiting(void)
{
    return parts_count;
}

/* ---- files ---- */

static int result(int lfs_err)
{
    if (!lfs_err)
        return STORE_OK;
    return lfs_err == LFS_ERR_NOSPC ? STORE_FULL : STORE_ERROR;
}

/* the whole index, one commit */
static int write_index(void)
{
    struct index_header h = { INDEX_MAGIC, RECORD_VERSION, sizeof(struct sms_record), count, next_id };
    struct lfs_file_config fc = { .buffer = file_cache };
    lfs_file_t f;
    int e = lfs_file_opencfg(fs, &f, INDEX_PATH, LFS_O_WRONLY | LFS_O_CREAT | LFS_O_TRUNC, &fc);
    if (e)
        return e;
    lfs_ssize_t w = lfs_file_write(fs, &f, &h, sizeof h);
    if (w >= 0 && count)
        w = lfs_file_write(fs, &f, recs, count * sizeof recs[0]);
    int c = lfs_file_close(fs, &f);
    return w < 0 ? (int)w : c;
}

static int read_index(void)
{
    struct index_header h;
    struct lfs_file_config fc = { .buffer = file_cache };
    lfs_file_t f;
    int e = lfs_file_opencfg(fs, &f, INDEX_PATH, LFS_O_RDONLY, &fc);
    if (e)
        return e;
    lfs_ssize_t n = lfs_file_read(fs, &f, &h, sizeof h);
    int ok = n == sizeof h && h.magic == INDEX_MAGIC && h.version == RECORD_VERSION &&
             h.record_size == sizeof(struct sms_record) && h.count <= SMS_STORE_CAP;
    if (ok && h.count)
        ok = lfs_file_read(fs, &f, recs, h.count * sizeof recs[0]) == (lfs_ssize_t)(h.count * sizeof recs[0]);
    lfs_file_close(fs, &f);
    if (!ok)
        return LFS_ERR_CORRUPT;
    /* the file is in id order: the entries follow it */
    count = h.count;
    for (unsigned i = 0; i < count; i++) {
        entry_from(&idx[i], &recs[i]);
        if (recs[i].id >= next_id)
            next_id = recs[i].id + 1;
    }
    if (h.next_id > next_id)
        next_id = h.next_id;
    return 0;
}

/* a message file: its text, and its record as an attribute, in one commit */
static int write_file(const char *path, const struct sms_record *r, const char *text, unsigned len)
{
    struct lfs_attr attr = { ATTR_RECORD, (void *)r, sizeof *r };
    struct lfs_file_config fc = { .buffer = file_cache, .attrs = &attr, .attr_count = 1 };
    lfs_file_t f;
    int e = lfs_file_opencfg(fs, &f, path, LFS_O_WRONLY | LFS_O_CREAT | LFS_O_TRUNC, &fc);
    if (e)
        return e;
    lfs_ssize_t w = len ? lfs_file_write(fs, &f, text, len) : 0;
    int c = lfs_file_close(fs, &f);
    if (w < 0 || c) {
        lfs_remove(fs, path);      /* a half-written message must not stay: it was never acknowledged */
        return w < 0 ? (int)w : c;
    }
    return 0;
}

static int read_file(const char *path, struct sms_record *r, char *text, unsigned max)
{
    struct sms_record tmp;
    struct lfs_attr attr = { ATTR_RECORD, r ? r : &tmp, sizeof tmp };
    struct lfs_file_config fc = { .buffer = file_cache, .attrs = &attr, .attr_count = 1 };
    lfs_file_t f;
    int e = lfs_file_opencfg(fs, &f, path, LFS_O_RDONLY, &fc);
    if (e)
        return e == LFS_ERR_NOENT ? STORE_NOT_FOUND : STORE_ERROR;
    lfs_ssize_t n = 0;
    if (text && max) {
        n = lfs_file_read(fs, &f, text, max - 1);
        if (n >= 0)
            text[n] = 0;
    }
    lfs_file_close(fs, &f);
    return n < 0 ? STORE_ERROR : (int)n;
}

/* the slow way, when the index is missing or unreadable: every message file's own record */
static void rebuild(void)
{
    static struct lfs_info info;
    lfs_dir_t dir;
    count = 0;
    if (lfs_dir_open(fs, &dir, "/sms/m"))
        return;
    char path[24];
    while (lfs_dir_read(fs, &dir, &info) > 0) {
        uint32_t id;
        struct sms_record r;
        if (info.type != LFS_TYPE_REG || !parse_hex(info.name, 0, &id))
            continue;
        message_path(path, id);
        if (count < SMS_STORE_CAP && lfs_getattr(fs, path, ATTR_RECORD, &r, sizeof r) == sizeof r && r.id == id &&
            r.version == RECORD_VERSION)
            index_insert(&r);
    }
    lfs_dir_close(fs, &dir);
}

/* messages written after the last index (a power cut between the two commits of store_add) */
static unsigned recover(void)
{
    unsigned n = 0;
    char path[24];
    struct sms_record r;
    for (;;) {
        message_path(path, next_id);
        if (count >= SMS_STORE_CAP || lfs_getattr(fs, path, ATTR_RECORD, &r, sizeof r) != sizeof r ||
            r.id != next_id)
            return n;
        index_insert(&r);
        n++;
    }
}

static void read_parts(void)
{
    static struct lfs_info info;
    lfs_dir_t dir;
    parts_count = 0;
    if (lfs_dir_open(fs, &dir, "/sms/p"))
        return;
    while (lfs_dir_read(fs, &dir, &info) > 0 && parts_count < PARTS_MAX) {
        uint32_t key, ref, total, seq;
        const char *p = info.type == LFS_TYPE_REG ? parse_hex(info.name, '-', &key) : 0;
        if (p)
            p = parse_hex(p + 1, '-', &ref);
        if (p)
            p = parse_dec(p + 1, '-', &total);
        if (p)
            p = parse_dec(p + 1, 0, &seq);
        if (!p)
            continue;
        parts[parts_count] = (struct store_part_key){ key, (uint16_t)ref, (uint8_t)total };
        part_seq[parts_count++] = (uint8_t)seq;
    }
    lfs_dir_close(fs, &dir);
}

/* the start of a draft for the list: at most STORE_DRAFT_HEAD - 1 bytes, never a part of a character */
static void draft_head_text(char *out, const char *text, unsigned len)
{
    unsigned n = len < STORE_DRAFT_HEAD - 1 ? len : STORE_DRAFT_HEAD - 1;
    if (n < len)
        while (n && ((uint8_t)text[n] & 0xC0) == 0x80)
            n--;
    memcpy(out, text, n);
    out[n] = 0;
}

static void read_drafts(void)
{
    static struct lfs_info info;
    static char text[STORE_DRAFT_HEAD];
    lfs_dir_t dir;
    drafts_count = 0;
    if (lfs_dir_open(fs, &dir, "/sms/d"))
        return;
    char path[24];
    while (lfs_dir_read(fs, &dir, &info) > 0 && drafts_count < STORE_DRAFTS) {
        uint32_t key;
        struct draft_head h;
        if (info.type != LFS_TYPE_REG || !parse_hex(info.name, 0, &key))
            continue;
        draft_path(path, key);
        struct lfs_attr attr = { ATTR_DRAFT, &h, sizeof h };
        struct lfs_file_config fc = { .buffer = file_cache, .attrs = &attr, .attr_count = 1 };
        lfs_file_t f;
        if (lfs_file_opencfg(fs, &f, path, LFS_O_RDONLY, &fc))
            continue;
        lfs_ssize_t n = lfs_file_read(fs, &f, text, sizeof text);
        lfs_file_close(fs, &f);
        h.number[SMS_NUMBER_MAX - 1] = 0;
        if (n <= 0)
            continue;
        struct store_draft *d = &drafts[drafts_count++];
        d->key = key;
        d->time = h.time;
        memcpy(d->number, h.number, sizeof d->number);
        draft_head_text(d->head, text, (unsigned)n);
    }
    lfs_dir_close(fs, &dir);
}

int store_init(void)
{
    ktime_t t0 = ktime_now();
    recs = heap_take((SMS_STORE_CAP + 1) * sizeof recs[0], 4);
    idx = heap_take((SMS_STORE_CAP + 1) * sizeof idx[0], 4);
    fs = recs && idx ? storage_fs(FS_USER) : 0;
    if (!fs) {
        kprintf("sms store: no user file system: messages are not kept\n");
        return -1;
    }
    int fresh = lfs_mkdir(fs, "/sms") == 0;
    if (fresh) {
        lfs_mkdir(fs, "/sms/m");
        lfs_mkdir(fs, "/sms/p");
        lfs_mkdir(fs, "/sms/d");
    } else {
        int e = read_index();
        if (e && e != LFS_ERR_NOENT)
            kprintf("sms store: the index cannot be read (%d): reading every message\n", e);
        if (e) {
            rebuild();
            write_index();
        } else if (recover()) {
            kprintf("sms store: messages written after the last index found again\n");
            write_index();
        }
        read_parts();
        lfs_mkdir(fs, "/sms/d");   /* a store from before drafts */
        read_drafts();
    }
    count_unread();
    stats.init_us = ktime_to_us(ktime_now() - t0);
    stats.entries = count;
    kprintf("sms store: %u messages (%u unread), %u parts waiting, %u draft%s; read in %u us\n", count, unread,
            parts_count, drafts_count, drafts_count == 1 ? "" : "s", stats.init_us);
    return 0;
}

static int evict_oldest(void)
{
    for (unsigned i = 0; i < count; i++)
        if (idx[i].state != SMS_QUEUED) {
            stats.evicted++;
            return store_delete(idx[i].id);
        }
    return STORE_FULL;         /* everything waits to be sent */
}

int store_add(struct sms_record *r, const char *text)
{
    if (!fs)
        return STORE_ERROR;
    if (simulate_full)
        return STORE_FULL;
    if (count >= SMS_STORE_CAP && evict_oldest())
        return STORE_FULL;
    ktime_t t0 = ktime_now();
    r->id = next_id;
    r->version = RECORD_VERSION;
    char path[24];
    message_path(path, r->id);
    int e = write_file(path, r, text, r->text_len);
    if (!e) {
        index_insert(r);
        e = write_index();
        if (e) {
            /* the text is there but its index entry is not: undo, the message was not stored */
            index_remove((unsigned)index_pos(r->id));
            next_id = r->id;
            lfs_remove(fs, path);
        }
    }
    stats.last_add_us = ktime_to_us(ktime_now() - t0);
    if (e) {
        kprintf("sms store: writing message %u failed (%d)\n", r->id, e);
        return result(e);
    }
    stats.adds++;
    count_unread();
    return STORE_OK;
}

int store_update(const struct sms_record *r)
{
    int i = index_pos(r->id);
    if (!fs || i < 0)
        return STORE_NOT_FOUND;
    ktime_t t0 = ktime_now();
    struct sms_record old = recs[i];
    recs[i] = *r;
    int e = write_index();
    stats.last_update_us = ktime_to_us(ktime_now() - t0);
    if (e) {
        recs[i] = old;
        kprintf("sms store: updating message %u failed (%d)\n", r->id, e);
        return result(e);
    }
    stats.updates++;
    entry_from(&idx[i], r);
    count_unread();
    return STORE_OK;
}

int store_read(uint32_t id, struct sms_record *r, char *text, unsigned max)
{
    int i = index_pos(id);
    if (!fs || i < 0)
        return STORE_NOT_FOUND;
    if (r)
        *r = recs[i];
    if (!text)
        return 0;
    char path[24];
    message_path(path, id);
    return read_file(path, 0, text, max);
}

int store_delete(uint32_t id)
{
    int i = index_pos(id);
    if (!fs || i < 0)
        return STORE_NOT_FOUND;
    struct sms_record old = recs[i];
    index_remove((unsigned)i);
    int e = write_index();
    if (e) {
        index_insert(&old);
        return result(e);
    }
    char path[24];
    message_path(path, id);
    lfs_remove(fs, path);      /* a power cut before this leaves an unlisted file: wasted, never shown */
    stats.deletes++;
    count_unread();
    return STORE_OK;
}

/* ---- parts ---- */

static int part_find(const struct store_part_key *k, unsigned seq)
{
    for (unsigned i = 0; i < parts_count; i++)
        if (parts[i].key == k->key && parts[i].ref == k->ref && parts[i].total == k->total && part_seq[i] == seq)
            return (int)i;
    return -1;
}

int store_part_exists(const struct store_part_key *k, unsigned seq)
{
    return part_find(k, seq) >= 0;
}

int store_part_put(const struct store_part_key *k, unsigned seq, const struct sms_record *r, const char *text,
                   unsigned len)
{
    if (!fs)
        return STORE_ERROR;
    if (simulate_full || (part_find(k, seq) < 0 && parts_count >= PARTS_MAX))
        return STORE_FULL;
    char path[48];
    part_path(path, k, seq);
    int e = write_file(path, r, text, len);
    if (e)
        return result(e);
    if (part_find(k, seq) < 0) {
        parts[parts_count] = *k;
        part_seq[parts_count++] = (uint8_t)seq;
    }
    return STORE_OK;
}

int store_part_read(const struct store_part_key *k, unsigned seq, struct sms_record *r, char *out, unsigned max)
{
    char path[48];
    part_path(path, k, seq);
    return read_file(path, r, out, max);
}

void store_part_delete(const struct store_part_key *k, unsigned seq)
{
    char path[48];
    part_path(path, k, seq);
    if (fs)
        lfs_remove(fs, path);
    int i = part_find(k, seq);
    if (i >= 0) {
        parts[i] = parts[parts_count - 1];
        part_seq[i] = part_seq[parts_count - 1];
        parts_count--;
    }
}

/* ---- drafts ---- */

static int draft_pos(uint32_t key)
{
    for (unsigned i = 0; i < drafts_count; i++)
        if (drafts[i].key == key)
            return (int)i;
    return -1;
}

const struct store_draft *store_draft_find(uint32_t key)
{
    int i = draft_pos(key);
    return i < 0 ? 0 : &drafts[i];
}

const struct store_draft *store_drafts(unsigned *n)
{
    *n = drafts_count;
    return drafts;
}

void store_draft_delete(uint32_t key)
{
    int i = draft_pos(key);
    if (i < 0)
        return;
    char path[24];
    draft_path(path, key);
    if (fs)
        lfs_remove(fs, path);
    drafts[i] = drafts[--drafts_count];
}

int store_draft_put(const char *number, uint32_t time, const char *text, unsigned len)
{
    uint32_t key = phonenum_key(number);
    if (!len) {
        store_draft_delete(key);
        return STORE_OK;
    }
    if (!fs)
        return STORE_ERROR;
    int i = draft_pos(key);
    if (i < 0 && drafts_count == STORE_DRAFTS) {
        unsigned oldest = 0;
        for (unsigned k = 1; k < drafts_count; k++)
            if (drafts[k].time < drafts[oldest].time)
                oldest = k;
        store_draft_delete(drafts[oldest].key);
    }
    struct draft_head h = { .time = time };
    for (unsigned k = 0; k < SMS_NUMBER_MAX; k++) {
        h.number[k] = number[k];
        if (!number[k])
            break;
    }
    h.number[SMS_NUMBER_MAX - 1] = 0;
    char path[24];
    draft_path(path, key);
    /* the text and its attribute in one commit: a power cut leaves the old draft or the new one */
    struct lfs_attr attr = { ATTR_DRAFT, &h, sizeof h };
    struct lfs_file_config fc = { .buffer = file_cache, .attrs = &attr, .attr_count = 1 };
    lfs_file_t f;
    int e = lfs_file_opencfg(fs, &f, path, LFS_O_WRONLY | LFS_O_CREAT | LFS_O_TRUNC, &fc);
    if (!e) {
        lfs_ssize_t w = lfs_file_write(fs, &f, text, len);
        int c = lfs_file_close(fs, &f);
        e = w < 0 ? (int)w : c;
    }
    if (e) {
        kprintf("sms store: writing the draft for %s failed (%d)\n", number, e);
        return result(e);
    }
    i = draft_pos(key);
    if (i < 0)
        i = (int)drafts_count++;
    struct store_draft *d = &drafts[i];
    d->key = key;
    d->time = time;
    memcpy(d->number, h.number, sizeof d->number);
    draft_head_text(d->head, text, len);
    return STORE_OK;
}

int store_draft_get(uint32_t key, char *out, unsigned max)
{
    if (draft_pos(key) < 0 || !fs || !max)
        return STORE_NOT_FOUND;
    char path[24];
    draft_path(path, key);
    struct lfs_file_config fc = { .buffer = file_cache };
    lfs_file_t f;
    if (lfs_file_opencfg(fs, &f, path, LFS_O_RDONLY, &fc))
        return STORE_NOT_FOUND;
    lfs_ssize_t n = lfs_file_read(fs, &f, out, max - 1);
    lfs_file_close(fs, &f);
    if (n < 0)
        return STORE_ERROR;
    if ((unsigned)n == max - 1) {
        /* cut by max: the last character must be whole */
        lfs_ssize_t lead = n;
        while (lead && ((uint8_t)out[lead - 1] & 0xC0) == 0x80)
            lead--;
        if (lead) {
            uint8_t c = (uint8_t)out[lead - 1];
            lfs_ssize_t need = c >= 0xF0 ? 4 : c >= 0xE0 ? 3 : c >= 0xC0 ? 2 : 1;
            if (n - (lead - 1) < need)
                n = lead - 1;
        }
    }
    out[n] = 0;
    return (int)n;
}
