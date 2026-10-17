/* SPDX-License-Identifier: MIT */
/* The built-in dictionary of predictive text (lib/dict.h); the index's format is described in myna/tools/mkdict.py.
 *
 * Every lookup is one range of the index: the words whose key sequence starts with the keys typed, which are next to
 * each other because the words are sorted by key sequence. Its start is found by a binary search over the blocks (the
 * key sequence of a block's first word, which is stored whole), then by reading entries; the words whose sequence is
 * exactly the keys come first in it, the longer ones follow. Entries are read one after the other (each word shares
 * its first letters with the one before it), keeping the word in a buffer. */
#include <stdint.h>

#include "dict_data.h"
#include "lib/dict.h"

#define COMPLETE_CLASS 207     /* round(16 log2(8001)): a completion must be among the 8,000 most frequent words */
#define COMPLETE_MORE  2       /* and add at least this many letters */
#define BEGINNINGS     48      /* distinct beginnings kept by dict_prefix (the best ones when there are more) */

#ifdef MYNA_DICT_STATS
unsigned dict_stat_entries;
#define COUNT_ENTRY() (dict_stat_entries++)
#else
#define COUNT_ENTRY() ((void)0)
#endif

/* the key of a letter ('2'-'9', '1' for the apostrophe), 0 for anything else */
static const char key_of[128] = {
    ['\''] = '1',
    ['a'] = '2', ['b'] = '2', ['c'] = '2', ['d'] = '3', ['e'] = '3', ['f'] = '3', ['g'] = '4', ['h'] = '4', ['i'] = '4',
    ['j'] = '5', ['k'] = '5', ['l'] = '5', ['m'] = '6', ['n'] = '6', ['o'] = '6', ['p'] = '7', ['q'] = '7', ['r'] = '7',
    ['s'] = '7', ['t'] = '8', ['u'] = '8', ['v'] = '8', ['w'] = '9', ['x'] = '9', ['y'] = '9', ['z'] = '9',
    ['A'] = '2', ['B'] = '2', ['C'] = '2', ['D'] = '3', ['E'] = '3', ['F'] = '3', ['G'] = '4', ['H'] = '4', ['I'] = '4',
    ['J'] = '5', ['K'] = '5', ['L'] = '5', ['M'] = '6', ['N'] = '6', ['O'] = '6', ['P'] = '7', ['Q'] = '7', ['R'] = '7',
    ['S'] = '7', ['T'] = '8', ['U'] = '8', ['V'] = '8', ['W'] = '9', ['X'] = '9', ['Y'] = '9', ['Z'] = '9',
};

/* reading the entries in order */
struct cursor {
    uint32_t at;               /* offset of the next entry in dict_bytes */
    uint32_t left;             /* entries after the current one */
    unsigned len;              /* the current word */
    unsigned shared;           /* its letters in common with the word before it */
    uint8_t cls;               /* its frequency class (0 = the most frequent) */
    char word[DICT_LONGEST + 1];
};

static void start(struct cursor *c, uint32_t block)
{
    c->at = dict_block_at[block];
    c->left = dict_count - block * DICT_BLOCK;
    c->len = 0;
}

/* the next entry into c->word; 0 at the end of the index */
static int next(struct cursor *c)
{
    if (!c->left)
        return 0;
    c->left--;
    COUNT_ENTRY();
    const uint8_t *p = dict_bytes + c->at;
    unsigned shared = p[0] >> 4, n = p[0] & 15;
    c->cls = p[1];
    p += 2;
    if (n == 15)
        n = *p++;
    for (unsigned i = 0; i < n; i++)
        c->word[shared + i] = (char)p[i];
    c->len = shared + n;
    c->word[c->len] = 0;
    c->shared = shared;
    c->at = (uint32_t)(p + n - dict_bytes);
    return 1;
}

/* the word's key sequence against keys[0..k): < 0 before (it is shorter and a beginning of keys, or smaller), 0 when it
   starts with keys, > 0 after */
static int compare(const char *w, unsigned len, const char *keys, unsigned k)
{
    for (unsigned i = 0; i < k; i++) {
        if (i == len)
            return -1;
        int d = key_of[(uint8_t)w[i] & 127] - keys[i];
        if (d)
            return d;
    }
    return 0;
}

/* the length of keys if it is a key sequence the index can hold, else 0 */
static unsigned check(const char *keys)
{
    unsigned k = 0;
    while (keys[k]) {
        if (keys[k] < '1' || keys[k] > '9' || k == DICT_LONGEST)
            return 0;
        k++;
    }
    return k;
}

/* the cursor on the first word whose sequence starts with keys; 0 if there is none */
static int seek(struct cursor *c, const char *keys, unsigned k)
{
    /* the last block whose first word comes before keys: the range starts in it or at the start of the next one */
    uint32_t lo = 0, hi = dict_block_count;
    while (hi - lo > 1) {
        uint32_t mid = (lo + hi) / 2;
        const uint8_t *p = dict_bytes + dict_block_at[mid];
        unsigned n = p[0] & 15, off = 2;
        if (n == 15)
            n = p[off++];
        if (compare((const char *)p + off, n, keys, k) < 0)
            lo = mid;
        else
            hi = mid;
    }
    start(c, lo);
    while (next(c)) {
        int d = compare(c->word, c->len, keys, k);
        if (d >= 0)
            return d == 0;
    }
    return 0;
}

static int put(char *out, unsigned max, const char *w, unsigned len)
{
    if (!max)
        return 0;
    if (len > max - 1)
        len = max - 1;
    for (unsigned i = 0; i < len; i++)
        out[i] = w[i];
    out[len] = 0;
    return (int)len;
}

static char lower(char c)
{
    return c >= 'A' && c <= 'Z' ? (char)(c + 32) : c;
}

static int same_letters(const char *a, const char *b, unsigned n)
{
    for (unsigned i = 0; i < n; i++)
        if (lower(a[i]) != lower(b[i]))
            return 0;
    return 1;
}

unsigned dict_words(void)
{
    return dict_count;
}

int dict_exact(const char *keys, unsigned n, char *out, unsigned max)
{
    struct cursor c;
    unsigned k = check(keys);
#ifdef MYNA_DICT_STATS
    dict_stat_entries = 0;
#endif
    if (!k || !seek(&c, keys, k))
        return 0;
    do {
        if (c.len != k || compare(c.word, c.len, keys, k))
            return 0;          /* past the words of exactly these keys */
        if (!n--)
            return put(out, max, c.word, c.len);
    } while (next(&c));
    return 0;
}

/* one or two keys: the answer made at build time (a scan would read up to a quarter of the index) */
static int prefix_short(const char *keys, unsigned k, unsigned n, char *out, unsigned max)
{
    unsigned seq = k == 1 ? (unsigned)(keys[0] - '1') : 9 + (unsigned)(keys[0] - '1') * 9 + (unsigned)(keys[1] - '1');
    const uint8_t *p = dict_short + dict_short_at[seq];
    if (n >= p[0])
        return 0;
    return put(out, max, (const char *)p + 1 + n * k, k);
}

#ifdef MYNA_DICT_STATS
int dict_prefix_scan(const char *keys, unsigned n, char *out, unsigned max)
#else
static int dict_prefix_scan(const char *keys, unsigned n, char *out, unsigned max)
#endif
{
    struct cursor c;
    unsigned k = check(keys);
#ifdef MYNA_DICT_STATS
    dict_stat_entries = 0;
#endif
    if (!k || !seek(&c, keys, k))
        return 0;
    /* the distinct beginnings and the class of the best word with each; `cur` is the current word's, which stays
       while the words share at least k letters */
    char begin[BEGINNINGS][DICT_LONGEST + 1];
    uint8_t best[BEGINNINGS];
    unsigned count = 0;
    int cur = -1, first = 1;
    do {
        if (c.shared < k || first) {
            /* the first k letters changed (their keys only change with them): past the range, or a new beginning */
            if (compare(c.word, c.len, keys, k))
                break;
            cur = -1;
            first = 0;
        }
        if (c.len == k)
            continue;          /* a word of exactly these keys */
        if (cur < 0) {
            for (unsigned i = 0; i < count; i++)
                if (same_letters(begin[i], c.word, k)) {
                    cur = (int)i;
                    break;
                }
            if (cur < 0) {
                unsigned slot = count;
                if (count == BEGINNINGS) {
                    /* full: the new one takes the place of the worst, if it is better */
                    slot = 0;
                    for (unsigned i = 1; i < count; i++)
                        if (best[i] > best[slot])
                            slot = i;
                    if (best[slot] <= c.cls)
                        continue;
                } else {
                    count++;
                }
                for (unsigned i = 0; i < k; i++)
                    begin[slot][i] = c.word[i];
                begin[slot][k] = 0;
                best[slot] = 0xFF;
                cur = (int)slot;
            }
        }
        if (c.cls < best[cur]) {
            best[cur] = c.cls;
            for (unsigned i = 0; i < k; i++)
                begin[cur][i] = c.word[i];     /* the case of the best word */
        }
    } while (next(&c));
    /* the n-th best: the one with n others better than it (ties: the one met first) */
    for (unsigned i = 0; i < count; i++) {
        unsigned better = 0;
        for (unsigned j = 0; j < count; j++)
            better += best[j] < best[i] || (best[j] == best[i] && j < i);
        if (better == n)
            return put(out, max, begin[i], k);
    }
    return 0;
}

int dict_prefix(const char *keys, unsigned n, char *out, unsigned max)
{
    unsigned k = check(keys);
#ifdef MYNA_DICT_STATS
    dict_stat_entries = 0;
#endif
    if (k && k <= 2)
        return prefix_short(keys, k, n, out, max);
    return dict_prefix_scan(keys, n, out, max);
}

int dict_complete(const char *keys, const char *shown, char *out, unsigned max)
{
    struct cursor c;
    unsigned k = check(keys);
#ifdef MYNA_DICT_STATS
    dict_stat_entries = 0;
#endif
    if (k < 2 || !seek(&c, keys, k))
        return 0;
    for (unsigned i = 0; i < k; i++)
        if (!shown[i])
            return 0;
    unsigned word_cls = 0x100, best_cls = 0x100;
    char best[DICT_LONGEST + 1];
    unsigned best_len = 0;
    int match = 0, first = 1;  /* match: the current word's first k letters are the letters shown */
    do {
        if (c.shared < k || first) {
            if (compare(c.word, c.len, keys, k))
                break;         /* past the range */
            match = same_letters(c.word, shown, k);
            first = 0;
        }
        if (!match)
            continue;
        if (c.len == k) {
            if (c.cls < word_cls)
                word_cls = c.cls;  /* `shown` is itself a word */
        } else if (c.len >= k + COMPLETE_MORE && c.cls < best_cls) {
            best_cls = c.cls;
            best_len = c.len;
            for (unsigned i = 0; i < c.len; i++)
                best[i] = c.word[i];
        }
    } while (next(&c));
    if (best_cls > COMPLETE_CLASS || best_cls >= word_cls)
        return 0;
    for (unsigned i = 0; i < k; i++)
        best[i] = shown[i];
    return put(out, max, best, best_len);
}
