/* SPDX-License-Identifier: MIT */
/* Key sequences (lib/keyseq.h). */
#include <stdint.h>

#include "lib/keyseq.h"
#include "lib/mem.h"
#include "lib/utf8.h"

static const char ascii[26] = { '2', '2', '2', '3', '3', '3', '4', '4', '4', '5', '5', '5', '6',
                                '6', '6', '7', '7', '7', '7', '8', '8', '8', '9', '9', '9', '9' };

/* Latin-1 letters, lower case (an upper-case one is 0x20 below it), U+00E0-U+00FF; '0': not a letter (the sign of
   division) */
static const char latin1[33] = "22222222333344443666666068888989";

/* Latin Extended-A, U+0100-U+017F: the base letter of each (Ā ā Ă ă Ą ą on a, ... ſ on s; Ĳ, Œ on their first) */
static const char extended_a[129] = "aaaaaaccccccccddddeeeeeeeeeegggggggghhhhiiiiiiiiiiiijjkkkllllllllllnnnnnnnnnoooooo"
                                    "oorrrrrrssssssssttttttuuuuuuuuuuuuwwyyyzzzzzzs";
_Static_assert(sizeof extended_a == 129, "one letter for each of U+0100-U+017F");

char keyseq_letter(uint32_t c)
{
    if (c < 0x80) {
        c |= 0x20;
        return c >= 'a' && c <= 'z' ? ascii[c - 'a'] : 0;
    }
    if (c < 0x100) {
        if (c >= 0xC0 && c <= 0xDE && c != 0xD7)
            c += 0x20;
        if (c >= 0xE0 && latin1[c - 0xE0] != '0')
            return latin1[c - 0xE0];
        return c == 0xDF ? '7' : 0;            /* sharp s */
    }
    if (c < 0x180)
        return ascii[extended_a[c - 0x100] - 'a'];
    if (c >= 0x218 && c <= 0x21B)
        return c < 0x21A ? '7' : '8';          /* Romanian s and t with a comma */
    /* Cyrillic: upper case to lower, then the Russian layout, four letters a key */
    if (c >= 0x410 && c <= 0x42F)
        c += 0x20;
    else if (c >= 0x400 && c <= 0x40F)
        c += 0x50;
    else if (c == 0x490)
        c = 0x491;
    if (c >= 0x430 && c <= 0x44F)
        return (char)('2' + (c - 0x430) / 4);
    switch (c) {
    case 0x491:                /* ґ */
        return '2';
    case 0x451:                /* ё */
    case 0x454:                /* є */
        return '3';
    case 0x456:                /* і */
    case 0x457:                /* ї */
        return '4';
    case 0x45E:                /* ў */
        return '6';
    }
    return 0;
}

int keyseq_name(const char *name, char *keys, uint8_t *at, unsigned max)
{
    const char *p = name, *end = name + strlen(name);
    unsigned n = 0;
    while (p < end && n + 1 < max) {
        const char *start = p;
        uint32_t c = (uint8_t)*p;
        char k;
        if (c < 0x80) {        /* most names: a letter's key from the table, no decoding */
            p++;
            k = c >= '0' && c <= '9' ? (char)c : (c | 0x20) >= 'a' && (c | 0x20) <= 'z' ? ascii[(c | 0x20) - 'a'] : 0;
        } else {
            c = utf8_next(&p, end);
            k = keyseq_letter(c);
        }
        if (!k) {
            if (c == '\'' || c == 0x2019 || !n || keys[n - 1] == ' ')
                continue;      /* an apostrophe joins; a break is one, and none at the start */
            k = ' ';
        }
        if (at)
            at[n] = (uint8_t)(start - name < 255 ? start - name : 255);
        keys[n++] = k;
    }
    while (n && keys[n - 1] == ' ')
        n--;
    keys[n] = 0;
    return (int)n;
}

int keyseq_word(const char *keys, const char *query, unsigned n)
{
    char first = query[0];
    for (const char *p = keys; *p;) {
        /* p is where a word starts */
        if (*p == first) {
            unsigned i = 1;
            for (; i < n; i++) {
                char k = p[i];
                if (k != query[i] && !(k == ' ' && (query[i] == '0' || query[i] == '1')))
                    break;     /* the end of the keys (0) ends it too */
            }
            if (i == n)
                return (int)(p - keys);
        }
        while (*p && *p != ' ')
            p++;
        if (*p)
            p++;
    }
    return -1;
}

int keyseq_find(const char *text, const char *query, unsigned n, unsigned *which)
{
    char first = query[0];
    const char *start = text;
    unsigned w = 0;
    for (const char *p = text; *p; p++) {
        if (*p == ' ') {
            w++;
            start = p + 1;
        } else if (*p == first) {
            unsigned i = 1;
            while (i < n && p[i] == query[i] && p[i] != ' ')
                i++;
            if (i == n) {
                *which = w;
                return (int)(p - start);
            }
        }
    }
    return -1;
}
