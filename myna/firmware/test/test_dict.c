/* SPDX-License-Identifier: MIT */
/* Host tests of the predictive-text dictionary (lib/dict.h) on the index the build made from myna/assets/words.
 *
 *   make -C myna/firmware host-test
 *
 * The expected orders are what a person would want first from the word list's frequencies (12dicts' bands); with
 * -v every lookup is printed with the entries it read. */
#include <stdio.h>
#include <string.h>

#include "lib/dict.h"

int dict_prefix_scan(const char *keys, unsigned n, char *out, unsigned max);  /* MYNA_DICT_STATS: no short table */

static int failures, checks, verbose;
static unsigned most_entries;
static char most_what[64];

#define CHECK(cond)                                                                                                    \
    do {                                                                                                               \
        checks++;                                                                                                      \
        if (!(cond)) {                                                                                                 \
            failures++;                                                                                                \
            printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                                                     \
        }                                                                                                              \
    } while (0)

static void note(const char *what, const char *keys)
{
    if (dict_stat_entries > most_entries) {
        most_entries = dict_stat_entries;
        snprintf(most_what, sizeof most_what, "%s(%s)", what, keys);
    }
}

/* the candidates of keys as "a b c" (at most 8) */
static const char *exact(const char *keys)
{
    static char out[256];
    char w[40];
    out[0] = 0;
    for (unsigned n = 0; n < 8 && dict_exact(keys, n, w, sizeof w); n++) {
        note("exact", keys);
        if (n)
            strcat(out, " ");
        strcat(out, w);
    }
    note("exact", keys);
    if (verbose)
        printf("  exact %-10s %-40s (%u entries)\n", keys, out, dict_stat_entries);
    return out;
}

static const char *prefix(const char *keys)
{
    static char out[256];
    char w[40];
    out[0] = 0;
    for (unsigned n = 0; n < 6 && dict_prefix(keys, n, w, sizeof w); n++) {
        note("prefix", keys);
        if (n)
            strcat(out, " ");
        strcat(out, w);
    }
    if (verbose)
        printf("  prefix %-9s %-40s (%u entries)\n", keys, out, dict_stat_entries);
    return out;
}

static const char *complete(const char *keys, const char *shown)
{
    static char out[64];
    out[0] = 0;
    dict_complete(keys, shown, out, sizeof out);
    note("complete", keys);
    if (verbose)
        printf("  complete %-7s %-8s -> %-20s (%u entries)\n", keys, shown, out, dict_stat_entries);
    return out;
}

/* w is among the first n candidates of keys */
static int among(const char *list, const char *w, int n)
{
    char copy[256];
    strcpy(copy, list);
    int i = 0;
    for (char *t = strtok(copy, " "); t && i < n; t = strtok(0, " "), i++)
        if (!strcmp(t, w))
            return 1;
    return 0;
}

static int first(const char *list, const char *w)
{
    return among(list, w, 1);
}

int main(int argc, char **argv)
{
    verbose = argc > 1 && !strcmp(argv[1], "-v");
    char w[40];
    CHECK(dict_words() > 20000);

    /* the classic collisions: the more frequent word first */
    CHECK(first(exact("4663"), "good"));
    CHECK(among(exact("4663"), "home", 3) && among(exact("4663"), "gone", 3));
    CHECK(among(exact("4663"), "hood", 8));
    CHECK(first(exact("43556"), "hello"));
    CHECK(first(exact("8447"), "this"));
    CHECK(first(exact("63"), "of") && among(exact("63"), "me", 2));
    CHECK(first(exact("46"), "in") && among(exact("46"), "go", 3));
    CHECK(first(exact("43"), "he") && among(exact("43"), "if", 2));
    CHECK(first(exact("843"), "the"));
    CHECK(first(exact("968"), "you"));
    CHECK(first(exact("2"), "a"));
    CHECK(first(exact("4"), "I"));                     /* the capital is kept */
    CHECK(first(exact("416"), "I'm"));                 /* the apostrophe is key 1 */
    CHECK(first(exact("36618"), "don't"));
    CHECK(first(exact("666329"), "Monday"));
    CHECK(among(exact("5477"), "kiss", 2) && among(exact("5477"), "lips", 2));
    CHECK(among(exact("2665"), "book", 2) && among(exact("2665"), "cool", 2));

    /* the end of the candidates, and keys that are no word */
    unsigned n = 0;
    while (dict_exact("4663", n, w, sizeof w))
        n++;
    CHECK(n >= 4 && n < 12);
    CHECK(!dict_exact("4663", n, w, sizeof w) && !dict_exact("4663", 99, w, sizeof w));
    CHECK(!strcmp(exact("23288"), ""));                /* "beaut" is no word here ... */
    CHECK(first(prefix("23288"), "beaut"));            /* ... but the beginning of beautiful */
    CHECK(!strcmp(exact("99999999"), "") && !strcmp(prefix("99999999"), ""));
    CHECK(!dict_exact("", 0, w, sizeof w) && !dict_prefix("", 0, w, sizeof w));
    CHECK(!dict_exact("46a3", 0, w, sizeof w) && !dict_exact("4603", 0, w, sizeof w));
    CHECK(!dict_exact("4444444444444444444444444444444444444444", 0, w, sizeof w));
    CHECK(first(prefix("4"), "h") || first(prefix("4"), "g") || first(prefix("4"), "i"));
    CHECK(among(prefix("84"), "th", 1));

    /* completion: only when worth it */
    CHECK(!strcmp(complete("2328", "beau"), "beauty"));       /* more frequent than beautiful */
    CHECK(!strcmp(complete("2328", "Beau"), "Beauty"));       /* the case shown is kept */
    CHECK(!strcmp(complete("843", "the"), ""));                /* "the" itself is more frequent than any longer */
    CHECK(!strcmp(complete("4", "g"), ""));                    /* one key: nothing */
    CHECK(!strcmp(complete("2328", "adau"), ""));              /* letters that start no word */
    complete("7663", "some");
    complete("26678", "compu");
    complete("8346", "tele");

    /* buffer limits: a word is cut to fit, never written past max */
    char small[4] = { 'x', 'x', 'x', 'x' };
    CHECK(dict_exact("43556", 0, small, 3) == 2 && !strcmp(small, "he") && small[3] == 'x');
    CHECK(dict_exact("43556", 0, small, 0) == 0 && small[0] == 'h');
    CHECK(dict_prefix("23288", 0, small, 1) == 0 && small[0] == 0);
    char big[64];
    CHECK(dict_complete("2328", "beau", big, 5) == 4 && !strcmp(big, "beau"));

    /* the build's answers for one and two keys are what a scan of the index finds */
    int same = 1;
    for (unsigned s = 0; s < 90; s++) {
        char keys[3] = { (char)('1' + (s < 9 ? s : (s - 9) / 9)), (char)(s < 9 ? 0 : '1' + (s - 9) % 9), 0 };
        for (unsigned i = 0; i < 20; i++) {
            char a[8] = "", b[8] = "";
            int la = dict_prefix(keys, i, a, sizeof a), lb = dict_prefix_scan(keys, i, b, sizeof b);
            if (la != lb || strcmp(a, b)) {
                printf("  short table %s #%u: \"%s\", the scan \"%s\"\n", keys, i, a, b);
                same = 0;
            }
            if (!la)
                break;
        }
    }
    CHECK(same);
    CHECK(!strcmp(prefix("7"), "s r p q") && !strcmp(prefix("41"), "I'"));

    /* the most work one lookup did, here and on the shortest keys of every first key */
    const char *one[] = { "2", "3", "4", "5", "6", "7", "8", "9", "22", "27", "73", "84" };
    for (unsigned i = 0; i < sizeof one / sizeof one[0]; i++) {
        exact(one[i]);
        prefix(one[i]);
        if (one[i][1])
            complete(one[i], one[i][0] == '8' ? "th" : one[i][0] == '7' ? "re" : one[i][1] == '7' ? "ar" : "ca");
    }
    printf("dict: %u words; the most entries one lookup read: %u (%s)\n", dict_words(), most_entries, most_what);
    printf("%d checks, %d failed\n", checks, failures);
    return failures != 0;
}
