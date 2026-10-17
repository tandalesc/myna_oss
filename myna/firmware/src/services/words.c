/* SPDX-License-Identifier: MIT */
/* Predictive text: candidates and My words (services/words.h). */
#include <stdint.h>

#include "fs/storage.h"
#include "kernel/timer.h"
#include "lib/dict.h"
#include "lib/keyseq.h"
#include "lib/mem.h"
#include "lib/print.h"
#include "lib/utf8.h"
#include "services/words.h"

#define USER_PATH "/words"
#define FILE_MAX  (WORDS_USER_MAX * WORD_MAX)

static char user[WORDS_USER_MAX][WORD_MAX];
static unsigned user_count;
static uint8_t loaded;
static uint8_t file_cache[STORAGE_FILE_CACHE];
static char file_buf[FILE_MAX];

char words_key(uint32_t c)
{
    if (c == '\'' || c == 0x2019)
        return '1';
    return keyseq_letter(c);
}

int words_keys_of(const char *word, char *keys, unsigned max)
{
    const char *p = word, *end = word + strlen(word);
    unsigned n = 0;
    while (p < end) {
        char k = words_key(utf8_next(&p, end));
        if (!k || n + 1 >= max)
            return -1;
        keys[n++] = k;
    }
    keys[n] = 0;
    return (int)n;
}

/* ASCII letters without regard to case (a candidate is not offered twice) */
static int same_word(const char *a, const char *b)
{
    for (; *a && *b; a++, b++) {
        char x = *a >= 'A' && *a <= 'Z' ? (char)(*a + 32) : *a, y = *b >= 'A' && *b <= 'Z' ? (char)(*b + 32) : *b;
        if (x != y)
            return 0;
    }
    return *a == *b;
}

/* ---- My words: the file ---- */

static void load(void)
{
    if (loaded)
        return;
    loaded = 1;
    lfs_t *fs = storage_fs(FS_USER);
    if (!fs)
        return;
    lfs_file_t f;
    struct lfs_file_config fc = { .buffer = file_cache };
    if (lfs_file_opencfg(fs, &f, USER_PATH, LFS_O_RDONLY, &fc))
        return;
    lfs_ssize_t n = lfs_file_read(fs, &f, file_buf, sizeof file_buf - 1);
    lfs_file_close(fs, &f);
    if (n <= 0)
        return;
    file_buf[n] = 0;
    for (char *p = file_buf; *p && user_count < WORDS_USER_MAX;) {
        char *eol = p;
        while (*eol && *eol != '\n')
            eol++;
        unsigned len = (unsigned)(eol - p);
        char keys[WORD_MAX];
        if (len && len < WORD_MAX) {
            memcpy(user[user_count], p, len);
            user[user_count][len] = 0;
            if (words_keys_of(user[user_count], keys, sizeof keys) > 0)
                user_count++;
        }
        p = *eol ? eol + 1 : eol;
    }
    kprintf("words: %u of my words read\n", user_count);
}

static void save(void)
{
    lfs_t *fs = storage_fs(FS_USER);
    if (!fs)
        return;
    unsigned n = 0;
    for (unsigned i = 0; i < user_count; i++) {
        unsigned len = (unsigned)strlen(user[i]);
        memcpy(file_buf + n, user[i], len);
        n += len;
        file_buf[n++] = '\n';
    }
    lfs_file_t f;
    struct lfs_file_config fc = { .buffer = file_cache };
    int r = lfs_file_opencfg(fs, &f, USER_PATH, LFS_O_WRONLY | LFS_O_CREAT | LFS_O_TRUNC, &fc);
    if (!r) {
        lfs_ssize_t w = lfs_file_write(fs, &f, file_buf, n);
        int c = lfs_file_close(fs, &f);        /* the commit: atomic */
        r = w < 0 ? (int)w : c;
    }
    if (r)
        kprintf("words: writing my words failed (%d)\n", r);
}

void words_learn(const char *word)
{
    char keys[WORD_MAX];
    if (strlen(word) >= WORD_MAX || words_keys_of(word, keys, sizeof keys) <= 0)
        return;
    load();
    unsigned i = 0;
    while (i < user_count && strcmp(user[i], word))
        i++;
    if (i == 0 && user_count)
        return;                /* first already: nothing changes */
    if (i == user_count) {
        if (user_count < WORDS_USER_MAX)
            user_count++;
        i = user_count - 1;    /* a new word: the least recent goes when the list is full */
    }
    memmove(user[1], user[0], (size_t)i * WORD_MAX);
    memcpy(user[0], word, strlen(word) + 1);
    kprintf("words: \"%s\" learnt (%u words)\n", word, user_count);
    save();
}

const char *words_user(unsigned i)
{
    load();
    return i < user_count ? user[i] : 0;
}

void words_forget(unsigned i)
{
    load();
    if (i >= user_count)
        return;
    memmove(user[i], user[i + 1], (size_t)(user_count - i - 1) * WORD_MAX);
    user_count--;
    save();
}

/* ---- candidates ---- */

static int add(char out[][WORD_MAX], int n, const char *w)
{
    if (n >= WORDS_CANDIDATES || !w[0])
        return n;
    for (int i = 0; i < n; i++)
        if (same_word(out[i], w))
            return n;
    memcpy(out[n], w, strlen(w) + 1);
    return n + 1;
}

int words_candidates(const char *keys, char out[][WORD_MAX], int *exact)
{
    load();
    unsigned k = (unsigned)strlen(keys);
    char w[WORD_MAX], wk[WORD_MAX];
    int n = 0;
    for (unsigned i = 0; i < user_count; i++)
        if (words_keys_of(user[i], wk, sizeof wk) == (int)k && !memcmp(wk, keys, k))
            n = add(out, n, user[i]);
    for (unsigned i = 0; n < WORDS_CANDIDATES && dict_exact(keys, i, w, sizeof w) > 0; i++)
        n = add(out, n, w);
    *exact = n > 0;
    if (n)
        return n;
    /* no whole word: the beginnings of longer ones */
    for (unsigned i = 0; i < user_count; i++)
        if (words_keys_of(user[i], wk, sizeof wk) > (int)k && !memcmp(wk, keys, k)) {
            /* the first k characters of the word (they are letters: one key each) */
            const char *p = user[i], *end = p + strlen(p);
            for (unsigned c = 0; c < k; c++)
                utf8_next(&p, end);
            memcpy(w, user[i], (size_t)(p - user[i]));
            w[p - user[i]] = 0;
            n = add(out, n, w);
        }
    for (unsigned i = 0; n < WORDS_CANDIDATES && dict_prefix(keys, i, w, sizeof w) > 0; i++)
        n = add(out, n, w);
    return n;
}

int words_complete(const char *keys, const char *shown, char *out)
{
    load();
    unsigned k = (unsigned)strlen(keys), s = (unsigned)strlen(shown);
    char wk[WORD_MAX];
    /* one of My words that starts with what is shown */
    for (unsigned i = 0; i < user_count; i++) {
        unsigned len = (unsigned)strlen(user[i]);
        if (len > s + 1 && words_keys_of(user[i], wk, sizeof wk) > (int)k && !memcmp(wk, keys, k)) {
            char head[WORD_MAX];
            memcpy(head, user[i], s);
            head[s] = 0;
            if (same_word(head, shown)) {
                memcpy(out, user[i], len + 1);
                return (int)len;
            }
        }
    }
    return dict_complete(keys, shown, out, WORD_MAX);
}
